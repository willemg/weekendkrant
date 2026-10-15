"""Single-scheduler Sherlock production and atomic activation/claim/run binding.

No network, model or scheduling calls. Empty activations are durable decisions.
Role/output contracts are immutable content-addressed snapshots in SQLite.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from job_control import JobControl, ControlConflict
from jobs import _stamp, _text

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


class SherlockExecutor:
    def __init__(self, db, clock=None):
        self.control = JobControl(db, clock)
        self.store = self.control.store
        self.db = db

    def start(self, args):
        """One stable platform occurrence ID, one atomic durable decision.

        Identity is supplied by the single scheduler adapter, never generated
        in the bridge. Changed operation identity for a used activation conflicts.
        Replayed receipts do not grant fresh execution authority.
        """
        JobControl._schema(args, {'operation_id', 'activation_id'})
        for value in args.values():
            _text(value, 128)
        self.store._idle()
        # A durable receipt must survive later edits/removal of deployment files.
        known = self.db.execute('SELECT 1 FROM sherlock_activations WHERE operation_id=? OR activation_id=?',
            (args['operation_id'], args['activation_id'])).fetchone()
        # File IO happens before BEGIN IMMEDIATE, never during the transaction.
        contents = [] if known else [p.read_text(encoding='utf-8') for p in
                    (ROOT / 'docs/agents/sherlock.md', ROOT / 'docs/agents/sherlock-output.md')]
        for content in contents:
            _text(content, 65536)
        contracts = [('sha256:' + hashlib.sha256(c.encode('utf-8')).hexdigest(), c) for c in contents]
        conflict = None
        with self.store._write() as now:
            self.store._expire(now)
            prior = self.store._row('SELECT * FROM sherlock_activations WHERE operation_id=? OR activation_id=?',
                (args['operation_id'], args['activation_id']))
            if self.db.execute('SELECT 1 FROM job_operations WHERE operation_id=?',
                               (args['operation_id'],)).fetchone():
                conflict = 'Operation identity already used'
            elif prior:
                if (prior['operation_id'], prior['activation_id']) != (args['operation_id'], args['activation_id']):
                    conflict = 'Activation/operation identity reused'
                else:
                    result = json.loads(prior['response'])
                    if prior['attempt_id'] is not None:
                        result['token'] = self.db.execute('SELECT token FROM job_attempts WHERE id=?',
                            (prior['attempt_id'],)).fetchone()[0]
                        for field in ('role_contract', 'output_contract'):
                            result[field] = self.db.execute('SELECT content FROM sherlock_contracts WHERE ref=?',
                                (result[field+'_ref'],)).fetchone()[0]
            elif self.db.execute('SELECT 1 FROM job_attempts WHERE activation_id=?',
                                 (args['activation_id'],)).fetchone():
                conflict = 'Activation already used'
            else:
                result = self._produce(args, now, contracts)
                audit = dict(result)
                for field in ('token', 'role_contract', 'output_contract'):
                    audit.pop(field, None)
                self.db.execute('''INSERT INTO sherlock_activations
                    (operation_id,activation_id,job_id,attempt_id,response,confirmed_at)
                    VALUES (?,?,?,?,?,?)''', (args['operation_id'], args['activation_id'],
                    result.get('job_id'), result.get('attempt_id'),
                    json.dumps(audit, ensure_ascii=False, separators=(',', ':')), _stamp(now)))
        if conflict:
            raise ControlConflict(conflict)
        return result

    def _produce(self, args, now, contracts):
        # Conservative serial lane, including quarantined work and legacy runs.
        if (self.db.execute("SELECT 1 FROM jobs WHERE role='Sherlock' AND status IN ('running','blocked')").fetchone()
                or self.db.execute("SELECT 1 FROM sherlock_runs WHERE status='running' AND id NOT IN (SELECT run_id FROM sherlock_job_runs)").fetchone()):
            return {'claim': None}
        self.control.atomic.transaction_now = now
        atomic = self.control.atomic
        ready = self.db.execute('''SELECT j.id FROM jobs j JOIN sherlock_assignments s ON s.job_id=j.id
            WHERE j.status='ready' ORDER BY j.id LIMIT 1''').fetchone()
        if ready:
            job_id = ready[0]
        else:
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
        claim = atomic.claim(job_id, args['activation_id'])
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
