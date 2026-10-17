"""Immutable mission input and a ready-only adapter for the generic executor."""
import hashlib
import json
from pathlib import Path

from ariadne_tokens import measure
from jobs import _text, _stamp
import role_contracts

ROOT = Path(__file__).resolve().parent
MISSION_CONTRACT = 'leonardo-output-v3:'


def digest(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def encoded_result(value):
    from leonardo import canonical
    if not isinstance(value, dict) or set(value) != {'summary', 'limitations'}:
        raise ValueError('Invalid Kuifje result')
    for text in value.values():
        _text(text, 8192)
    content = canonical(value)
    return content, measure(content)


def prepare_missions(db, args):
    """Bounded IO/token audit before finish's write lock; no effects here.

    Replay uses stored artifacts and does not reopen deployment contracts.
    Revalidation of binding, corpus and equality occurs under the finish lock.
    """
    from leonardo import canonical, queue_ref
    proposals = args.get('kuifje_missions', [])
    if not isinstance(proposals, list) or len(proposals) > 4:
        raise ValueError('Expected at most four mission proposals')
    if 'kuifje_missions' in args:
        row = db.execute('SELECT snapshot FROM leonardo_assignments WHERE job_id=?', (args['job_id'],)).fetchone()
        if row is None or args['status'] != 'succeeded' or 'leonardo_state' not in args:
            raise ValueError('Missions require successful Leonardo state output')
        data = json.loads(row[0])
        if not data['output_contract'].startswith(MISSION_CONTRACT):
            raise ValueError('Frozen contract does not permit missions')
    if not proposals:
        return []
    dossier, topic = db.execute('''SELECT a.dossier_id,d.topic FROM leonardo_assignments a
        JOIN leonardo_dossiers d ON d.id=a.dossier_id WHERE a.job_id=?''', (args['job_id'],)).fetchone()
    prepared = []
    contracts = None
    for ordinal, proposal in enumerate(proposals, 1):
        if not isinstance(proposal, dict) or set(proposal) != {'question', 'rationale', 'scope', 'refs'}:
            raise ValueError('Invalid mission proposal')
        for key in ('question', 'rationale', 'scope'):
            _text(proposal[key], 8192)
        refs = proposal['refs']
        if (not isinstance(refs, list) or not 1 <= len(refs) <= 256
                or any(not isinstance(r, str) or len(r) > 128 for r in refs)
                or len(set(refs)) != len(refs)
                or any(not (r.startswith('part:') or queue_ref(r)) for r in refs)):
            raise ValueError('Invalid mission provenance')
        mission_id = 'kuifje:%s:%s' % (args['job_id'], ordinal)
        mission = dict(proposal, schema_version=1, mission_id=mission_id, dossier_id=dossier,
                       producer_job_id=args['job_id'], state_version=data['base_version'] + 1,
                       topic=topic)
        content = canonical(mission)
        metrics = measure(content)
        if metrics['bytes'] > 32768 or metrics['tokens'] > 4000:
            raise ValueError('Mission input budget exceeded')
        prior = db.execute('''SELECT a.snapshot,a.sha256,a.bytes,a.tokens,a.tokenizer
            FROM kuifje_assignments a WHERE a.mission_id=?''', (mission_id,)).fetchone()
        if prior:
            snapshot, sha, size, tokens, tokenizer = prior
            audit = dict(bytes=size, tokens=tokens, tokenizer=tokenizer)
            output_ref = None  # Existing job is checked and reused under the lock.
        else:
            if contracts is None:
                contracts = [role_contracts.load_contract(ROOT / 'roles' / name)
                             for name in ('kuifje.md', 'kuifje-output.md')]
            (_, role), (output_ref, output) = contracts
            snapshot = canonical(dict(schema_version=1, mission=mission,
                                      role_contract=role, output_contract=output,
                                      tokenizer=metrics['tokenizer']))
            audit = measure(snapshot)
            if audit['bytes'] > 262144 or audit['tokens'] > 32768:
                raise ValueError('Kuifje assignment input budget exceeded')
            sha = digest(snapshot)
        prepared.append(dict(mission=mission, content=content, metrics=metrics,
                             snapshot=snapshot, sha=sha, audit=audit, output_ref=output_ref))
    return prepared


def commit_missions(control, args, prepared, state_created):
    """Same savepoint as successful state + terminal receipt, after fencing."""
    db = control.db
    existing = db.execute('SELECT content FROM kuifje_missions WHERE producer_job_id=? ORDER BY ordinal',
                          (args['job_id'],)).fetchall()
    if existing:
        if [r[0] for r in existing] != [p['content'] for p in prepared]:
            raise ValueError('Conflicting confirmed missions')
        return
    if not prepared:
        return
    if not state_created:
        raise ValueError('Cannot append missions to an already confirmed state')
    snapshot, = db.execute('SELECT snapshot FROM leonardo_assignments WHERE job_id=?', (args['job_id'],)).fetchone()
    data = json.loads(snapshot)
    # commit_state already validated the exact union of prior and current input.
    corpus = set(data['state']['processed_refs']) if data['state'] else set()
    corpus.update(part['ref'] for part in data['parts'])
    allowed = set(corpus)
    for ref in corpus:
        _, part, revision = ref.split(':')
        allowed.update('queue:%s' % q for (q,) in db.execute('''SELECT r.queue_id
            FROM revision_sources r JOIN source_archive a ON a.queue_id=r.queue_id
            WHERE r.part_id=? AND r.revision=?''', (int(part), int(revision))))
    state = db.execute('SELECT dossier_id,version FROM leonardo_states WHERE job_id=? AND attempt_id=?',
                       (args['job_id'], args['attempt_id'])).fetchone()
    if state is None:
        raise ValueError('Mission requires committed matching Leonardo output')
    for ordinal, p in enumerate(prepared, 1):
        m, metrics, audit = p['mission'], p['metrics'], p['audit']
        if (state != (m['dossier_id'], m['state_version'])
                or not set(m['refs']) <= allowed):
            raise ValueError('Mission references outside processed corpus')
        db.execute('INSERT INTO kuifje_missions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (m['mission_id'], args['job_id'], *state, ordinal, p['content'], digest(p['content']),
                    metrics['bytes'], metrics['tokens'], metrics['tokenizer'], _stamp(control.atomic.transaction_now)))
        job = control.atomic.create('Kuifje', ['sha256:' + p['sha']], p['output_ref'])
        db.execute('INSERT INTO kuifje_assignments VALUES (?,?,?,?,?,?,?)',
                   (job, m['mission_id'], p['snapshot'], p['sha'], audit['bytes'], audit['tokens'], audit['tokenizer']))


