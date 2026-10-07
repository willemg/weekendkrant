"""Persistente ingressqueue met caller-beheerde consumententransacties."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


class IngressQueue:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS ingress_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )''')

    def pending_for_day(self, db, day):
        """Read one caller-owned snapshot; reject unassignable pending records.

        A valid other calendar date is ignored before fiche validation. Malformed
        JSON or an invalid/missing date cannot safely be assigned to another day.
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
            if parsed == day:
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

    def add(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('Payload moet een JSON-object zijn')
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        received_at = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.db_path)) as db, db:
            cursor = db.execute(
                'INSERT INTO ingress_queue (received_at, payload) VALUES (?, ?)',
                (received_at, data))
            return cursor.lastrowid

    def pending_count(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return db.execute("SELECT count(*) FROM ingress_queue WHERE status = 'pending'").fetchone()[0]
