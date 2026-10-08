"""Deterministische verwerking van de persistente backlogsnapshot in de SQLite-queue."""
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

from ariadne import LOCK_PATH, runtime_lock, week_name
from ingress_queue import IngressQueue
from parts import PartStore, migrate, weave

DB_PATH = Path('/home/weekendkrant/weekendkrant.sqlite3')
OUTPUT_PATH = Path('/home/weekendkrant/draden')
TOKENIZER = 'cl100k_base'
LIMIT = 35000
RESERVE = 5000
logger = logging.getLogger(__name__)


def local_day(now=None):
    now = datetime.now(ZoneInfo('Europe/Brussels')) if now is None else now
    if now.tzinfo is None:
        raise ValueError('De klok moet een timezone bevatten.')
    return now.astimezone(ZoneInfo('Europe/Brussels')).date()


def token_count(text):
    import tiktoken
    return len(tiktoken.get_encoding(TOKENIZER).encode(text, disallowed_special=()))


@dataclass(frozen=True)
class Fiche:
    path: str
    topic: int
    data: bytes
    sha256: str
    date: str = ''
    schema_version: int = 1


def queue_fiche(identity, payload, day):
    if (not isinstance(payload, dict)
            or set(payload) != {'schema_version', 'topic', 'date', 'content'}
            or type(payload['schema_version']) is not int or payload['schema_version'] != 1
            or type(payload['topic']) is not int or payload['topic'] not in (1, 2, 3)
            or payload['date'] != day.isoformat()
            or not isinstance(payload['content'], str) or not payload['content'].strip()):
        raise ValueError(f'Ongeldige fiche: queue:{identity}')
    data = payload['content'].encode('utf-8')
    return Fiche(f'queue:{identity}', payload['topic'], data,
                 hashlib.sha256(data).hexdigest(), str(day), payload['schema_version'])


def database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS days (
            day TEXT PRIMARY KEY, week TEXT NOT NULL, status TEXT NOT NULL,
            commit_sha TEXT, manifest_sha256 TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, day TEXT NOT NULL, status TEXT NOT NULL,
            error TEXT, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS threads (
            path TEXT PRIMARY KEY, day TEXT NOT NULL REFERENCES days(day),
            topic INTEGER NOT NULL, part INTEGER NOT NULL, sha256 TEXT NOT NULL,
            tokens INTEGER NOT NULL, tokenizer TEXT NOT NULL, reserved_tokens INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sources (
            day TEXT NOT NULL REFERENCES days(day), source_path TEXT NOT NULL,
            sha256 TEXT NOT NULL, thread_path TEXT NOT NULL REFERENCES threads(path),
            position INTEGER NOT NULL, PRIMARY KEY(day, source_path));
    ''')
    try:
        migrate(db)
        IngressQueue(path)
    except Exception:
        db.close()
        raise
    return db


def write_thread(path, data, replace_orphan=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.ariadne-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # The caller holds the runtime lock and permits replacement ONLY after
        # checking that this path has no registered revision provenance.
        # A deterministic retry can reuse an identical orphan without rewriting it.
        try:
            os.link(name, path)
        except FileExistsError:
            if path.read_bytes() != data:
                if not replace_orphan:
                    raise ValueError(f'Revisionpad bevat andere bytes: {path}')
                os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def outside_repo(root, path):
    path = Path(path).resolve()
    if path == root or root in path.parents:
        raise ValueError('Operationele staat moet buiten de applicatierepository staan')
    return path


def run_daily(root, db_path=DB_PATH, output=OUTPUT_PATH, now=None, lock_path=LOCK_PATH):
    day = local_day(now)
    week = week_name(day)
    root = Path(root).resolve()
    db_path, output = outside_repo(root, db_path), outside_repo(root, output)
    lock_path = outside_repo(root, lock_path)
    logger.info('Dagverwerking gestart: datum=%s week=%s zone=Europe/Brussels', day, week)
    with runtime_lock(lock_path):
        db = database(db_path)
        try:
            queue = IngressQueue(db_path)
            # Materialize one snapshot without retaining a SQLite write lock.
            items = queue.pending_for_day(db, day)
            grouped = {}
            new_sources = []
            for identity, payload in items:
                original_day = date.fromisoformat(payload['date'])
                fiche = queue_fiche(identity, payload, original_day)
                grouped.setdefault((week_name(original_day), fiche.topic), []).append(fiche)
                new_sources.append(fiche)
            if not items:
                logger.info('Geen verwerkbare pending fiches: datum=%s', day)
                return {'date': str(day), 'week': week, 'status': 'success', 'threads': 0}
            store = PartStore(db)
            snapshots, existing = {}, {}
            # A short read transaction gives a coherent part/membership snapshot.
            # Release it BEFORE planning, tokenization, or filesystem operations.
            db.execute('BEGIN')
            try:
                for key in sorted(grouped):
                    snapshots[key] = store.state(*key)
                    existing[key] = store.active_sources(snapshots[key])
            finally:
                db.rollback()
            plans, closures = [], {}
            for (original_week, topic), fiches in sorted(grouped.items()):
                key = (original_week, topic)
                revisions, closures[key] = weave(
                    fiches, original_week, topic, snapshots[key], existing[key],
                    count=token_count, limit=LIMIT, reserve=RESERVE)
                plans.extend(revisions)
            paths = []
            for plan in plans:
                path = outside_repo(root, output / plan.week / f'topic_{plan.topic}' /
                                    f'part_{plan.part:04d}' / f'rev_{plan.revision:04d}.txt')
                if db.execute('SELECT 1 FROM part_revisions WHERE path=?', (str(path),)).fetchone():
                    raise ValueError(f'Revisionpad heeft al succesvolle provenance: {path}')
                write_thread(path, plan.text.encode('utf-8'), replace_orphan=True)
                paths.append(path)
            # Only the final provenance/status update takes a SQLite write lock.
            db.execute('BEGIN IMMEDIATE')
            for identity, _ in items:
                row = db.execute('SELECT status FROM ingress_queue WHERE id=?', (identity,)).fetchone()
                if row != ('pending',):
                    raise ValueError(f'Queue-item niet pending: queue:{identity}')
            store.register(plans, paths, closures, snapshots, new_sources)
            queue.mark_processed(db, [identity for identity, _ in items])
            db.commit()
            logger.info('Dagverwerking geslaagd: datum=%s fiches=%s draden=%s', day, len(items), len(plans))
            return {'date': str(day), 'week': week, 'status': 'success', 'threads': len(plans)}
        except Exception as error:
            db.rollback()
            try:
                with db:
                    # A failed attempt must not downgrade successful output audit.
                    db.execute('INSERT INTO attempts(day,status,error) VALUES (?,?,?)',
                               (str(day), 'processing_error', str(error)))
            except sqlite3.Error:
                logger.exception('Pogingsfout kon niet in SQLite worden geregistreerd: datum=%s', day)
            logger.exception('Dagverwerking mislukt: datum=%s status=processing_error', day)
            raise
        finally:
            db.close()
