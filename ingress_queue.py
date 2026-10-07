"""Persistente producerqueue; consumentenlogica volgt afzonderlijk."""
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
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status = 'pending')
            )''')

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
