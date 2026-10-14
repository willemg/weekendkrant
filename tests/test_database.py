"""Migration contract, with legacy DDL independent of the new migration files."""
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import database
import test_parts


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)

    def schema(self, db):
        return [(kind, name, database.sql_tokens(sql)) for kind, name, sql in db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]

    def legacy(self, version, runtime=True):
        self.db.executescript((Path(__file__).parent / 'fixtures/parts_v1.sql').read_text())
        if version == 2:
            self.db.executescript((Path(__file__).parent / 'fixtures/parts_v2_offers.sql').read_text())
        if runtime:
            self.db.executescript(test_parts.MigrationTests.LEGACY)
        with self.db:
            self.db.execute("INSERT INTO parts VALUES (1,'2026_W41',2,1,1,NULL)")
            self.db.execute("INSERT INTO source_archive VALUES (1,1,'2026-10-11',2,?, 'hash')", (b'original\r\n',))
            self.db.execute("INSERT INTO part_revisions VALUES (1,1,'path','hash',10,'cl100k_base',5000)")
            self.db.execute('INSERT INTO revision_sources VALUES (1,1,0,1)')
            self.db.execute('UPDATE parts SET active_revision=1')
            if version == 2:
                self.db.execute('INSERT INTO part_offers(part_id,revision) VALUES (1,1)')
            if runtime:
                self.db.execute("INSERT INTO days VALUES ('2026-10-11','2026_W41','success','commit','manifest',NULL)")
                self.db.execute("INSERT INTO attempts(day,status) VALUES ('2026-10-11','success')")
                self.db.execute("INSERT INTO threads VALUES ('thread','2026-10-11',2,1,'hash',10,'cl100k_base',5000)")
                self.db.execute("INSERT INTO sources VALUES ('2026-10-11','source','hash','thread',0)")
                self.db.execute("INSERT INTO ingress_queue(received_at,payload) VALUES ('now','{}')")
        self.db.execute(f'PRAGMA user_version={version}')

    def test_scratch_matches_full_legacy_schema_and_idempotence(self):
        self.legacy(2)
        expected = self.schema(self.db)
        with sqlite3.connect(':memory:') as fresh:
            database.migrate(fresh)
            self.assertEqual([row for row in self.schema(fresh)
                              if not row[1].startswith(('sherlock_', 'source_materializations', 'job'))], expected)
            self.assertEqual(fresh.execute('PRAGMA user_version').fetchone(), (database.SCHEMA_VERSION,))
            self.assertEqual(fresh.execute('PRAGMA foreign_keys').fetchone(), (1,))
            before = list(fresh.iterdump())
            database.migrate(fresh)
            self.assertEqual(list(fresh.iterdump()), before)
            self.assertEqual(len(fresh.execute('PRAGMA foreign_key_list(revision_sources)').fetchall()), 3)
            with self.assertRaises(sqlite3.IntegrityError):
                fresh.execute("INSERT INTO parts(week,topic,part,is_open) VALUES ('week',4,1,1)")

    def test_legacy_data_preserved(self):
        for version, runtime in ((1, True), (2, True), (2, False)):
            with self.subTest(version=version, runtime=runtime):
                self.db.close()
                self.db = sqlite3.connect(':memory:')
                self.addCleanup(self.db.close)
                self.legacy(version, runtime)
                tables = [row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                before = {t: self.db.execute('SELECT * FROM '+t).fetchall() for t in tables}
                database.migrate(self.db)
                for t, rows in before.items():
                    self.assertEqual(self.db.execute('SELECT * FROM '+t).fetchall(), rows)
                self.assertEqual(self.db.execute('PRAGMA user_version').fetchone(), (database.SCHEMA_VERSION,))
                self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
                with sqlite3.connect(':memory:') as fresh:
                    database.migrate(fresh)
                    self.assertEqual(self.schema(self.db), self.schema(fresh))

    def test_v2_with_only_some_runtime_tables(self):
        self.legacy(2, False)
        self.db.executescript(test_parts.MigrationTests.LEGACY.split(';')[1]+';')
        with self.db:
            self.db.execute("INSERT INTO days VALUES ('2026-10-11','2026_W41','success',NULL,NULL,NULL)")
        before = self.db.execute('SELECT * FROM days').fetchall()
        database.migrate(self.db)
        self.assertEqual(self.db.execute('SELECT * FROM days').fetchall(), before)
        with sqlite3.connect(':memory:') as fresh:
            database.migrate(fresh)
            self.assertEqual(self.schema(self.db), self.schema(fresh))

    def test_newer_refused(self):
        self.db.execute('PRAGMA user_version=99')
        before = list(self.db.iterdump())
        with self.assertRaises(ValueError):
            database.migrate(self.db)
        self.assertEqual(list(self.db.iterdump()), before)

    def test_partial_step_rolls_back(self):
        self.legacy(2, False)
        before = list(self.db.iterdump())
        original = database.statements
        with patch('database.statements', side_effect=lambda sql: list(original(sql))+['CREATE TABLE days(id);']):
            with self.assertRaises(sqlite3.OperationalError):
                database.migrate(self.db)
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone(), (2,))
        self.assertFalse(self.db.in_transaction)

    def test_incompatible_existing_runtime_table_refused(self):
        self.legacy(2, False)
        self.db.execute('CREATE TABLE days(day TEXT)')
        before = list(self.db.iterdump())
        with self.assertRaisesRegex(ValueError, 'days'):
            database.migrate(self.db)
        self.assertEqual(list(self.db.iterdump()), before)

    def test_active_transaction_not_committed(self):
        self.db.execute('CREATE TABLE unrelated(x)')
        self.db.execute('INSERT INTO unrelated VALUES (1)')
        with self.assertRaises(ValueError):
            database.migrate(self.db)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT * FROM unrelated').fetchall(), [])

    def test_concurrent_bootstrap_serializes_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'concurrent.sqlite3'
            ready = Barrier(2)
            def build():
                with sqlite3.connect(path) as db:
                    ready.wait(timeout=5)
                    database.migrate(db)
                    return db.execute('PRAGMA user_version').fetchone()[0]
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(build) for _ in range(2)]
                self.assertEqual([f.result(timeout=10) for f in futures], [database.SCHEMA_VERSION] * 2)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_cli_missing_path_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'nested'/'new.sqlite3'
            for _ in range(2):
                result = subprocess.run([__import__('sys').executable, 'database.py', '--db', str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (database.SCHEMA_VERSION,))

    @patch.object(database, 'SCHEMA_VERSION', 4)
    def test_v3_to_v4_preserves_full_existing_schema_and_data(self):
        self.legacy(2)
        self.db.execute('PRAGMA user_version=3')
        old_schema = self.schema(self.db)
        tables = [row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before = {t: self.db.execute('SELECT * FROM '+t).fetchall() for t in tables}
        database.migrate(self.db)
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone(), (4,))
        for table, rows in before.items():
            self.assertEqual(self.db.execute('SELECT * FROM '+table).fetchall(), rows)
        self.assertEqual([r for r in self.schema(self.db) if not r[1].startswith('sherlock_')], old_schema)
        self.assertEqual({r[1] for r in self.schema(self.db)} - {r[1] for r in old_schema},
                         {'sherlock_runs', 'sherlock_sources'})
        with sqlite3.connect(':memory:') as fresh:
            database.migrate(fresh)
            self.assertEqual(fresh.execute('PRAGMA user_version').fetchone(), (4,))
            self.assertEqual(self.schema(fresh), self.schema(self.db))
        snapshot = list(self.db.iterdump())
        statements = []
        self.db.set_trace_callback(statements.append)
        database.migrate(self.db)
        self.assertFalse(any(s.lstrip().upper().startswith(('CREATE', 'INSERT', 'UPDATE', 'BEGIN')) for s in statements))
        self.assertEqual(list(self.db.iterdump()), snapshot)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_failed_fourth_migration_rolls_back_schema_and_version(self):
        self.legacy(2)
        self.db.execute('PRAGMA user_version=3')
        before = list(self.db.iterdump())
        original = database.migration_sql
        def broken(version):
            return original(version) + '; CREATE TABLE sherlock_runs(conflict);'
        with patch('database.migration_sql', side_effect=broken):
            with self.assertRaises(sqlite3.OperationalError):
                database.migrate(self.db)
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone(), (3,))
        self.assertFalse(self.db.in_transaction)
