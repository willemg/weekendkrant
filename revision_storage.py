"""Reconstruct immutable revisions; retire only verified superseded file copies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from ariadne import LOCK_PATH, runtime_lock


def reconstruct(db, part_id, revision):
    """Return exact serialized bytes, verifying archive, hash and token audit.

    Logical revision rows/membership remain authoritative even without a file.
    Unknown serializers/tokenizers fail closed, never authorize deletion.
    """
    from daily import Fiche
    from part_format_v1 import render, TOKENIZER, token_count
    row = db.execute('''SELECT p.week,p.topic,p.part,r.sha256,r.tokens,
        r.tokenizer,r.reserved_tokens FROM parts p JOIN part_revisions r
        ON r.part_id=p.id WHERE p.id=? AND r.revision=?''', (part_id, revision)).fetchone()
    if row is None:
        raise ValueError('Onbekende revisie')
    week, topic, part, digest, tokens, tokenizer, reserve = row
    if tokenizer != TOKENIZER:
        raise ValueError('Onbekende revisietokenizer')
    rows = db.execute('''SELECT m.position,a.queue_id,a.topic,a.content,a.sha256,a.date,a.schema_version
        FROM revision_sources m LEFT JOIN source_archive a ON a.queue_id=m.queue_id
        WHERE m.part_id=? AND m.revision=? ORDER BY m.position''', (part_id, revision)).fetchall()
    if not rows or [r[0] for r in rows] != list(range(len(rows))):
        raise ValueError('Onvolledige revisiemembership')
    sources = []
    for _, identity, source_topic, data, source_hash, day, version in rows:
        if (identity is None or source_topic != topic or version != 1
                or hashlib.sha256(data).hexdigest() != source_hash):
            raise ValueError('Ongeldige bronprovenance')
        sources.append(Fiche(f'queue:{identity}', topic, data, source_hash, day, version))
    text = render(sources, week, topic, part, revision, reserve)
    data = text.encode('utf-8')
    if hashlib.sha256(data).hexdigest() != digest or token_count(text) != tokens:
        raise ValueError('Reconstructie wijkt af van hash/tokenaudit')
    return data


def _file(db, part_id, revision, output):
    row = db.execute('''SELECT p.week,p.topic,p.part,r.path FROM parts p
        JOIN part_revisions r ON r.part_id=p.id WHERE p.id=? AND r.revision=?''',
        (part_id, revision)).fetchone()
    if row is None:
        raise ValueError('Onbekende revisie')
    week, topic, part, raw = row
    root = Path(output).absolute()
    path = Path(raw)
    expected = root / week / f'topic_{topic}' / f'part_{part:04d}' / f'rev_{revision:04d}.txt'
    if path != expected or root.resolve() not in path.resolve().parents:
        raise ValueError('Revisiepad buiten canonieke dradenmap')
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('Symlinks zijn niet toegestaan bij revisiecleanup')
    if db.execute('SELECT count(*) FROM part_revisions WHERE path=?', (str(path),)).fetchone() != (1,):
        raise ValueError('Gedeeld revisiepad kan niet worden verwijderd')
    return path


def _protected(db, part_id, revision):
    return db.execute('''SELECT 1 FROM parts WHERE id=? AND active_revision=?
        UNION ALL SELECT 1 FROM part_offers WHERE part_id=? AND revision=?''',
        (part_id, revision, part_id, revision)).fetchone() is not None


def retire(db, part_id, revision, output, apply=False):
    """Verify a redundant copy, then unlink under a short fencing transaction.

    Caller holds runtime_lock. No DB audit row or source is changed. A crash
    before unlink leaves a redundant copy; after unlink reconstruction still works.
    """
    if db.in_transaction:
        raise ValueError('Cleanup vereist een vrije connection')
    if _protected(db, part_id, revision):
        return {'status': 'protected', 'bytes': 0}
    data = reconstruct(db, part_id, revision)
    path = _file(db, part_id, revision, output)
    if not path.exists():
        return {'status': 'missing', 'bytes': 0}
    if path.read_bytes() != data:
        raise ValueError('Revisiebestand wijkt af van reconstructie')
    if not apply:
        return {'status': 'eligible', 'bytes': len(data)}
    db.execute('BEGIN IMMEDIATE')
    try:
        if _protected(db, part_id, revision):
            result = {'status': 'protected', 'bytes': 0}
        else:
            path = _file(db, part_id, revision, output)
            # Recheck bytes immediately before unlink; never remove corrupted input.
            if path.exists() and path.read_bytes() != data:
                raise ValueError('Revisiebestand gewijzigd tijdens cleanup')
            path.unlink(missing_ok=True)
            sync_directory(path.parent)
            result = {'status': 'removed', 'bytes': len(data)}
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def sync_directory(path):
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def cleanup(db, output, apply=False):
    """Explicit legacy cleanup. No glob/unregistered orphan deletion."""
    rows = db.execute('SELECT part_id,revision FROM part_revisions ORDER BY part_id,revision').fetchall()
    results = [dict(part_id=p, revision=r, **retire(db, p, r, output, apply)) for p, r in rows]
    return {'apply': apply, 'bytes': sum(r['bytes'] for r in results), 'revisions': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=LOCK_PATH)
    parser.add_argument('--apply', action='store_true', help='Verwijder geverifieerde historische kopieën; standaard dry-run.')
    args = parser.parse_args()
    with runtime_lock(args.lock):
        # Existing DB only: dry-run must never create/migrate persistent state.
        db = sqlite3.connect(args.db.resolve().as_uri() + '?mode=rw', uri=True)
        try:
            result = cleanup(db, args.output, args.apply)
        finally:
            db.close()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
