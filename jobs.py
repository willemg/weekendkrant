"""Generic durable job storage, deliberately disconnected from runtime/control plane.

Expiry quarantines work, never authorizes automatic reexecution. Reconciliation
asserts the old executor stopped and effects were checked, with durable evidence.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import uuid

from database import migrate


def _text(value, limit=512):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Expected bounded nonempty text')
    return value


def _refs(values):
    if not isinstance(values, list) or len(values) > 32:
        raise ValueError('Expected at most 32 artifact references')
    return json.dumps([_text(v) for v in values], ensure_ascii=False, separators=(',', ':'))


def _id(value):
    if type(value) is not int or value < 1:
        raise ValueError('Expected positive integer identity')


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


class JobStore:
    """Caller-owned idle connection; every mutation owns a short write transaction.

    Clock is authoritative backend UTC, sampled after acquiring the lock. No
    model/network/file work may run inside these transactions. Returned claim
    tokens are secrets, not worker-selected identities. An activation ID must
    identify one scheduled activation globally and must be reused on toolretry.
    """
    def __init__(self, db, clock=None):
        migrate(db)
        self.db = db
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _idle(self):
        if self.db.in_transaction:
            raise ValueError('JobStore requires an idle connection')

    @contextmanager
    def _write(self):
        self._idle()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            now = self.clock()
            if not isinstance(now, datetime) or now.utcoffset() is None:
                raise ValueError('Clock must return an aware datetime')
            yield now
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _row(self, sql, args):
        cursor = self.db.execute(sql, args)
        row = cursor.fetchone()
        return None if row is None else dict(zip([d[0] for d in cursor.description], row))

    def get(self, job_id):
        self._idle()
        _id(job_id)
        row = self._row('''SELECT j.*, r.evidence_ref AS recovery_ref FROM jobs j
            LEFT JOIN job_recoveries r ON r.attempt_id=(
                SELECT max(id) FROM job_attempts WHERE job_id=j.id) WHERE j.id=?''', (job_id,))
        if row is None:
            raise ValueError('Unknown job')
        for key in ('input_refs', 'output_refs'):
            row[key] = json.loads(row[key])
        return row

    def attempts(self, job_id):
        self._idle()
        _id(job_id)
        cursor = self.db.execute('SELECT * FROM job_attempts WHERE job_id=? ORDER BY id', (job_id,))
        keys = [d[0] for d in cursor.description]
        rows = [dict(zip(keys, r)) for r in cursor]
        for row in rows:
            row['output_refs'] = json.loads(row['output_refs'])
        return rows

    def create(self, role, input_refs, output_contract_ref, lease_seconds=600):
        role = _text(role, 128)
        refs = _refs(input_refs)
        contract = _text(output_contract_ref)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 86400:
            raise ValueError('Lease must be 1..86400 integer seconds')
        with self._write() as now:
            stamp = _stamp(now)
            cursor = self.db.execute('''INSERT INTO jobs
                (role,input_refs,output_contract_ref,lease_seconds,created_at,updated_at)
                VALUES (?,?,?,?,?,?)''', (role, refs, contract, lease_seconds, stamp, stamp))
            identity = cursor.lastrowid
        return identity

    def _expire(self, now):
        stamp = _stamp(now)
        ids = [r[0] for r in self.db.execute(
            "SELECT job_id FROM job_attempts WHERE status='running' AND lease_until<=?", (stamp,))]
        self.db.execute("""UPDATE job_attempts SET status='expired',finished_at=?
            WHERE status='running' AND lease_until<=?""", (stamp, stamp))
        for identity in ids:
            self.db.execute("UPDATE jobs SET status='blocked',updated_at=? WHERE id=?", (stamp, identity))
        return len(ids)

    def recover_expired(self):
        """Persist quarantine; safe to repeat after restart. No automatic retry."""
        with self._write() as now:
            count = self._expire(now)
        return count

    @staticmethod
    def _claim(row):
        return {
            'job_id': row['job_id'], 'attempt_id': row['id'],
            'token': row['token'], 'lease_until': row['lease_until']}

    def claim(self, job_id, activation_id):
        """Claim a specified ready job, not select/dispatch work. None if unavailable.

        Same activation+job returns the still-valid claim. Reusing an activation
        for another job or after its attempt ended is refused.
        """
        _id(job_id)
        activation_id = _text(activation_id, 128)
        rejected = False
        result = None
        with self._write() as now:
            self._expire(now)
            prior = self._row('SELECT * FROM job_attempts WHERE activation_id=?', (activation_id,))
            if prior is not None:
                if prior['job_id'] != job_id or prior['status'] != 'running':
                    rejected = True
                else:
                    result = self._claim(prior)
            else:
                job = self._row('SELECT * FROM jobs WHERE id=?', (job_id,))
                if job is None:
                    raise ValueError('Unknown job')
                if job['status'] == 'ready':
                    stamp = _stamp(now)
                    token = uuid.uuid4().hex
                    until = _stamp(now + timedelta(seconds=job['lease_seconds']))
                    cursor = self.db.execute('''INSERT INTO job_attempts
                        (job_id,activation_id,token,status,started_at,lease_until)
                        VALUES (?,?,?,'running',?,?)''', (job_id, activation_id, token, stamp, until))
                    self.db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?", (stamp, job_id))
                    result = dict(job_id=job_id, attempt_id=cursor.lastrowid, token=token, lease_until=until)
        if rejected:
            raise ValueError('Activation already used')
        return result

    def finish(self, claim, status, output_refs, error=None):
        """Accept only current unexpired claim; exact confirmed finish retries are no-ops.

        failed is terminal; uncertain quarantines effects. This does not publish
        artifacts: it records existing concrete references in the same commit.
        """
        if not isinstance(claim, dict):
            raise ValueError('Expected claim')
        for key in ('job_id', 'attempt_id'):
            _id(claim.get(key))
        _text(claim.get('token'))
        if status not in ('succeeded', 'failed', 'uncertain'):
            raise ValueError('Invalid finish status')
        refs = _refs(output_refs)
        if error is not None:
            _text(error, 2048)
        # Do not raise inside the transaction on expiry: quarantine must persist.
        rejected = False
        with self._write() as now:
            self._expire(now)
            row = self._row('SELECT * FROM job_attempts WHERE id=? AND job_id=? AND token=?',
                            (claim['attempt_id'], claim['job_id'], claim['token']))
            if row is None:
                raise ValueError('Unknown claim')
            if row['status'] != 'running':
                if row['status'] == status and row['output_refs'] == refs and row['error'] == error:
                    return
                rejected = True
            else:
                stamp = _stamp(now)
                self.db.execute('''UPDATE job_attempts SET status=?,output_refs=?,error=?,finished_at=?
                    WHERE id=?''', (status, refs, error, stamp, row['id']))
                self.db.execute('''UPDATE jobs SET status=?,output_refs=?,updated_at=?,finished_at=?
                    WHERE id=?''', ('blocked' if status == 'uncertain' else status, refs, stamp,
                                   None if status == 'uncertain' else stamp, row['job_id']))
        if rejected:
            raise ValueError('Expired, superseded or conflicting finish')

    def reconcile(self, job_id, attempt_id, decision, evidence_ref, output_refs=None):
        """Trusted recovery only: evidence must establish stopped executor + known effects.

        retry additionally asserts safe reexecution (no unhandled effects, or
        verified downstream idempotency). Unknown effects must remain blocked.
        An old attempt stays immutable; reconciliation has its own durable audit.
        """
        _id(job_id)
        _id(attempt_id)
        if decision not in ('retry', 'succeeded', 'failed'):
            raise ValueError('Invalid recovery decision')
        evidence = _text(evidence_ref)
        refs = _refs([] if output_refs is None else output_refs)
        if decision == 'retry' and refs != '[]':
            raise ValueError('Retry cannot accept output')
        with self._write() as now:
            job = self._row('SELECT * FROM jobs WHERE id=?', (job_id,))
            attempt = self._row('SELECT * FROM job_attempts WHERE id=? AND job_id=?', (attempt_id, job_id))
            latest = self.db.execute('SELECT max(id) FROM job_attempts WHERE job_id=?', (job_id,)).fetchone()[0]
            if (job is None or job['status'] != 'blocked' or attempt is None
                    or latest != attempt_id or attempt['status'] not in ('expired', 'uncertain')):
                raise ValueError('Not the current quarantined attempt')
            stamp = _stamp(now)
            self.db.execute('''INSERT INTO job_recoveries
                (attempt_id,decision,evidence_ref,output_refs,reconciled_at) VALUES (?,?,?,?,?)''',
                (attempt_id, decision, evidence, refs, stamp))
            self.db.execute('''UPDATE jobs SET status=?,output_refs=?,updated_at=?,finished_at=? WHERE id=?''',
                            ('ready' if decision == 'retry' else decision, refs, stamp,
                             None if decision == 'retry' else stamp, job_id))
