"""Deterministische verwerking van de lokale dagsnapshot in de SQLite-queue."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

from ariadne import clone_lock, week_name
from ingress_queue import IngressQueue

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


def queue_fiche(identity, payload, day):
    if (not isinstance(payload, dict)
            or set(payload) != {'schema_version', 'topic', 'date', 'content'}
            or type(payload['schema_version']) is not int or payload['schema_version'] != 1
            or type(payload['topic']) is not int or payload['topic'] not in (1, 2, 3)
            or payload['date'] != day.isoformat()
            or not isinstance(payload['content'], str) or not payload['content'].strip()):
        raise ValueError(f'Ongeldige fiche: queue:{identity}')
    data = payload['content'].encode('utf-8')
    return Fiche(f'queue:{identity}', payload['topic'], data, hashlib.sha256(data).hexdigest())


def weave(fiches, week, day, count=token_count, limit=LIMIT, reserve=RESERVE):
    threads = []
    current = []
    current_topic = None
    part = 1
    def render(items, topic, number):
        head = f'WEEKENDKRANT-DRAAD-1\nweek: {week}\ndate: {day}\ntopic: {topic}\npart: {number}\ntokenizer: {TOKENIZER}\nreserved_tokens: {reserve}\n\n'
        return head + ''.join(f'\n--- SOURCE {f.path} sha256={f.sha256} bytes={len(f.data)} ---\n' +
                              f.data.decode('utf-8') + '\n--- END SOURCE ---\n' for f in items)
    def finish():
        text = render(current, current_topic, part)
        threads.append({'topic': current_topic, 'part': part, 'text': text,
                        'tokens': count(text), 'sources': list(current)})
    for fiche in sorted(fiches, key=lambda f: (f.topic, f.path)):
        if fiche.topic != current_topic:
            if current:
                finish()
            current, current_topic, part = [], fiche.topic, 1
        if count(render(current + [fiche], current_topic, part)) + reserve > limit:
            if current:
                finish()
                current = []
                part += 1
            if count(render([fiche], current_topic, part)) + reserve > limit:
                raise ValueError(f'Eén fiche overschrijdt tokenbudget: {fiche.path}')
        current.append(fiche)
    if current:
        finish()
    return threads


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
    return db


def status(db, day, state, commit=None, manifest=None, error=None):
    db.execute('INSERT INTO days VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET '
               'status=excluded.status, commit_sha=excluded.commit_sha, '
               'manifest_sha256=excluded.manifest_sha256, error=excluded.error',
               (str(day), week_name(day), state, commit, manifest, error))
    db.execute('INSERT INTO attempts(day,status,error) VALUES (?,?,?)', (str(day), state, error))


def write_thread(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.ariadne-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
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
    for worktree in (root, (root.parent / 'weekworktree').resolve()):
        if path == worktree or worktree in path.parents:
            raise ValueError('Operationele staat moet buiten beide Git-working trees staan')
    return path


def run_daily(root, db_path=DB_PATH, output=OUTPUT_PATH, now=None):
    day = local_day(now)
    week = week_name(day)
    root = Path(root).resolve()
    db_path, output = outside_repo(root, db_path), outside_repo(root, output)
    logger.info('Dagverwerking gestart: datum=%s week=%s zone=Europe/Brussels', day, week)
    with clone_lock(root):
        db = database(db_path)
        try:
            queue = IngressQueue(db_path)
            # Fix the snapshot and exclude concurrent writers until commit/rollback.
            # No status is changed before validation and the complete thread plan.
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT status FROM days WHERE day=?', (str(day),)).fetchone()
            if previous and previous[0] == 'success':
                db.rollback()
                logger.info('Dag al geslaagd: %s', day)
                return {'date': str(day), 'week': week, 'status': 'success'}
            items = queue.pending_for_day(db, day)
            fiches = [queue_fiche(identity, payload, day) for identity, payload in items]
            threads = weave(fiches, week, day)
            status(db, day, 'success')
            for thread in threads:
                path = outside_repo(root, output / week / f'topic_{thread["topic"]}' /
                                    f'{day}_{thread["part"]:04d}.txt')
                data = thread['text'].encode('utf-8')
                write_thread(path, data)
                db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?)',
                           (str(path), str(day), thread['topic'], thread['part'],
                            hashlib.sha256(data).hexdigest(), thread['tokens'], TOKENIZER, RESERVE))
                for position, fiche in enumerate(thread['sources']):
                    db.execute('INSERT INTO sources VALUES (?,?,?,?,?)',
                               (str(day), fiche.path, fiche.sha256, str(path), position))
            queue.mark_processed(db, [identity for identity, _ in items])
            db.commit()
            logger.info('Dagverwerking geslaagd: datum=%s fiches=%s draden=%s', day, len(fiches), len(threads))
            return {'date': str(day), 'week': week, 'status': 'success', 'threads': len(threads)}
        except Exception as error:
            db.rollback()
            try:
                with db:
                    status(db, day, 'processing_error', error=str(error))
            except sqlite3.Error:
                logger.exception('Dagfout kon niet in SQLite worden geregistreerd: datum=%s', day)
            logger.exception('Dagverwerking mislukt: datum=%s status=processing_error', day)
            raise
        finally:
            db.close()


def week_report(db_path, day):
    monday = day - timedelta(days=day.weekday())
    db = database(db_path)
    try:
        result = []
        for offset in range(7):
            target = str(monday + timedelta(days=offset))
            row = db.execute('SELECT status FROM days WHERE day=?', (target,)).fetchone()
            if not row or row[0] != 'success':
                result.append({'date': target, 'status': row[0] if row else 'missing'})
        return result
    finally:
        db.close()


def prune_history(db_path, report_day):
    """Keep the reported Belgian ISO-week and the seven preceding ISO-weeks."""
    cutoff = report_day - timedelta(days=report_day.weekday(), weeks=7)
    db = database(db_path)
    try:
        with db:
            for table in ('sources', 'threads', 'attempts', 'days'):
                db.execute(f'DELETE FROM {table} WHERE day < ?', (str(cutoff),))
        # VACUUM cannot run within a transaction. Also retries a previous failed vacuum.
        db.execute('VACUUM')
        logger.info('SQLite-retentie voltooid: bewaard vanaf %s (acht ISO-weken)', cutoff)
        return cutoff
    finally:
        db.close()
