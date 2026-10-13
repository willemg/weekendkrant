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

    def add(self, payload, run_id=None):
        if not isinstance(payload, dict):
            raise ValueError('Payload moet een JSON-object zijn')
        if run_id is not None:
            if type(run_id) is not int or not 0 < run_id <= 9007199254740991:
                raise ValueError('run_id moet een positieve safe integer zijn')
            from datetime import date
            from daily import queue_fiche
            day = date.fromisoformat(payload.get('date', ''))
            queue_fiche(0, payload, day)
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        received_at = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            if run_id is not None:
                run = db.execute('SELECT topic,status FROM sherlock_runs WHERE id=?', (run_id,)).fetchone()
                if run is None or run != (payload['topic'], 'running'):
                    raise FicheRunConflict('Fiche vereist een running run met hetzelfde topic')
            cursor = db.execute(
                'INSERT INTO ingress_queue (received_at, payload) VALUES (?, ?)',
                (received_at, data))
            identity = cursor.lastrowid
            if run_id is not None:
                db.execute('INSERT INTO sherlock_fiches(queue_item_id,run_id) VALUES (?,?)',
                           (identity, run_id))
            return identity

    def pending_count(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return db.execute("SELECT count(*) FROM ingress_queue WHERE status = 'pending'").fetchone()[0]
