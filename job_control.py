"""Explicit-job control protocol; no selection, scheduling or external effects."""
from contextlib import contextmanager
import hashlib
import json

from jobs import JobStore, _id, _text, _refs, _stamp


def _identity(value):
    _id(value)
    if value > 9007199254740991:
        raise ValueError('Identity exceeds transport integer range')


class ControlConflict(ValueError):
    """Identity reuse or unavailable execution authority; do not change retry ID."""


class _AtomicStore(JobStore):
    """Reuse lifecycle primitives inside the control plane's owned transaction."""
    @contextmanager
    def _write(self):
        yield self.transaction_now


class JobControl:
    fields = {
        'claim': ({'operation_id', 'job_id', 'activation_id'}, set()),
        'finish': ({'operation_id', 'job_id', 'attempt_id', 'token', 'status', 'output_refs'}, {'error'}),
        'abandon': ({'operation_id', 'job_id', 'attempt_id', 'token', 'error'}, set()),
        'reconcile': ({'operation_id', 'job_id', 'attempt_id', 'decision', 'evidence_ref'}, {'output_refs'}),
    }

    def __init__(self, db, clock=None):
        self.store = JobStore(db, clock)
        self.atomic = _AtomicStore(db, clock)
        self.db = db

    @staticmethod
    def _schema(args, required, optional=()):
        if (not isinstance(args, dict) or not required <= set(args)
                or set(args) - required - set(optional)):
            raise ValueError('Invalid request fields')

    @staticmethod
    def _claim_fields(args):
        _identity(args.get('job_id'))
        _identity(args.get('attempt_id'))
        _text(args.get('token'))

    def validate(self, args):
        """Current authority, not a cached receipt or permission for external effects."""
        self._schema(args, {'job_id', 'attempt_id', 'token'})
        self._claim_fields(args)
        with self.store._write() as now:
            self.store._expire(now)
            row = self.store._row('''SELECT a.* FROM job_attempts a
                WHERE a.id=? AND a.job_id=? AND a.token=?''',
                (args['attempt_id'], args['job_id'], args['token']))
        if row is None:
            raise ControlConflict('Unknown claim')
        return {'job_id': row['job_id'], 'attempt_id': row['id'],
                'claim_status': row['status'], 'valid': row['status'] == 'running',
                'lease_until': row['lease_until']}

    def execute(self, operation, args):
        if operation not in self.fields:
            raise ValueError('Unknown operation')
        self._schema(args, *self.fields[operation])
        _text(args['operation_id'], 128)
        _identity(args['job_id'])
        if operation == 'claim':
            _text(args['activation_id'], 128)
        elif operation in ('finish', 'abandon'):
            self._claim_fields(args)
            if operation == 'finish':
                if args['status'] not in ('succeeded', 'failed', 'uncertain'):
                    raise ValueError('Invalid finish status')
                _refs(args['output_refs'])
            if args.get('error') is not None:
                _text(args['error'], 2048)
            if operation == 'abandon':
                _text(args['error'], 2048)
        else:
            _identity(args['attempt_id'])
            if args['decision'] not in ('retry', 'succeeded', 'failed'):
                raise ValueError('Invalid recovery decision')
            _text(args['evidence_ref'])
            _refs(args.get('output_refs', []))
        canonical = json.dumps([operation, args], sort_keys=True, ensure_ascii=False,
                               separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        conflict = None
        with self.store._write() as now:
            self.store._expire(now)
            if self.db.execute('SELECT 1 FROM sherlock_activations WHERE operation_id=?', (args['operation_id'],)).fetchone():
                conflict = 'Operation identity already used by executor start'
            prior = self.store._row('SELECT * FROM job_operations WHERE operation_id=?',
                                    (args['operation_id'],))
            if conflict:
                pass
            elif prior:
                if prior['request_digest'] != digest or prior['operation'] != operation:
                    conflict = 'Operation identity reused with different request'
                else:
                    response = json.loads(prior['response'])
                    if operation == 'claim' and prior['attempt_id'] is not None:
                        # Token remains only in job_attempts, never receipt/audit metadata.
                        response['token'] = self.db.execute(
                            'SELECT token FROM job_attempts WHERE id=?',
                            (prior['attempt_id'],)).fetchone()[0]
            else:
                self.atomic.transaction_now = now
                self.db.execute('SAVEPOINT control_mutation')
                try:
                    response = self._apply(operation, args)
                    audit = dict(response)
                    audit.pop('token', None)
                    self.db.execute('''INSERT INTO job_operations
                        (operation_id,operation,request_digest,job_id,attempt_id,response,confirmed_at)
                        VALUES (?,?,?,?,?,?,?)''', (args['operation_id'], operation, digest,
                        args['job_id'], response.get('attempt_id'),
                        json.dumps(audit, ensure_ascii=False, separators=(',', ':')), _stamp(now)))
                except ValueError as error:
                    # Preserve quarantine, roll back any operation work on refusal.
                    self.db.execute('ROLLBACK TO control_mutation')
                    conflict = str(error)
                finally:
                    self.db.execute('RELEASE control_mutation')
        if conflict:
            raise ControlConflict(conflict)
        return response

    def _apply(self, operation, args):
        if operation == 'claim':
            if self.db.execute('SELECT 1 FROM sherlock_assignments WHERE job_id=?', (args['job_id'],)).fetchone():
                raise ControlConflict('Sherlock claims require atomic executor start')
            if self.db.execute('SELECT 1 FROM sherlock_activations WHERE activation_id=?', (args['activation_id'],)).fetchone():
                raise ControlConflict('Activation already used by executor start')
            claim = self.atomic.claim(args['job_id'], args['activation_id'])
            if claim is None:
                return {'claim': None}
            row = self.db.execute('SELECT role,input_refs,output_contract_ref FROM jobs WHERE id=?',
                                  (args['job_id'],)).fetchone()
            return dict(claim, role=row[0], input_refs=json.loads(row[1]), output_contract_ref=row[2])
        if operation in ('finish', 'abandon'):
            status = 'uncertain' if operation == 'abandon' else args['status']
            run = self.db.execute('SELECT run_id FROM sherlock_job_runs WHERE job_id=? AND attempt_id=?', (args['job_id'], args['attempt_id'])).fetchone()
            if run and operation == 'finish' and args['output_refs'] != ['sherlock-run:'+str(run[0])]:
                raise ControlConflict('Sherlock finish requires its concrete run result')
            self.atomic.finish(args, status, [] if operation == 'abandon' else args['output_refs'],
                               args.get('error'))
            if run:
                self.db.execute("UPDATE sherlock_runs SET status=?,finished_at=? WHERE id=? AND status='running'",
                    ('completed' if status == 'succeeded' else 'failed', _stamp(self.atomic.transaction_now), run[0]))
            return {'job_id': args['job_id'], 'attempt_id': args['attempt_id'],
                    'job_status': 'blocked' if status == 'uncertain' else status}
        self.atomic.reconcile(args['job_id'], args['attempt_id'], args['decision'],
                              args['evidence_ref'], args.get('output_refs'))
        self.db.execute("""UPDATE sherlock_runs SET status=?,finished_at=?
            WHERE status='running' AND id IN
            (SELECT run_id FROM sherlock_job_runs WHERE job_id=? AND attempt_id=?)""",
            ('completed' if args['decision'] == 'succeeded' else 'failed',
             _stamp(self.atomic.transaction_now), args['job_id'], args['attempt_id']))
        return {'job_id': args['job_id'], 'attempt_id': args['attempt_id'],
                'job_status': 'ready' if args['decision'] == 'retry' else args['decision']}
