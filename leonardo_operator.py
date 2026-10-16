"""Local explicit experimental offer routing. No scheduler or public API."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from jobs import _id
from leonardo import LeonardoStore


def enqueue_offers(db, operation_id, dossier_id, base_version, offer_ids):
    # Offers are immutable and seal their part. Resolve IDs, never active revisions.
    if not isinstance(offer_ids, list) or not 1 <= len(offer_ids) <= 32:
        raise ValueError('Expected 1..32 explicit offers')
    for identity in offer_ids:
        _id(identity)
    if len(set(offer_ids)) != len(offer_ids):
        raise ValueError('Duplicate offer')
    revisions = []
    for identity in offer_ids:
        row = db.execute('''SELECT o.part_id,o.revision FROM part_offers o
            JOIN parts p ON p.id=o.part_id WHERE o.id=? AND p.is_open=0''',
                         (identity,)).fetchone()
        if row is None:
            raise ValueError('Unknown or unsealed offer')
        revisions.append(list(row))
    return LeonardoStore(db).enqueue(operation_id, dossier_id, base_version, revisions)


def rows(db, sql, args=()):
    cursor = db.execute(sql, args)
    return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor]


def context_usage(db, job):
    """Local measurements per attempt; unknown provider usage never means zero."""
    assignment = db.execute('SELECT tokens,snapshot FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone()
    if assignment is None:
        raise ValueError('Unknown Leonardo assignment')
    attempts = rows(db, 'SELECT id AS attempt_id,status FROM job_attempts WHERE job_id=? ORDER BY id', (job,))
    for attempt in attempts:
        attempt['recalls'] = rows(db, '''SELECT id AS sequence,recall_id,ref,bytes,tokens,recalled_at
            FROM leonardo_recalls WHERE attempt_id=? ORDER BY id''', (attempt['attempt_id'],))
        attempt['recall_count'] = len(attempt['recalls'])
        attempt['recall_tokens'] = sum(r['tokens'] for r in attempt['recalls'])
        attempt['recall_bytes'] = sum(r['bytes'] for r in attempt['recalls'])
        attempt['start_input_tokens'] = assignment[0]
        attempt['local_context_tokens'] = assignment[0] + attempt['recall_tokens']
        state = db.execute('SELECT tokens FROM leonardo_states WHERE attempt_id=?', (attempt['attempt_id'],)).fetchone()
        attempt['state_tokens'] = state[0] if state else None
        attempt['provider_usage'] = None
    return dict(tokenizer='cl100k_base', start_input_tokens=assignment[0],
                start_input_bytes=len(assignment[1].encode('utf-8')), attempts=attempts)


def inspect_job(db, job, compact=False):
    if db.in_transaction:
        raise ValueError('Inspection requires an idle connection')
    db.execute('BEGIN')  # One consistent read snapshot, without a writer lock.
    try:
        if compact:
            result = rows(db, '''SELECT a.job_id,a.dossier_id,j.status FROM leonardo_assignments a
                JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?''', (job,))
            if not result:
                raise ValueError('Unknown Leonardo assignment')
            return dict(result[0], context_usage=context_usage(db, job))
        return _inspect_job(db, job)
    finally:
        db.rollback()  # Release the read snapshot, including on unknown jobs.


def _inspect_job(db, job):
    result = rows(db, '''SELECT a.job_id,a.operation_id,a.dossier_id,a.base_version,
        a.snapshot,a.tokens AS input_tokens,j.status,j.created_at,j.updated_at,j.finished_at
        FROM leonardo_assignments a JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?''', (job,))
    if not result:
        raise ValueError('Unknown Leonardo assignment')
    report = result[0]
    snapshot = report.pop('snapshot')
    report['context_usage'] = context_usage(db, job)
    report['input_bytes'] = len(snapshot.encode('utf-8'))
    assignment = json.loads(snapshot)
    before = assignment['state'] or {}
    report['offers'] = rows(db, '''SELECT o.* FROM leonardo_assignment_parts a
        JOIN part_offers o ON o.part_id=a.part_id AND o.revision=a.revision
        WHERE a.job_id=? ORDER BY o.id''', (job,))
    # Preserve the operator's immutable input order rather than sorting offer IDs.
    offers_by_ref = {f"part:{o['part_id']}:{o['revision']}": o for o in report['offers']}
    report['offers'] = [offers_by_ref[p['ref']] for p in assignment['parts']]
    report['sources'] = rows(db, '''SELECT r.part_id,r.revision,r.queue_id,
        f.run_id,m.materialized_at FROM leonardo_assignment_parts a
        JOIN revision_sources r ON r.part_id=a.part_id AND r.revision=a.revision
        LEFT JOIN sherlock_fiches f ON f.queue_item_id=r.queue_id
        LEFT JOIN source_materializations m ON m.queue_id=r.queue_id
        WHERE a.job_id=? ORDER BY r.part_id,r.revision,r.position''', (job,))
    report['attempts'] = rows(db, '''SELECT id,status,activation_id,started_at,
        lease_until,finished_at,error FROM job_attempts WHERE job_id=? ORDER BY id''', (job,))
    report['dispatch'] = rows(db, '''SELECT operation_id,activation_id,job_id,attempt_id,
        confirmed_at FROM executor_activations WHERE job_id=?''', (job,))
    report['backlog'] = rows(db, '''SELECT role,status,count(*) AS count,
        min(created_at) AS oldest_created_at FROM jobs
        WHERE status IN ('ready','running','blocked') GROUP BY role,status''')
    states = rows(db, '''SELECT version,previous_version,attempt_id,content,tokens,
        created_at FROM leonardo_states WHERE job_id=?''', (job,))
    report['state'] = None
    if states:
        meta = states[0]
        content = meta.pop('content')
        report['state'] = json.loads(content)
        report['state_bytes'] = len(content.encode('utf-8'))
        report['state_metadata'] = meta
        delta = {}
        for field in ('hypotheses', 'claims', 'uncertainties', 'open_questions'):
            old = {v['id']: v for v in before.get(field, [])}
            new = {v['id']: v for v in report['state'][field]}
            delta[field] = dict(added=sorted(new.keys() - old.keys()),
                                removed=sorted(old.keys() - new.keys()),
                                changed=sorted(k for k in old.keys() & new.keys() if old[k] != new[k]))
        delta['processed_refs'] = dict(added=sorted(set(report['state']['processed_refs']) - set(before.get('processed_refs', []))))
        report['delta'] = delta
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('offers')
    sub.add_parser('dossiers')
    create = sub.add_parser('create-dossier')
    create.add_argument('--dossier', required=True)
    create.add_argument('--topic', required=True, type=int, choices=(1, 2, 3))
    enqueue = sub.add_parser('enqueue')
    enqueue.add_argument('--dossier', required=True)
    enqueue.add_argument('--base-version', required=True, type=int)
    enqueue.add_argument('--operation-id', required=True)
    enqueue.add_argument('--offer', required=True, action='append', type=int)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('--job', required=True, type=int)
    inspect.add_argument('--compact', action='store_true', help='Only local context usage per attempt')
    args = parser.parse_args(argv)
    # mode=rw prevents a typo from silently creating a fresh database.
    with closing(sqlite3.connect(args.db.resolve().as_uri() + '?mode=rw', uri=True)) as db:
        if args.command == 'offers':
            result = rows(db, '''SELECT o.*,p.topic,p.is_open FROM part_offers o
                JOIN parts p ON p.id=o.part_id ORDER BY o.id''')
        elif args.command == 'dossiers':
            result = rows(db, '''SELECT d.*,COALESCE(max(s.version),0) AS base_version
                FROM leonardo_dossiers d LEFT JOIN leonardo_states s ON s.dossier_id=d.id
                GROUP BY d.id ORDER BY d.id''')
        elif args.command == 'create-dossier':
            result = dict(dossier_id=LeonardoStore(db).create_dossier(args.dossier, args.topic))
        elif args.command == 'enqueue':
            result = dict(job_id=enqueue_offers(db, args.operation_id, args.dossier,
                                              args.base_version, args.offer))
        else:
            result = inspect_job(db, args.job, compact=args.compact)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
