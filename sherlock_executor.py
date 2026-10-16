"""Sherlock work production, immutable assignments and claim/run binding.

No network, model or scheduling calls. Empty activations are durable decisions.
Role/output contracts are immutable content-addressed snapshots in SQLite.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from jobs import _stamp, _text

# Temporary development policy, not a schema or dispatcher invariant.
SHERLOCK_NEW_JOB_COOLDOWN = timedelta(hours=30)

ROOT = Path(__file__).resolve().parent


def require_run_authority(db, run_id, claim=None):
    """Called under the adapter's write lock immediately before effects.

    Legacy runs remain compatible. A job-backed run always requires the current
    attempt's token; preflight validation alone never authorizes a later write.
    This check rejects expiry without rolling back a quarantine transaction.
    """
    binding = db.execute('SELECT job_id,attempt_id FROM sherlock_job_runs WHERE run_id=?',
                         (run_id,)).fetchone()
    if binding is None:
        if claim is not None:
            raise ValueError('Claim supplied for a legacy run')
        return
    if (not isinstance(claim, dict) or set(claim) != {'job_id','attempt_id','token'}
            or type(claim['job_id']) is not int or type(claim['attempt_id']) is not int
            or (claim['job_id'], claim['attempt_id']) != binding
            or not isinstance(claim['token'], str)):
        raise ValueError('Job-backed run requires its claim')
    valid = db.execute('''SELECT 1 FROM job_attempts a JOIN jobs j ON j.id=a.job_id
        WHERE a.id=? AND a.job_id=? AND a.token=? AND a.status='running'
        AND j.status='running' AND a.lease_until>?''',
        (claim['attempt_id'], claim['job_id'], claim['token'],
         _stamp(datetime.now(timezone.utc)))).fetchone()
    if valid is None:
        raise ValueError('No current Sherlock execution authority')


class SherlockProducer:
    role = 'Sherlock'

    def __init__(self, dispatcher):
        self.db = dispatcher.db
        self.control = dispatcher.control

    def prepare(self):
        contents = [p.read_text(encoding='utf-8') for p in
                    (ROOT / 'docs/agents/sherlock.md', ROOT / 'docs/agents/sherlock-output.md')]
        for content in contents:
            _text(content, 65536)
        return [('sha256:' + hashlib.sha256(c.encode('utf-8')).hexdigest(), c) for c in contents]

    def ready(self, job_id):
        return self.db.execute('SELECT 1 FROM sherlock_assignments WHERE job_id=?', (job_id,)).fetchone() is not None

    def produce(self, now, contracts):
        atomic = self.control.atomic
        # Only new production is throttled. Explicit ready recovery above
        # retains its original job/topic and starts a new real run.
        latest = self.db.execute(
            'SELECT started_at FROM sherlock_runs ORDER BY julianday(started_at) DESC LIMIT 1').fetchone()
        if latest is not None:
            started = datetime.fromisoformat(latest[0])
            if started.utcoffset() is None:
                raise ValueError('Sherlock runstart must be timezone-aware')
            if now - started < SHERLOCK_NEW_JOB_COOLDOWN:
                return None
        previous = self.db.execute('SELECT topic FROM sherlock_runs ORDER BY id DESC LIMIT 1').fetchone()
        topic = 1 if previous is None else previous[0] % 3 + 1
        for ref, content in contracts:
            if not self.db.execute('SELECT 1 FROM sherlock_contracts WHERE ref=?', (ref,)).fetchone():
                self.db.execute('INSERT INTO sherlock_contracts VALUES (?,?)', (ref, content))
        date = now.astimezone(ZoneInfo('Europe/Brussels')).date().isoformat()
        context = json.dumps({'topic': topic, 'date': date}, sort_keys=True, separators=(',', ':'))
        input_ref = 'sha256:' + hashlib.sha256(context.encode('utf-8')).hexdigest()
        if not self.db.execute('SELECT 1 FROM sherlock_contracts WHERE ref=?', (input_ref,)).fetchone():
            self.db.execute('INSERT INTO sherlock_contracts VALUES (?,?)', (input_ref, context))
        job_id = atomic.create('Sherlock', [input_ref, contracts[0][0]], contracts[1][0])
        self.db.execute('INSERT INTO sherlock_assignments VALUES (?,?,?,?,?)',
            (job_id, topic, date, contracts[0][0], contracts[1][0]))
        return job_id

    def bind(self, job_id, claim, now):
        assignment = self.db.execute('SELECT topic,date,role_contract_ref,output_contract_ref FROM sherlock_assignments WHERE job_id=?', (job_id,)).fetchone()
        # Old expired runs are closed only after explicit recovery has made the job ready.
        self.db.execute("""UPDATE sherlock_runs SET status='failed',finished_at=?
            WHERE status='running' AND id IN (SELECT run_id FROM sherlock_job_runs WHERE job_id=?)""", (_stamp(now), job_id))
        run_id = self.db.execute('INSERT INTO sherlock_runs(topic,started_at) VALUES (?,?)',
                                 (assignment[0], _stamp(now))).lastrowid
        self.db.execute('INSERT INTO sherlock_job_runs VALUES (?,?,?)', (run_id, job_id, claim['attempt_id']))
        role = self.db.execute('SELECT content FROM sherlock_contracts WHERE ref=?', (assignment[2],)).fetchone()[0]
        output = self.db.execute('SELECT content FROM sherlock_contracts WHERE ref=?', (assignment[3],)).fetchone()[0]
        return dict(claim, role='Sherlock', run_id=run_id,
            input={'topic': assignment[0], 'date': assignment[1]},
            input_refs=json.loads(self.db.execute('SELECT input_refs FROM jobs WHERE id=?', (job_id,)).fetchone()[0]),
            role_contract_ref=assignment[2], role_contract=role,
            output_contract_ref=assignment[3], output_contract=output,
            result_ref='sherlock-run:'+str(run_id))


class SherlockExecutor:
    """Compatibility import for callers predating the generic dispatcher."""
    def __new__(cls, db, clock=None):
        from dispatcher import Dispatcher
        return Dispatcher(db, clock)
