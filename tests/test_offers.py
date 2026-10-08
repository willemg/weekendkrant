"""Offer invariants exercised against real daily output and SQLite."""
from pathlib import Path
import sqlite3
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import daily
from parts import PartStore, migrate, render
from test_parts import PartFixture

TABLES = ('parts', 'part_revisions', 'revision_sources', 'source_archive', 'part_offers')


class OfferTests(PartFixture):
    def prepare(self, revisions=1):
        for day in range(5, 5 + revisions):
            self.add('2026-10-%02d' % day)
            self.run_day(day)
        return self.rows('SELECT id FROM parts')[0][0]

    def offer(self, identity, revision):
        db = daily.database(self.db)
        try:
            return PartStore(db).offer(identity, revision)
        finally:
            db.close()

    def snapshot(self):
        return {t: self.rows('SELECT * FROM ' + t + ' ORDER BY 1,2') for t in TABLES}

    def test_open_offer_seals_exact_revision_and_next_daily_starts_next_part(self):
        identity = self.prepare(3)
        before = self.snapshot()
        files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.rglob('*.txt')}
        with patch.object(daily, 'write_thread', side_effect=AssertionError('no offer file writes')):
            offer = self.offer(identity, 3)
        self.assertEqual((offer.part_id, offer.revision), (identity, 3))
        self.assertTrue(offer.created_at)
        self.assertEqual(self.rows('SELECT id,part_id,revision,created_at FROM part_offers'),
                         [(offer.id, identity, 3, offer.created_at)])
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 0, 3)])
        for t in TABLES[1:-1]:
            self.assertEqual(self.snapshot()[t], before[t])
        self.add('2026-10-08', content='next part')
        self.run_day(8)
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 0, 3), ('2026_W41', 2, 2, 1, 1)])
        for p, (data, mtime) in files.items():
            self.assertEqual(p.read_bytes(), data)
            self.assertEqual(p.stat().st_mtime_ns, mtime)
        for t in TABLES[1:-1]:
            self.assertEqual(self.snapshot()[t][:len(before[t])], before[t])

    def test_overflow_closed_part_is_offerable(self):
        self.add(content='x' * 100)
        self.add(content='y' * 100)
        with patch.object(daily, 'token_count', side_effect=len), patch.object(daily, 'LIMIT', 5400):
            self.run_day(5)
        self.assertEqual(self.active()[0], ('2026_W41', 2, 1, 0, 1))
        before = self.rows('SELECT * FROM parts')
        self.assertEqual(self.offer(1, 1).revision, 1)
        self.assertEqual(self.rows('SELECT * FROM parts'), before)

    def test_storage_rejects_old_missing_and_unregistered_revisions(self):
        identity = self.prepare(3)
        db = daily.database(self.db)
        with db:
            empty = db.execute("INSERT INTO parts(week,topic,part,is_open) VALUES ('2026_W41',1,1,1)").lastrowid
        db.close()
        before = self.snapshot()
        for part, revision in ((identity, 1), (identity, 2), (identity, 4), (999, 1), (empty, 1)):
            with self.subTest(part=part, revision=revision), self.assertRaises(ValueError):
                self.offer(part, revision)
            self.assertEqual(self.snapshot(), before)

    def test_direct_sql_refuses_invalid_revision_even_without_foreign_keys(self):
        identity = self.prepare(3)
        before = self.snapshot()
        with sqlite3.connect(self.db) as db:
            for part, revision in ((identity, 1), (identity, 2), (identity, 4), (999, 1), (identity, None)):
                with self.subTest(part=part, revision=revision), self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO part_offers(part_id,revision) VALUES (?,?)', (part, revision))
        self.assertEqual(self.snapshot(), before)

    def test_identical_retry_returns_same_offer_and_other_revision_is_refused(self):
        identity = self.prepare(2)
        first = self.offer(identity, 2)
        before = self.snapshot()
        self.assertEqual(self.offer(identity, 2), first)
        with self.assertRaises(ValueError):
            self.offer(identity, 1)
        self.assertEqual(self.snapshot(), before)

    def test_sql_seals_and_forbids_duplicate_replacement_update_delete_or_reopen(self):
        identity = self.prepare()
        with sqlite3.connect(self.db) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('INSERT INTO part_offers(part_id,revision) VALUES (?,1)', (identity,))
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 0, 1)])
        before = self.snapshot()
        with sqlite3.connect(self.db) as db:
            db.execute('PRAGMA foreign_keys=ON')
            for sql in (
                'INSERT INTO part_offers(part_id,revision) VALUES (1,1)',
                'INSERT OR REPLACE INTO part_offers(part_id,revision) VALUES (1,1)',
                "INSERT OR REPLACE INTO part_offers(id,part_id,revision) VALUES (1,1,1)",
                "UPDATE part_offers SET created_at='changed'", 'DELETE FROM part_offers',
                'UPDATE parts SET is_open=1', 'UPDATE parts SET active_revision=2',
                "INSERT INTO part_revisions SELECT part_id,2,path || '.new',sha256,tokens,tokenizer,reserved_tokens FROM part_revisions",
                'INSERT INTO revision_sources VALUES (1,1,9,1)',
            ):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
        self.assertEqual(self.snapshot(), before)

    def test_offered_pointer_cannot_advance_to_preexisting_future_revision(self):
        identity = self.prepare()
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO part_revisions SELECT part_id,2,path || '.future',sha256,tokens,tokenizer,reserved_tokens FROM part_revisions")
        self.offer(identity, 1)
        with sqlite3.connect(self.db) as db, self.assertRaises(sqlite3.IntegrityError):
            db.execute('UPDATE parts SET active_revision=2')
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 0, 1)])

    def test_failure_during_sealing_rolls_back_all_audit_and_files(self):
        identity = self.prepare()
        before = self.snapshot()
        files = {p: p.read_bytes() for p in self.output.rglob('*.txt')}
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER fail_seal BEFORE UPDATE OF is_open ON parts BEGIN SELECT RAISE(ABORT,'seal failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'seal failure'):
            self.offer(identity, 1)
        self.assertEqual(self.snapshot(), before)
        for p, data in files.items():
            self.assertEqual(p.read_bytes(), data)
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER fail_seal')
        self.offer(identity, 1)

    def test_commit_failure_rolls_back_both_offer_and_seal(self):
        identity = self.prepare()
        before = self.snapshot()
        class FailCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError('commit failure')
        db = sqlite3.connect(self.db, factory=FailCommit)
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, 'commit failure'):
                PartStore(db).offer(identity, 1)
            self.assertFalse(db.in_transaction)
        finally:
            db.close()
        self.assertEqual(self.snapshot(), before)

    def test_offer_refuses_callers_transaction_without_committing_it(self):
        identity = self.prepare()
        db = daily.database(self.db)
        try:
            db.execute('BEGIN')
            with self.assertRaises(ValueError):
                PartStore(db).offer(identity, 1)
            self.assertTrue(db.in_transaction)
            self.assertEqual(db.execute('SELECT is_open FROM parts').fetchone(), (1,))
        finally:
            db.close()