def require_authority(db, mission_id, claim, now):
    """Fencing under caller's ingress write lock, including executor binding."""
    from job_control import JobControl
    if not isinstance(claim, dict):
        raise ValueError('Kuifje requires claim')
    JobControl._schema(claim, {'job_id', 'attempt_id', 'token'}, {'lease_until'})
    JobControl._claim_fields(claim)
    row = db.execute('''SELECT a.job_id,a.snapshot FROM kuifje_assignments a
        JOIN jobs j ON j.id=a.job_id JOIN job_attempts t ON t.job_id=j.id
        WHERE a.mission_id=? AND j.id=? AND t.id=? AND t.token=? AND j.role='Kuifje'
          AND j.status='running' AND t.status='running' AND t.lease_until>?
          AND t.id=(SELECT max(id) FROM job_attempts WHERE job_id=j.id)
          AND EXISTS(SELECT 1 FROM executor_activations e WHERE e.job_id=j.id AND e.attempt_id=t.id)''',
        (mission_id, claim['job_id'], claim['attempt_id'], claim['token'], now)).fetchone()
    if row is None:
        raise ValueError('Kuifje requires current mission authority')
    return row[0], json.loads(row[1])['mission']


def commit_result(control, args, encoded):
    db = control.db
    row = db.execute('SELECT mission_id FROM kuifje_assignments WHERE job_id=?', (args['job_id'],)).fetchone()
    if row is None:
        if encoded is not None:
            raise ValueError('Result supplied for non-Kuifje job')
        return
    if args['status'] != 'succeeded':
        if encoded is not None or args['output_refs']:
            raise ValueError('Non-successful Kuifje finish requires no output')
        return
    if encoded is None or args['output_refs'] != ['kuifje-result:' + row[0]]:
        raise ValueError('Kuifje success requires concrete mission result')
    content, audit = encoded
    values = (args['job_id'], args['attempt_id'], content, audit['bytes'], audit['tokens'], audit['tokenizer'])
    prior = db.execute('SELECT * FROM kuifje_results WHERE job_id=?', (args['job_id'],)).fetchone()
    if prior:
        if prior != values:
            raise ValueError('Conflicting confirmed Kuifje output')
        return
    db.execute('INSERT INTO kuifje_results VALUES (?,?,?,?,?,?)', values)


