"""Persistente ingressqueue met caller-beheerde consumententransacties."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from database import migrate


class FicheRunConflict(ValueError):
    """Publication cannot be attributed to this run/topic/state."""


class IngressQueue:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            migrate(db)

    def pending_for_day(self, db, day):
        """Read one caller-owned snapshot; reject unassignable pending records.

        All pending JSON and dates are parsed strictly. Dates through the local
        cutoff are eligible; future records remain pending. The consumer also
        validates the complete schema of future records.
        """
        from datetime import date
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Dubbele JSON-sleutel')
                result[key] = value
            return result
        def invalid_constant(value):
            raise ValueError('Ongeldige JSON-constante')
        result = []
        for identity, raw in db.execute(
                "SELECT id,payload FROM ingress_queue WHERE status='pending' ORDER BY id").fetchall():
            try:
                payload = json.loads(raw, object_pairs_hook=unique,
                                     parse_constant=invalid_constant)
                value = payload.get('date') if isinstance(payload, dict) else None
                if not isinstance(value, str) or len(value) != 10:
                    raise ValueError('Ongeldige payloaddatum')
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value:
                    raise ValueError('Ongeldige payloaddatum')
            except (ValueError, TypeError) as error:
                raise ValueError(f'Ongeldig queue-item queue:{identity}') from error
            from daily import queue_fiche
            queue_fiche(identity, payload, parsed)
            if parsed <= day:
                result.append((identity, payload))
        return result

    def mark_processed(self, db, identities):
        """Never commit here: provenance and statuses belong to one transaction."""
        if not db.in_transaction:
            raise ValueError('Consument vereist een actieve SQLite-transactie')
        for identity in identities:
            cursor = db.execute("UPDATE ingress_queue SET status='processed' "
                                "WHERE id=? AND status='pending'", (identity,))
            if cursor.rowcount != 1:
                raise ValueError(f'Queue-item niet pending: queue:{identity}')

    def add(self, payload, run_id=None, claim=None, mission_id=None, fiche_id=None):
        if not isinstance(payload, dict):
            raise ValueError('Payload moet een JSON-object zijn')
        if mission_id is not None:
            if run_id is not None:
                raise FicheRunConflict('Only one producer binding is allowed')
            from jobs import _text
            _text(mission_id, 128)
            _text(fiche_id, 128)
        elif fiche_id is not None:
            raise FicheRunConflict('fiche_id requires mission_id')
        if claim is not None and run_id is None and mission_id is None:
            raise FicheRunConflict('Claim requires run_id')
        if run_id is not None:
            if type(run_id) is not int or not 0 < run_id <= 9007199254740991:
                raise ValueError('run_id moet een positieve safe integer zijn')
            from datetime import date
            from daily import queue_fiche
            day = date.fromisoformat(payload.get('date', ''))
            queue_fiche(0, payload, day)
        if mission_id is not None:
            from datetime import date
            from daily import queue_fiche
            queue_fiche(0, payload, date.fromisoformat(payload.get('date', '')))
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            received_at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            if (run_id is None and mission_id is None
                    and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sherlock_assignments'").fetchone()
                    and db.execute('SELECT 1 FROM sherlock_assignments UNION ALL SELECT 1 FROM kuifje_assignments').fetchone()):
                raise FicheRunConflict('Job-backed ingress requires run and claim')
            if run_id is not None:
                from sherlock_executor import require_run_authority
                try:
                    require_run_authority(db, run_id, claim)
                except ValueError as error:
                    raise FicheRunConflict(str(error)) from error
                run = db.execute('SELECT topic,status FROM sherlock_runs WHERE id=?', (run_id,)).fetchone()
                if run is None or run != (payload['topic'], 'running'):
                    raise FicheRunConflict('Fiche vereist een running run met hetzelfde topic')
            if mission_id is not None:
                from kuifje import require_authority, digest
                from leonardo import canonical
                try:
                    job, mission, job_date = require_authority(db, mission_id, claim, received_at)
                except ValueError as error:
                    raise FicheRunConflict(str(error)) from error
                if mission['topic'] != payload['topic']:
                    raise FicheRunConflict('Wrong mission topic')
                if job_date is not None and payload['date'] != job_date:
                    raise FicheRunConflict('Fiche date must match immutable job date')
                payload_sha = digest(canonical(payload))
                prior = db.execute('SELECT queue_item_id,payload_sha256 FROM kuifje_fiches WHERE job_id=? AND mission_id=? AND fiche_id=?',
                                   (job, mission_id, fiche_id)).fetchone()
                if prior:
                    if prior[1] != payload_sha:
                        raise FicheRunConflict('Fiche identity reused with different payload')
                    return prior[0]
                if db.execute('SELECT count(*) FROM kuifje_fiches WHERE job_id=? AND mission_id=?', (job, mission_id)).fetchone()[0] >= 5:
                    raise FicheRunConflict('Mission fiche bound exceeded')
            cursor = db.execute(
                'INSERT INTO ingress_queue (received_at, payload) VALUES (?, ?)',
                (received_at, data))
            identity = cursor.lastrowid
            if run_id is not None:
                db.execute('INSERT INTO sherlock_fiches(queue_item_id,run_id) VALUES (?,?)',
                           (identity, run_id))
            if mission_id is not None:
                db.execute('INSERT INTO kuifje_fiches VALUES (?,?,?,?,?,?)',
                           (identity, job, claim['attempt_id'], mission_id, fiche_id, payload_sha))
            return identity

    def pending_count(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return db.execute("SELECT count(*) FROM ingress_queue WHERE status = 'pending'").fetchone()[0]
