"""Local explicit experimental offer routing. No scheduler or public API."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from jobs import _id
from leonardo import LeonardoStore, canonical, item_refs
from ariadne_tokens import token_count


def enqueue_offers(db, operation_id, dossier_id, base_version, offer_ids, kuifje_results=None):
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
    return LeonardoStore(db).enqueue(operation_id, dossier_id, base_version, revisions,
                                     kuifje_results=kuifje_results)


def rows(db, sql, args=()):
    cursor = db.execute(sql, args)
    return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor]


def context_usage(db, job):
    """Local measurements per attempt; unknown provider usage never means zero."""
    assignment = db.execute('SELECT tokens,snapshot FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone()
    if assignment is None:
        raise ValueError('Unknown Leonardo assignment')
    snapshot = json.loads(assignment[1])
    # Measure exact offered text, not the enclosing JSON, contracts or state.
    # 'New' means offered in this assignment, not semantic novelty/deduplication.
    new_parts = [dict(ref=part['ref'], tokens=token_count(part['content']),
                      bytes=len(part['content'].encode('utf-8')))
                 for part in snapshot['parts']]
    previous_state_tokens = (token_count(canonical(snapshot['state']))
                             if snapshot['state'] is not None else 0)
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
    state_row = db.execute('SELECT content FROM leonardo_states WHERE job_id=?', (job,)).fetchone()
    provenance = None
    if state_row:
        refs = set(item_refs(json.loads(state_row[0])))
        provenance = dict(part_ref_count=sum(r.startswith('part:') for r in refs),
                          queue_ref_count=sum(r.startswith('queue:') for r in refs))
    research = snapshot.get('research_results', [])
    return dict(research_result_count=len(research),
                selected_kuifje_job_count=len({r['job_id'] for r in research}),
                research_result_refs=[r['ref'] for r in research],
                research_result_tokens=sum(token_count(canonical(r)) for r in research),
                research_result_bytes=sum(len(canonical(r).encode('utf-8')) for r in research),
                tokenizer='cl100k_base', state_provenance=provenance, new_part_count=len(new_parts),
                new_part_tokens=sum(part['tokens'] for part in new_parts),
                new_part_bytes=sum(part['bytes'] for part in new_parts),
                new_parts=new_parts, previous_state_tokens=previous_state_tokens,
                start_input_tokens=assignment[0],
                start_input_bytes=len(assignment[1].encode('utf-8')), attempts=attempts)


def inspect_job(db, job, compact=False):
    if db.in_transaction:
        raise ValueError('Inspection requires an idle connection')
    db.execute('BEGIN')  # One consistent read snapshot, without a writer lock.
    try:
        if compact:
            result = rows(db, '''SELECT a.job_id,a.dossier_id,a.base_version,j.status FROM leonardo_assignments a
                JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?''', (job,))
            if not result:
                raise ValueError('Unknown Leonardo assignment')
            return dict(result[0], mode=json.loads(db.execute('SELECT snapshot FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone()[0]).get('mode', 'new_material'),
                        mission_count=db.execute('SELECT count(*) FROM kuifje_missions WHERE producer_job_id=?', (job,)).fetchone()[0],
                        context_usage=context_usage(db, job))
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
    report['mission_count'] = db.execute('SELECT count(*) FROM kuifje_missions WHERE producer_job_id=?', (job,)).fetchone()[0]
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


def result_pair(value):
    import re
    if re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', value) is None:
        raise argparse.ArgumentTypeError('Expected JOB:ATTEMPT')
    return list(map(int, value.split(':')))


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
    reevaluate = sub.add_parser('reevaluate')
    reevaluate.add_argument('--dossier', required=True)
    reevaluate.add_argument('--base-version', required=True, type=int)
    reevaluate.add_argument('--operation-id', required=True)
    mission = sub.add_parser('inspect-mission')
    mission.add_argument('--mission', required=True)
    for command in (enqueue, reevaluate):
        command.add_argument('--kuifje-result', action='append', type=result_pair,
                             help='Exact completed Kuifje JOB:ATTEMPT, repeatable (max 16)')
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
        elif args.command == 'reevaluate':
            result = dict(job_id=LeonardoStore(db).reevaluate(args.operation_id, args.dossier, args.base_version,
                                                                    kuifje_results=args.kuifje_result))
        elif args.command == 'inspect-mission':
            from kuifje import inspect_mission
            result = inspect_mission(db, args.mission)
        elif args.command == 'enqueue':
            result = dict(job_id=enqueue_offers(db, args.operation_id, args.dossier,
                                              args.base_version, args.offer, args.kuifje_result))
        else:
            result = inspect_job(db, args.job, compact=args.compact)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
