"""Deterministic, atomic state-driven work selection. No scheduler or model calls."""
import json
from job_control import JobControl, ControlConflict
from jobs import _text, _stamp
from sherlock_executor import SherlockProducer


def admission(db, role=None):
    """Called under the start/claim write lock, after expiry quarantine."""
    paused, limit = db.execute('SELECT paused,max_running FROM dispatcher_policy WHERE id=1').fetchone()
    if paused or db.execute("SELECT 1 FROM jobs WHERE status='blocked'").fetchone():
        return False
    legacy = db.execute("SELECT count(*) FROM sherlock_runs WHERE status='running' AND id NOT IN (SELECT run_id FROM sherlock_job_runs)").fetchone()[0]
    running = db.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0]
    if role is not None and db.execute("SELECT 1 FROM jobs WHERE role=? AND status='running'", (role,)).fetchone():
        return False
    if role == 'Sherlock' and legacy:
        return False
    return running + legacy < limit


class Dispatcher:
    def __init__(self, db, clock=None, producer_types=None):
        self.control = JobControl(db, clock)
        self.store = self.control.store
        self.db = db
        self.producers = [p(self) for p in (producer_types if producer_types is not None else (SherlockProducer,))]
        self.by_role = {p.role: p for p in self.producers}
        if len(self.by_role) != len(self.producers):
            raise ValueError('Duplicate role adapter')

    def start(self, args):
        """One stable logical activation ID, one atomic durable decision.

        Identity is supplied by the single scheduler adapter, never generated
        in the bridge. Changed operation identity for a used activation conflicts.
        Replayed receipts do not grant fresh execution authority.
        """
        JobControl._schema(args, {'operation_id', 'activation_id'})
        for value in args.values():
            _text(value, 128)
        self.store._idle()
        # Each locked pass resolves replay/admission/ready work first. Only a
        # producer actually reached for new work may request unlocked file IO.
        prepared = {}
        while True:
            conflict = None
            with self.store._write() as now:
                self.store._expire(now)
                prior = self.store._row('SELECT * FROM executor_activations WHERE operation_id=? OR activation_id=?',
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
                elif self.db.execute('SELECT 1 FROM job_attempts WHERE activation_id=?',
                                     (args['activation_id'],)).fetchone():
                    conflict = 'Activation already used'
                else:
                    result = self._dispatch(args, now, prepared)
                    if isinstance(result, dict):
                        audit = dict(result)
                        audit.pop('token', None)
                        self.db.execute('''INSERT INTO executor_activations
                            (operation_id,activation_id,job_id,attempt_id,response,confirmed_at)
                            VALUES (?,?,?,?,?,?)''', (args['operation_id'], args['activation_id'],
                            result.get('job_id'), result.get('attempt_id'),
                            json.dumps(audit, ensure_ascii=False, separators=(',', ':')), _stamp(now)))
            if conflict:
                raise ControlConflict(conflict)
            if isinstance(result, dict):
                return result
            # No transaction is open here. On the next pass, expiry, receipts,
            # admission and ready-first selection are all evaluated again.
            prepared[result.role] = result.prepare()

    def _dispatch(self, args, now, prepared):
        """Locked decision: response, or next producer needing unlocked preparation."""
        if not admission(self.db):
            return {'claim': None}
        self.control.atomic.transaction_now = now
        # Persistent ready work first, FIFO by stable ID, supported adapters only.
        selected = None
        for job_id, role in self.db.execute("SELECT id,role FROM jobs WHERE status='ready' ORDER BY id"):
            adapter = self.by_role.get(role)
            if adapter and admission(self.db, role) and adapter.ready(job_id):
                selected = (job_id, adapter)
                break
        if selected is None:
            # Producer registration order is explicit policy, never role rotation.
            for adapter in self.producers:
                if not admission(self.db, adapter.role):
                    continue
                if adapter.role not in prepared:
                    return adapter
                job_id = adapter.produce(now, prepared[adapter.role])
                if job_id is not None:
                    selected = (job_id, adapter)
                    break
        if selected is None:
            return {'claim': None}
        job_id, adapter = selected
        executable = self.db.execute("SELECT 1 FROM jobs WHERE id=? AND role=? AND status='ready'",
                                     (job_id, adapter.role)).fetchone()
        if not executable or not adapter.ready(job_id):
            raise ValueError('Producer returned non-executable work')
        claim = self.control.atomic.claim(job_id, args['activation_id'])
        return adapter.bind(job_id, claim, now)
