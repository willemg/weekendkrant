"""Phase-6 policy: real provenance, exact boundary, pending/running fences."""
from datetime import datetime, timedelta, timezone
import sqlite3
from unittest.mock import patch

import daily
from parts import PartStore, OFFER_QUIET_PERIOD
from test_parts import PartFixture

STAMP = datetime(2026, 10, 16, 7, 15, tzinfo=timezone.utc)


class OfferPolicyTests(PartFixture):
    def prepare(self, topic=2):
        self.add(topic=topic)
        with patch.object(daily, 'materialization_timestamp', return_value=STAMP.isoformat()), \
                patch('parts.datetime', wraps=datetime) as clock:
            clock.now.return_value = STAMP
            self.run_day()
        return self.rows('SELECT id FROM parts ORDER BY id DESC')[0][0]

    def offer_at(self, now):
        db = daily.database(self.db)
        try:
            return PartStore(db).offer_ready(now)
        finally:
            db.close()

    def test_boundary_exact_provenance_and_idempotence(self):
        identity = self.prepare()
        before = {t: self.rows('SELECT * FROM ' + t) for t in
                  ('part_revisions', 'revision_sources', 'source_archive', 'source_materializations')}
        files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.rglob('*.txt')}
        boundary = STAMP + OFFER_QUIET_PERIOD
        self.assertEqual(self.offer_at(boundary - timedelta(microseconds=1)), ())
        offered = self.offer_at(boundary)
        self.assertEqual([(o.part_id, o.revision) for o in offered], [(identity, 1)])
        self.assertEqual(self.offer_at(boundary + timedelta(days=1)), ())
        self.assertEqual(self.rows('SELECT is_open FROM parts'), [(0,)])
        for table, rows in before.items():
            self.assertEqual(self.rows('SELECT * FROM ' + table), rows)
        for path, value in files.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), value)
        self.add(content='late source')
        self.run_day()
        self.assertEqual(self.rows('SELECT part,active_revision FROM parts ORDER BY part'), [(1, 1), (2, 1)])

    def test_latest_source_restarts_quiet_period(self):
        self.prepare()
        self.add(content='second')
        later = STAMP + timedelta(minutes=20)
        with patch.object(daily, 'materialization_timestamp', return_value=later.isoformat()), \
                patch('parts.datetime', wraps=datetime) as clock:
            clock.now.return_value = later
            self.run_day()
        self.assertEqual(self.offer_at(STAMP + OFFER_QUIET_PERIOD), ())
        self.assertEqual(self.offer_at(later + OFFER_QUIET_PERIOD)[0].revision, 2)

    def test_pending_same_week_topic_and_running_topic_block_open_offer(self):
        self.prepare()
        self.add(content='pending')
        now = STAMP + timedelta(hours=1)
        self.assertEqual(self.offer_at(now), ())
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM ingress_queue WHERE status='pending'")
            db.execute("INSERT INTO sherlock_runs(topic,status,started_at) VALUES (2,'running',?)", (STAMP.isoformat(),))
        self.assertEqual(self.offer_at(now), ())
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE sherlock_runs SET status='completed',finished_at='2026-10-16T07:30:00+00:00'")
        self.add(topic=1)  # Unrelated pending work does not hold this topic hostage.
        self.assertEqual(len(self.offer_at(now)), 1)

    def test_unknown_naive_invalid_or_future_timestamp_never_seals(self):
        self.prepare()
        for stamp in (None, 'bad', '2026-10-16T07:15:00', '2027-01-01T00:00:00+00:00'):
            with self.subTest(stamp=stamp), sqlite3.connect(self.db) as db:
                db.execute('DROP TRIGGER IF EXISTS source_materializations_immutable_delete')
                db.execute('DROP TRIGGER IF EXISTS source_materializations_immutable_update')
                db.execute('DELETE FROM source_materializations')
                if stamp is not None:
                    db.execute('INSERT INTO source_materializations VALUES (1,?)', (stamp,))
            self.assertEqual(self.offer_at(STAMP + timedelta(hours=1)), ())
        with self.assertRaises(ValueError):
            self.offer_at(datetime(2026, 10, 16))

    def test_closed_part_needs_no_age_and_empty_daily_offers_without_rewriting(self):
        self.prepare()
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE parts SET is_open=0')
        with patch.object(daily, 'write_thread', side_effect=AssertionError('no writes')):
            self.assertEqual(self.run_day()['threads'], 0)
        self.assertEqual(len(self.rows('SELECT * FROM part_offers')), 1)
        self.run_day()
        self.assertEqual(len(self.rows('SELECT * FROM part_offers')), 1)

    def test_selection_and_sealing_batch_roll_back_on_failure(self):
        self.prepare()
        self.add(topic=1)
        with patch.object(daily, 'materialization_timestamp', return_value=STAMP.isoformat()), \
                patch('parts.datetime', wraps=datetime) as clock:
            clock.now.return_value = STAMP
            self.run_day()
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER fail_offer BEFORE INSERT ON part_offers WHEN NEW.part_id=1 BEGIN SELECT RAISE(ABORT,'fail offer'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'fail offer'):
            self.offer_at(STAMP + timedelta(hours=1))
        self.assertEqual(self.rows('SELECT * FROM part_offers'), [])
        self.assertEqual(self.rows('SELECT is_open FROM parts'), [(1,), (1,)])

    def test_empty_daily_runs_policy_and_logs_only_new_offers(self):
        self.prepare()
        with patch('parts.datetime', wraps=datetime) as clock:
            clock.now.return_value = STAMP + OFFER_QUIET_PERIOD
            with self.assertLogs('daily', level='INFO') as logs:
                self.assertEqual(self.run_day()['threads'], 0)
            self.assertIn('Parts aangeboden: aantal=1', logs.output[0])
            with patch.object(daily.logger, 'info') as info:
                self.run_day()
                info.assert_not_called()
        self.assertEqual(len(self.rows('SELECT * FROM part_offers')), 1)

    def test_offer_failure_after_materialization_retries_without_duplicate_sources(self):
        self.add(content='x' * 100)
        self.add(content='y' * 100)
        with patch.object(daily, 'token_count', side_effect=len), patch.object(daily, 'LIMIT', 5400), \
                patch.object(PartStore, '_offer', side_effect=sqlite3.OperationalError('offer failure')), \
                self.assertLogs('daily', level='ERROR'), \
                self.assertRaisesRegex(sqlite3.OperationalError, 'offer failure'):
            self.run_day()
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('processed',), ('processed',)])
        provenance = self.rows('SELECT * FROM part_revisions')
        self.assertEqual(self.rows('SELECT * FROM part_offers'), [])
        self.run_day()
        self.assertEqual(self.rows('SELECT * FROM part_revisions'), provenance)
        self.assertEqual(len(self.rows('SELECT * FROM source_archive')), 2)
        self.assertEqual(len(self.rows('SELECT * FROM source_materializations')), 2)
        self.assertEqual(len(self.rows('SELECT * FROM part_offers')), 1)

    def test_future_pending_same_week_blocks_but_other_week_does_not(self):
        self.prepare()
        self.add('2026-10-11')  # Same ISO week, independently of daily cutoff.
        self.assertEqual(self.offer_at(STAMP + timedelta(hours=1)), ())
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM ingress_queue WHERE status='pending'")
        self.add('2026-10-12')  # Another week of the same topic may proceed independently.
        self.assertEqual(len(self.offer_at(STAMP + timedelta(hours=1))), 1)

    def test_caller_transaction_is_preserved_and_concurrent_writer_prevents_selection(self):
        self.prepare()
        db = sqlite3.connect(self.db, timeout=0)
        other = sqlite3.connect(self.db)
        try:
            db.execute('BEGIN')
            with self.assertRaises(ValueError):
                PartStore(db).offer_ready(STAMP + timedelta(hours=1))
            self.assertTrue(db.in_transaction)
            db.rollback()
            other.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError):
                PartStore(db).offer_ready(STAMP + timedelta(hours=1))
            self.assertEqual(other.execute('SELECT count(*) FROM part_offers').fetchone(), (0,))
            other.rollback()
            self.assertEqual(len(PartStore(db).offer_ready(STAMP + timedelta(hours=1))), 1)
        finally:
            db.close()
            other.close()
