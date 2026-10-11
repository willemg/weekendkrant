"""Reviewed-page identity and method-owned, persistent Sherlock audit state."""
from datetime import datetime, timezone
import sqlite3
import tempfile
from pathlib import Path
import unittest

from sherlock_state import SherlockState, canonicalize_url


class CanonicalURLTests(unittest.TestCase):
    def test_tracking_fragment_case_and_default_ports(self):
        for url in ('https://Example.COM/article?utm_source=x',
                    'HTTPS://EXAMPLE.COM:443/article#section',
                    'https://example.com/article?fbclid=x&gclid=y&trk=z&UTM_medium=a'):
            with self.subTest(url=url):
                self.assertEqual(canonicalize_url(url), 'https://example.com/article')
        self.assertEqual(canonicalize_url('HTTP://Example.COM:80/a'), 'http://example.com/a')
        self.assertEqual(canonicalize_url('https://[2001:DB8::1]:443/a'), 'https://[2001:db8::1]/a')

    def test_real_query_parameters_preserved_exactly(self):
        self.assertEqual(canonicalize_url('https://example.com/article?id=42&utm_source=x'),
                         'https://example.com/article?id=42')
        self.assertEqual(canonicalize_url('https://example.com/a?q=a%20b&q=a+b&flag=&%75tm_source=x&n=2'),
                         'https://example.com/a?q=a%20b&q=a+b&flag=&n=2')

    def test_distinct_resources_stay_distinct(self):
        urls = ['https://example.com/a', 'https://example.com/a/',
                'https://example.com/A', 'https://example.com/a?id=1',
                'https://example.com/a?id=2', 'https://example.com:8443/a',
                'http://example.com/a', 'https://example.com/a%2Fb',
                'https://example.com/a/b']
        self.assertEqual([canonicalize_url(u) for u in urls], urls)

    def test_unusable_urls_rejected(self):
        for url in (None, 42, '', '/article', 'example.com', 'ftp://example.com/a',
                    'https:///a', 'https://', 'https://user:pass@example.com/a',
                    'https://example.com:99999/a', 'https://example.com:bad/a',
                    'https://example.com:/a', 'https://example.com:0/a',
                    'https://[broken/a', 'https://exa mple.com/a',
                    ' https://example.com/a', 'https://example.com/a\n',
                    'https://example.com/\\a', 'https://example.com/%zz',
                    'https://bad_host/a'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonicalize_url(url)


class SherlockStateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.store = SherlockState(self.db)

    def record(self, run, topic=1, url='https://Example.COM/a?utm_source=x', **kw):
        return self.store.record_reviewed_source(run, topic, url,
                                                outcome='  afgewezen  ',
                                                rationale='Geen onafhankelijk bewijs.\nWel geopend.', **kw)

    def test_start_each_topic_and_finish_statuses(self):
        before = datetime.now(timezone.utc)
        ids = [self.store.start_run(topic) for topic in (1, 2, 3)]
        self.assertEqual(ids, sorted(set(ids)))
        for identity, topic in zip(ids, (1, 2, 3)):
            row = self.db.execute('SELECT topic,started_at,finished_at,status FROM sherlock_runs WHERE id=?', (identity,)).fetchone()
            self.assertEqual((row[0], row[2], row[3]), (topic, None, 'running'))
            self.assertGreaterEqual(datetime.fromisoformat(row[1]), before)
        for identity, status in zip(ids, ('completed', 'failed')):
            self.store.finish_run(identity, status)
            started, finished, actual = self.db.execute('SELECT started_at,finished_at,status FROM sherlock_runs WHERE id=?', (identity,)).fetchone()
            self.assertEqual(actual, status)
            self.assertGreaterEqual(datetime.fromisoformat(finished), datetime.fromisoformat(started))
            snapshot = list(self.db.iterdump())
            for again in ('completed', 'failed'):
                with self.assertRaises(ValueError):
                    self.store.finish_run(identity, again)
            self.assertEqual(list(self.db.iterdump()), snapshot)

    def test_invalid_topics_and_finish_requests(self):
        for topic in (0, 4, True, 1.0, '1', None):
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                self.store.start_run(topic)
        identity = self.store.start_run(1)
        for status in ('running', 'other', None):
            with self.assertRaises(ValueError):
                self.store.finish_run(identity, status)
        with self.assertRaises(ValueError):
            self.store.finish_run(999, 'failed')
        for bad_id in (True, 1.0, '1', None):
            with self.assertRaises(ValueError):
                self.store.finish_run(bad_id, 'failed')
        self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs').fetchone(), ('running',))

    def test_database_topic_and_status_constraints(self):
        for sql in ("INSERT INTO sherlock_runs(topic,started_at) VALUES (4,'now')",
                    "INSERT INTO sherlock_runs(topic,started_at,status) VALUES (1,'now','anything')"):
            with self.assertRaises(sqlite3.IntegrityError), self.db:
                self.db.execute(sql)

    def test_record_preserves_audit_and_recognizes_variants(self):
        identity = self.store.start_run(1)
        self.assertFalse(self.store.already_reviewed('https://example.com/a'))
        before = datetime.now(timezone.utc)
        self.record(identity)
        self.assertTrue(self.store.already_reviewed('https://example.com/a?gclid=abc#part'))
        row = self.db.execute('SELECT canonical_url,original_url,topic,run_id,reviewed_at,title,outcome,rationale FROM sherlock_sources').fetchone()
        self.assertEqual(row[:4], ('https://example.com/a', 'https://Example.COM/a?utm_source=x', 1, identity))
        self.assertGreaterEqual(datetime.fromisoformat(row[4]), before)
        self.assertEqual(row[5:], (None, '  afgewezen  ', 'Geen onafhankelijk bewijs.\nWel geopend.'))
        self.store.finish_run(identity, 'failed')
        self.assertTrue(self.store.already_reviewed('https://example.com/a'))

    def test_duplicate_rejected_across_runs_and_topics_without_overwriting(self):
        self.record(self.store.start_run(1), title='Oorspronkelijk')
        run = self.store.start_run(2)
        before = list(self.db.iterdump())
        with self.assertRaises(sqlite3.IntegrityError):
            self.record(run, topic=2, url='https://example.com/a#other', title='Ander')
        self.assertEqual(list(self.db.iterdump()), before)
        self.assertFalse(self.db.in_transaction)

    def test_distinct_urls_with_same_story_metadata_allowed(self):
        run = self.store.start_run(1)
        for url in ('https://example.com/a', 'https://elsewhere.example/story'):
            self.record(run, url=url, title='Hetzelfde verhaal')
        self.assertEqual(self.db.execute('SELECT count(*) FROM sherlock_sources').fetchone(), (2,))

    def test_unknown_mismatched_and_closed_runs_rejected(self):
        run = self.store.start_run(1)
        with self.assertRaises(ValueError):
            self.record(999)
        for topic in (2, True, '1', 1.0):
            with self.assertRaises(ValueError):
                self.record(run, topic=topic)
        for status in ('completed', 'failed'):
            identity = self.store.start_run(1)
            self.store.finish_run(identity, status)
            with self.assertRaises(ValueError):
                self.record(identity)
        self.assertEqual(self.db.execute('SELECT count(*) FROM sherlock_sources').fetchone(), (0,))
        self.record(run)  # Failed operations leave the connection usable.

    def test_invalid_source_input_does_not_change_state(self):
        run = self.store.start_run(1)
        for changes in ({'url': '/relative'}, {'outcome': ''}, {'rationale': '  '},
                        {'title': 42}, {'outcome': None}, {'run_id': True}):
            args = dict(run_id=run, topic=1, url='https://example.com/a', outcome='kept', rationale='Evidence')
            args.update(changes)
            with self.assertRaises(ValueError):
                self.store.record_reviewed_source(**args)
        with self.assertRaises(ValueError):
            self.store.already_reviewed('/relative')
        self.assertEqual(self.db.execute('SELECT count(*) FROM sherlock_sources').fetchone(), (0,))

    def test_methods_refuse_caller_transaction_without_committing(self):
        run = self.store.start_run(1)
        self.db.execute('BEGIN')
        for operation in (lambda: SherlockState(self.db), lambda: self.store.start_run(2),
                          lambda: self.store.finish_run(run, 'completed'),
                          lambda: self.record(run),
                          lambda: self.store.already_reviewed('https://example.com/a')):
            with self.assertRaises(ValueError):
                operation()
            self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT status FROM sherlock_runs').fetchone(), ('running',))

    def test_state_survives_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.sqlite3'
            with sqlite3.connect(path) as db:
                store = SherlockState(db)
                run = store.start_run(3)
                store.record_reviewed_source(run, 3, 'https://example.com/a', 'kept', 'Evidence', title='Titel')
                store.finish_run(run, 'completed')
            db.close()
            with sqlite3.connect(path) as db:
                store = SherlockState(db)
                self.assertTrue(store.already_reviewed('https://example.com/a?trk=x'))
                self.assertEqual(db.execute('SELECT status FROM sherlock_runs').fetchone(), ('completed',))
            db.close()