def inspect_mission(db, mission_id):
    row = db.execute('''SELECT m.content,m.tokens,m.bytes,m.tokenizer,a.job_id,j.status,
        a.tokens,a.bytes FROM kuifje_missions m JOIN kuifje_assignments a USING(mission_id)
        JOIN jobs j ON j.id=a.job_id WHERE m.mission_id=?''', (mission_id,)).fetchone()
    if row is None:
        raise ValueError('Unknown mission')
    mission = json.loads(row[0])
    attempt = db.execute('SELECT id FROM job_attempts WHERE job_id=? ORDER BY id DESC LIMIT 1',
                         (row[4],)).fetchone()
    return dict(mission, attempt_id=attempt[0] if attempt else None, tokens=row[1], bytes=row[2], tokenizer=row[3], job_id=row[4],
                status=row[5], assignment_tokens=row[6], assignment_bytes=row[7],
                fiche_count=db.execute('SELECT count(*) FROM kuifje_fiches WHERE job_id=?', (row[4],)).fetchone()[0])


class KuifjeProducer:
    role = 'Kuifje'

    def __init__(self, dispatcher):
        self.db = dispatcher.db

    def prepare(self):
        return None

    def produce(self, now, prepared):
        return None

    def ready(self, job_id):
        return self.db.execute('SELECT 1 FROM kuifje_assignments WHERE job_id=?', (job_id,)).fetchone() is not None

    def bind(self, job_id, claim, now):
        snapshot, sha, mission_id = self.db.execute('SELECT snapshot,sha256,mission_id FROM kuifje_assignments WHERE job_id=?', (job_id,)).fetchone()
        data = json.loads(snapshot)
        return dict(claim, role=self.role, input=data, input_refs=['sha256:' + sha],
                    role_contract=data['role_contract'], role_contract_ref='sha256:' + digest(data['role_contract']),
                    output_contract=data['output_contract'], output_contract_ref=self.db.execute('SELECT output_contract_ref FROM jobs WHERE id=?', (job_id,)).fetchone()[0],
                    result_ref='kuifje-result:' + mission_id)


def result_selection(values):
    """Explicit bounded immutable identities, not a latest-result selector."""
    from job_control import _identity
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 16:
        raise ValueError('Expected at most sixteen explicit Kuifje job/attempt pairs')
    for pair in values:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError('Expected [Kuifje job_id, attempt_id]')
        for identity in pair:
            _identity(identity)
    if len({pair[0] for pair in values}) != len(values):
        raise ValueError('Duplicate Kuifje job selection')
    return values


def selected_results(db, dossier_id, base_version, selections):
    """Freeze finished research as context, never as processed source evidence.

    Exact terminal job/attempt identities and append-only mission/result bytes
    cannot change between this unlocked read and Leonardo's enqueue CAS. The
    subsequent assignment measures and hashes the complete delivered context.
    """
    feedback = []
    for job, attempt in selections:
        row = db.execute('''SELECT m.content,m.sha256,m.state_version,t.status,t.error,
                r.content,r.bytes,r.tokens,r.tokenizer
            FROM kuifje_assignments k JOIN kuifje_missions m USING(mission_id)
            JOIN jobs j ON j.id=k.job_id JOIN job_attempts t ON t.job_id=j.id
            LEFT JOIN kuifje_results r ON r.job_id=j.id AND r.attempt_id=t.id
            WHERE j.id=? AND t.id=? AND m.dossier_id=? AND j.role='Kuifje'
              AND j.status=t.status AND t.status IN ('succeeded','failed')
              AND t.id=(SELECT max(id) FROM job_attempts WHERE job_id=j.id)''',
            (job, attempt, dossier_id)).fetchone()
        if row is None or row[2] > base_version:
            raise ValueError('Foreign, unfinished or superseded Kuifje result binding')
        mission, mission_sha, _, status, error, content, size, tokens, tokenizer = row
        if status == 'succeeded' and content is None:
            raise ValueError('Successful Kuifje outcome requires its immutable result')
        feedback.append(dict(
            ref='kuifje-outcome:%s:%s' % (job, attempt), job_id=job, attempt_id=attempt,
            mission=json.loads(mission), mission_sha256=mission_sha, status=status, error=error,
            result=json.loads(content) if content else None,
            result_ref='kuifje-result:' + json.loads(mission)['mission_id'] if content else None,
            result_sha256=digest(content) if content else None,
            result_audit=dict(bytes=size, tokens=tokens, tokenizer=tokenizer) if content else None,
        ))
    return feedback