class OfferMigrationTests(unittest.TestCase):
    def test_zero_to_two_and_two_noop(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        migrate(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (2,))
        schema = db.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall()
        statements = []
        db.set_trace_callback(statements.append)
        migrate(db)
        self.assertEqual(db.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall(), schema)
        self.assertFalse(any(s.upper().startswith(('CREATE', 'BEGIN', 'COMMIT')) for s in statements))

    def v1(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('PRAGMA foreign_keys=ON')
        fixture = Path(__file__).parent / 'fixtures/parts_v1.sql'
        db.executescript(fixture.read_text())
        with db:
            db.execute("INSERT INTO parts VALUES (1,'2026_W41',2,1,1,NULL)")
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            sources = []
            for revision, content in ((1, 'é\r\n漢字'), (2, 'tweede bron')):
                data = content.encode()
                digest = hashlib.sha256(data).hexdigest()
                identity = 41 + revision
                source = daily.Fiche('queue:%s' % identity, 2, data, digest, '2026-10-05')
                sources.append(source)
                db.execute("INSERT INTO source_archive VALUES (?,1,'2026-10-05',2,?,?)",
                           (identity, data, digest))
                text = render(sources, '2026_W41', 2, 1, revision, 5000)
                path = Path(tmp.name) / ('rev_%04d.txt' % revision)
                path.write_bytes(text.encode())
                db.execute('INSERT INTO part_revisions VALUES (1,?,?,?,?,?,5000)',
                           (revision, str(path), hashlib.sha256(text.encode()).hexdigest(),
                            daily.token_count(text), 'cl100k_base'))
                for position, fiche in enumerate(sources):
                    db.execute('INSERT INTO revision_sources VALUES (1,?,?,?)',
                               (revision, position, int(fiche.path[6:])))
                db.execute('UPDATE parts SET active_revision=?', (revision,))
        return db

    def test_real_v1_migration_preserves_rows_schema_bytes_and_is_idempotent(self):
        db = self.v1()
        before = {t: db.execute('SELECT * FROM ' + t).fetchall() for t in TABLES[:-1]}
        schema = db.execute('SELECT * FROM sqlite_master ORDER BY name').fetchall()
        files = {Path(row[2]): Path(row[2]).read_bytes() for row in before['part_revisions']}
        statements = []
        db.set_trace_callback(statements.append)
        migrate(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (2,))
        for t, rows in before.items():
            self.assertEqual(db.execute('SELECT * FROM ' + t).fetchall(), rows)
        for row in schema:
            self.assertIn(row, db.execute('SELECT * FROM sqlite_master').fetchall())
        self.assertFalse(any(s.lstrip().upper().startswith(('UPDATE', 'DELETE', 'DROP', 'VACUUM')) for s in statements))
        offer = PartStore(db).offer(1, 2)
        after = list(db.iterdump())
        migrate(db)
        self.assertEqual(list(db.iterdump()), after)
        self.assertEqual(PartStore(db).offer(1, 2), offer)
        for path, data in files.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_migration_failure_is_transactional(self):
        db = self.v1()
        db.execute("CREATE TRIGGER offered_active_revision BEFORE UPDATE ON parts BEGIN SELECT 1; END")
        before = list(db.iterdump())
        with self.assertRaises(sqlite3.OperationalError):
            migrate(db)
        self.assertEqual(list(db.iterdump()), before)
        self.assertFalse(db.in_transaction)

    def test_newer_schema_refused_without_changes(self):
        db = self.v1()
        db.execute('PRAGMA user_version=3')
        before = list(db.iterdump())
        with self.assertRaises(ValueError):
            migrate(db)
        self.assertEqual(list(db.iterdump()), before)
