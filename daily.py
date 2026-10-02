"""Deterministische verwerking van een expliciet afgesloten lokale dagoogst."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo

from ariadne import _git, _has_ref, clone_lock, week_name, inspect_worktrees, ensure_week_worktree

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


def parse_fiche(data):
    text = data.decode('utf-8')
    header = text.split('\n\n', 1)[0].splitlines()
    if len(header) != 3 or header[0] != 'WEEKENDKRANT-INGRESS-1':
        raise ValueError('Ongeldige ficheheader')
    if not re.fullmatch(r'topic: [1-4]', header[1]):
        raise ValueError('Ongeldig numeriek topic in fiche')
    if not re.fullmatch(r'date: \d{4}-\d{2}-\d{2}', header[2]):
        raise ValueError('Ongeldige lokale date in fiche')
    return int(header[1][7:]), date.fromisoformat(header[2][6:])


def blob(root, commit, path):
    return subprocess.check_output(['git', '-C', str(root), 'cat-file', 'blob',
                                    f'{commit}:{path}'], stderr=subprocess.PIPE)


def tree(root, commit, prefix):
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-r', '-z',
                                   commit, '--', prefix])
    entries = {}
    for entry in raw.split(b'\0'):
        if entry:
            metadata, path = entry.split(b'\t', 1)
            mode, kind, oid = metadata.decode().split()
            if mode != '100644' or kind != 'blob':
                raise ValueError('Alle ingressbestanden moeten gewone bestanden zijn')
            entries[path.decode('utf-8')] = oid
    return entries


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Dubbele JSON-sleutel')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def closed_harvest(root, commit, day):
    """Read immutable Git blobs, never worktree contents or symlinks."""
    week = week_name(day)
    prefix = f'ingress/{week}/'
    marker = f'{prefix}closed/{day.isoformat()}.json'
    entries = tree(root, commit, prefix)
    if marker not in entries:
        return None
    raw = blob(root, commit, marker)
    record = strict_json(raw)
    if (not isinstance(record, dict) or set(record) != {'schema_version', 'date', 'week', 'files'}
            or type(record['schema_version']) is not int or record['schema_version'] != 1
            or record['date'] != day.isoformat() or record['week'] != week
            or not isinstance(record['files'], list)):
        raise ValueError('Ongeldige gereedmelding')
    expected = {}
    for item in record['files']:
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256'}
                or not isinstance(item['path'], str)
                or not re.fullmatch(re.escape(prefix) + r'ingress_[0-9]+\.md', item['path'])
                or not isinstance(item['sha256'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])
                or item['path'] in expected):
            raise ValueError('Ongeldige of dubbele manifestfiche')
        expected[item['path']] = item['sha256']
    # The first publication fixes the manifest forever, even before first consumption.
    additions = _git(root, 'log', '--format=%H', '--diff-filter=A', commit, '--', marker).splitlines()
    if len(additions) != 1 or blob(root, additions[0], marker) != raw:
        raise ValueError('Gereedmelding gewijzigd of opnieuw aangemaakt na afsluiting')
    result = []
    for snapshot in dict.fromkeys((additions[0], commit)):
        found = {}
        for path in tree(root, snapshot, prefix):
            if path == prefix + '.gitkeep' or path.startswith(prefix + 'closed/'):
                continue
            if not re.fullmatch(re.escape(prefix) + r'ingress_[0-9]+\.md', path):
                raise ValueError(f'Onbekend ingressbestand: {path}')
            data = blob(root, snapshot, path)
            topic, fiche_day = parse_fiche(data)
            if week_name(fiche_day) != week:
                raise ValueError(f'Fiche buiten ISO-week: {path}')
            if fiche_day == day:
                digest = hashlib.sha256(data).hexdigest()
                found[path] = digest
                if snapshot == commit:
                    result.append(Fiche(path, topic, data, digest))
        if found != expected:
            raise ValueError('Afgesloten ficheverzameling wijkt af van manifest')
    return hashlib.sha256(raw).hexdigest(), result


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


def sync_week(root, day, commit):
    worktree = ensure_week_worktree(root, day)
    if _git(worktree, 'rev-parse', 'HEAD') != commit:
        raise ValueError('Weekworktree wijkt af van de gefetchte commit')
    return worktree


def run_daily(root, db_path=DB_PATH, output=OUTPUT_PATH, now=None,
              monotonic=time.monotonic, sleep=time.sleep):
    deadline = monotonic() + 3 * 60 * 60
    day = local_day(now)
    week = week_name(day)
    root = Path(root).resolve()
    db_path, output = outside_repo(root, db_path), outside_repo(root, output)
    logger.info('Dagverwerking gestart: datum=%s week=%s zone=Europe/Brussels', day, week)
    with clone_lock(root):
        db = database(db_path)
        previous = None
        try:
            previous = db.execute('SELECT status FROM days WHERE day=?', (str(day),)).fetchone()
            inspect_worktrees(root)
            if previous and previous[0] == 'success':
                logger.info('Dag al geslaagd: %s', day)
                return {'date': str(day), 'week': week, 'status': 'success'}
            if _git(root, 'status', '--porcelain'):
                raise ValueError('Vuile werkboom')
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError(f'Geen geldige gereedmelding binnen drie uur: {day}')
                _git(root, 'fetch', '--prune', 'origin', timeout=remaining)
                if monotonic() >= deadline:
                    raise TimeoutError(f'Wachtdeadline bereikt: {day}')
                ref = f'refs/remotes/origin/ingress/{week}'
                harvest = None
                if _has_ref(root, ref):
                    commit = _git(root, 'rev-parse', ref)
                    worktree = sync_week(root, day, commit)
                    harvest = closed_harvest(worktree, commit, day)
                if monotonic() >= deadline:
                    raise TimeoutError(f'Wachtdeadline bereikt: {day}')
                if harvest is not None:
                    break
                logger.info('Gereedmelding ontbreekt: datum=%s; volgende controle over tien minuten', day)
                sleep(max(0, min(600, deadline - monotonic())))
            manifest, fiches = harvest
            threads = weave(fiches, week, day)
            with db:
                status(db, day, 'success', commit, manifest)
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
            logger.info('Dagverwerking geslaagd: datum=%s fiches=%s draden=%s', day, len(fiches), len(threads))
            return {'date': str(day), 'week': week, 'status': 'success', 'threads': len(threads)}
        except Exception as error:
            state = 'timeout' if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)) else 'processing_error'
            with db:
                if previous and previous[0] == 'success':
                    db.execute('INSERT INTO attempts(day,status,error) VALUES (?,?,?)',
                               (str(day), state, str(error)))
                else:
                    status(db, day, state, error=str(error))
            logger.exception('Dagverwerking mislukt: datum=%s status=%s', day, state)
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
