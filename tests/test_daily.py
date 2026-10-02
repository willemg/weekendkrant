from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import ariadne
import daily
import test_prepare_week_runtime as weekly


class FakeClock:
    def __init__(self):
        self.value = 0
        self.sleeps = []
    def __call__(self):
        return self.value
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class DailyTests(weekly.RuntimeGitFixture):
    def setUp(self):
        super().setUp()
        self.db = Path(self.tmp.name) / 'state.sqlite3'
        self.output = Path(self.tmp.name) / 'threads'
        self.clock = FakeClock()
        self.prepare()

    def publish(self, items=None):
        items = items if items is not None else [('ingress_0001.md', 2, 'Bron https://example.org/é\n')]
        files = []
        for name, topic, body in items:
            path = f'ingress/2026_W41/{name}'
            data = f'WEEKENDKRANT-INGRESS-1\ntopic: {topic}\ndate: 2026-10-05\n\n{body}'.encode()
            (self.root / path).write_bytes(data)
            files.append({'path': path, 'sha256': hashlib.sha256(data).hexdigest()})
        marker = self.root / 'ingress/2026_W41/closed/2026-10-05.json'
        marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({'schema_version': 1, 'date': '2026-10-05',
                                     'week': '2026_W41', 'files': files}))
        self.git('add', 'ingress')
        self.git('commit', '-m', 'Afgesloten oogst')
        self.git('push')
        return marker

    def run_daily(self, **kwargs):
        return daily.run_daily(self.root, db_path=self.db, output=self.output,
                               now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc),
                               monotonic=self.clock, sleep=self.clock.sleep, **kwargs)

    def status(self):
        with sqlite3.connect(self.db) as db:
            return db.execute('SELECT status FROM days').fetchone()[0]

    def test_daily_empty_and_repeat(self):
        self.publish([])
        self.assertEqual(self.run_daily()['status'], 'success')
        self.assertEqual(self.run_daily()['status'], 'success')
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM days').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM threads').fetchone()[0], 0)

    def test_daily_provenance_and_repeat(self):
        self.publish()
        self.run_daily()
        files = list(self.output.rglob('*.txt'))
        self.assertEqual(len(files), 1)
        before = files[0].read_bytes()
        self.assertIn('https://example.org/é', before.decode())
        self.run_daily()
        self.assertEqual(files[0].read_bytes(), before)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sources').fetchone()[0], 1)

    def test_daily_timeout_and_immediate_check(self):
        with self.assertRaises(TimeoutError):
            self.run_daily()
        self.assertEqual(self.clock.sleeps, [600] * 18)
        self.assertEqual(self.status(), 'timeout')
        self.assertFalse(self.output.exists())

    def test_daily_poll_fetches_again(self):
        self.clock.sleep = unittest.mock.Mock(wraps=self.clock.sleep)
        original = self.clock.sleep
        def publish_after_wait(seconds):
            original(seconds)
            self.publish([])
        self.clock.sleep = publish_after_wait
        self.run_daily()
        self.assertEqual(self.clock.sleeps, [600])

    def test_daily_invalid_hash_is_processing_error(self):
        self.publish()
        path = self.root / 'ingress/2026_W41/ingress_0001.md'
        path.write_text(path.read_text() + 'Late wijziging')
        self.git('add', 'ingress'); self.git('commit', '-m', 'Late wijziging'); self.git('push')
        with self.assertRaises(ValueError):
            self.run_daily()
        self.assertEqual(self.status(), 'processing_error')
        self.assertFalse(self.output.exists())

    def test_daily_remote_fast_forward(self):
        old = self.git('rev-parse', 'HEAD')
        self.publish([])
        target = self.git('rev-parse', 'HEAD')
        self.git('switch', 'main')
        self.git('branch', '-f', self.branch, old)
        self.run_daily()
        self.assertEqual(self.git('rev-parse', 'HEAD'), target)

    def test_daily_dirty_and_ahead_refused(self):
        self.publish([])
        (self.root / 'local').write_text('keep')
        with self.assertRaises(ValueError): self.run_daily()
        self.git('add', 'local'); self.git('commit', '-m', 'Local')
        head = self.git('rev-parse', 'HEAD')
        with self.assertRaises(ValueError): self.run_daily()
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)

    def test_daily_output_failure_never_success(self):
        self.publish()
        with patch.object(daily, 'write_thread', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.run_daily()
        self.assertEqual(self.status(), 'processing_error')
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sources').fetchone()[0], 0)
        self.run_daily()
        self.assertEqual(self.status(), 'success')

    def test_daily_shared_lock(self):
        with ariadne.clone_lock(self.root):
            with self.assertRaises(ValueError): self.run_daily()
            with self.assertRaises(ValueError): self.prepare()

    def test_week_prepares_despite_failed_days(self):
        with self.assertRaises(TimeoutError): self.run_daily()
        report = daily.week_report(self.db, self.day)
        self.assertEqual(len(report), 7)
        with patch.object(ariadne, 'DB_PATH', self.db):
            ariadne.prepare_week_runtime(self.root, date(2026, 10, 12), report_day=self.day)
        self.assertEqual(self.status(), 'timeout')
        self.assertEqual(self.remote_ref('ingress/2026_W42'), self.git('rev-parse', 'HEAD'))

    def commit_ingress(self):
        self.git('add', 'ingress')
        self.git('commit', '-m', 'Wijziging oogst')
        self.git('push')

    def test_daily_late_extra_fiche_refused(self):
        self.publish([])
        (self.root / 'ingress/2026_W41/ingress_0002.md').write_text(
            'WEEKENDKRANT-INGRESS-1\ntopic: 1\ndate: 2026-10-05\n\nLate bron')
        self.commit_ingress()
        with self.assertRaises(ValueError): self.run_daily()
        self.assertEqual(self.status(), 'processing_error')

    def test_daily_manifest_revision_refused(self):
        marker = self.publish([])
        marker.write_text(marker.read_text() + '\n')
        self.commit_ingress()
        with self.assertRaisesRegex(ValueError, 'gewijzigd'): self.run_daily()

    def test_daily_invalid_manifest_and_duplicate_keys_refused(self):
        marker = self.publish([])
        marker.write_text('{"schema_version":1,"schema_version":1}')
        self.commit_ingress()
        with self.assertRaisesRegex(ValueError, 'Dubbele'): self.run_daily()

    def test_daily_remote_only_branch(self):
        self.publish([])
        self.git('switch', 'main')
        self.git('branch', '-d', self.branch)
        self.run_daily()
        self.assertEqual(self.git('branch', '--show-current'), self.branch)

    def test_daily_divergence_preserves_both_histories(self):
        self.publish([])
        other = self.other_clone()
        self.run_git(other, 'switch', self.branch)
        (other / 'remote').write_text('keep remote')
        self.run_git(other, 'add', 'remote')
        self.run_git(other, 'commit', '-m', 'Remote')
        self.run_git(other, 'push')
        (self.root / 'local').write_text('keep local')
        self.git('add', 'local'); self.git('commit', '-m', 'Local')
        before = self.git('rev-parse', 'HEAD')
        remote = self.remote_ref(self.branch)
        with self.assertRaises(ValueError): self.run_daily()
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.remote_ref(self.branch), remote)

    def test_daily_deadline_includes_fetch_and_never_sleeps_past_it(self):
        real = daily._git
        def slow_fetch(root, *args, **kwargs):
            result = real(root, *args, **kwargs)
            if args[0] == 'fetch': self.clock.value += 10799
            return result
        with patch.object(daily, '_git', side_effect=slow_fetch):
            with self.assertRaises(TimeoutError): self.run_daily()
        self.assertEqual(self.clock.sleeps, [1])

    def test_daily_ready_at_deadline_is_not_processed(self):
        self.publish([])
        real = daily._git
        def slow_fetch(root, *args, **kwargs):
            result = real(root, *args, **kwargs)
            if args[0] == 'fetch': self.clock.value = 10800
            return result
        with patch.object(daily, '_git', side_effect=slow_fetch):
            with self.assertRaises(TimeoutError): self.run_daily()
        self.assertEqual(self.status(), 'timeout')

    def test_daily_later_day_preserves_previous_output(self):
        self.publish()
        self.run_daily()
        first = {p: p.read_bytes() for p in self.output.rglob('*.txt')}
        path = 'ingress/2026_W41/ingress_0002.md'
        data = b'WEEKENDKRANT-INGRESS-1\ntopic: 2\ndate: 2026-10-06\n\nNext day'
        (self.root / path).write_bytes(data)
        (self.root / 'ingress/2026_W41/closed/2026-10-06.json').write_text(json.dumps({
            'schema_version': 1, 'date': '2026-10-06', 'week': '2026_W41',
            'files': [{'path': path, 'sha256': hashlib.sha256(data).hexdigest()}]}))
        self.commit_ingress()
        daily.run_daily(self.root, self.db, self.output,
                        now=datetime(2026, 10, 6, 8, tzinfo=timezone.utc))
        self.assertEqual(len(list(self.output.rglob('*.txt'))), 2)
        for path, data in first.items(): self.assertEqual(path.read_bytes(), data)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sources').fetchone()[0], 2)

    def test_daily_partial_write_rolls_back_all_provenance(self):
        self.publish([('ingress_0001.md', 1, 'one'), ('ingress_0002.md', 2, 'two')])
        original = daily.write_thread
        calls = []
        def fail_second(path, data):
            calls.append(path)
            if len(calls) == 2: raise OSError('full')
            original(path, data)
        with patch.object(daily, 'write_thread', side_effect=fail_second):
            with self.assertRaises(OSError): self.run_daily()
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM threads').fetchone()[0], 0)
        self.run_daily()
        self.assertEqual(self.status(), 'success')
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM threads').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT status FROM attempts ORDER BY id').fetchall(),
                             [('processing_error',), ('success',)])

    def test_daily_operational_files_cannot_be_in_repo(self):
        with self.assertRaises(ValueError):
            daily.run_daily(self.root, self.root / 'state.sqlite3', self.output)


    def test_daily_deleted_remote_branch_cannot_use_stale_tracking_ref(self):
        self.publish([])
        self.git('push', 'origin', '--delete', self.branch)
        # Simulate the stale tracking ref left by deletion from another clone.
        self.git('update-ref', 'refs/remotes/origin/' + self.branch,
                 self.git('rev-parse', 'HEAD'))
        with self.assertRaises(TimeoutError): self.run_daily()
        self.assertEqual(self.status(), 'timeout')

    def test_daily_only_current_week_even_if_other_branch_checked_out(self):
        self.publish([])
        old_head = self.git('rev-parse', 'HEAD')
        clock = FakeClock()
        with self.assertRaises(TimeoutError):
            daily.run_daily(self.root, self.db, self.output,
                            now=datetime(2026, 10, 12, 8, tzinfo=timezone.utc),
                            monotonic=clock, sleep=clock.sleep)
        self.assertEqual(self.git('rev-parse', 'HEAD'), old_head)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT day,status FROM days').fetchall(),
                             [('2026-10-12', 'timeout')])



class WeaveTests(unittest.TestCase):
    def test_metadata_rejects_ambiguous_or_invalid_headers(self):
        for header in ('topic: x\ndate: 2026-10-05', 'topic: 1\ndate: 2026-02-30',
                       'topic: 1\ntopic: 2\ndate: 2026-10-05'):
            with self.assertRaises(ValueError):
                daily.parse_fiche(('WEEKENDKRANT-INGRESS-1\n' + header + '\n\nBody').encode())

    def test_weave_stable_split_and_oversize(self):
        fiches = [daily.Fiche(f'ingress_000{i}.md', 2, b'x' * 150, 'abc') for i in range(3)]
        first = daily.weave(fiches, '2026_W41', date(2026, 10, 5), count=len, limit=700, reserve=100)
        second = daily.weave(list(reversed(fiches)), '2026_W41', date(2026, 10, 5), count=len, limit=700, reserve=100)
        self.assertEqual(first, second)
        self.assertGreater(len(first), 1)
        self.assertEqual(sum(len(t['sources']) for t in first), 3)
        self.assertTrue(all(len(t['text']) + 100 <= 700 for t in first))
        with self.assertRaisesRegex(ValueError, 'fiche'):
            daily.weave(fiches, '2026_W41', date(2026, 10, 5), count=len, limit=200, reserve=100)

    def test_brussels_date(self):
        self.assertEqual(daily.local_day(datetime(2026, 10, 4, 22, 1, tzinfo=timezone.utc)), date(2026, 10, 5))

    def test_real_tokenizer_bounds_full_serialized_threads(self):
        data = ('één bron https://example.org/ <|endoftext|>\n' * 1500).encode()
        fiches = [daily.Fiche(str(i), 2, data, 'a' * 64) for i in range(2)]
        result = daily.weave(fiches, '2026_W41', date(2026, 10, 5))
        self.assertEqual(len(result), 2)
        for thread in result:
            self.assertEqual(thread['tokens'], daily.token_count(thread['text']))
            self.assertLessEqual(thread['tokens'] + daily.RESERVE, daily.LIMIT)
        with self.assertRaisesRegex(ValueError, 'fiche'):
            daily.weave([daily.Fiche('huge', 1, data * 2, 'b' * 64)],
                        '2026_W41', date(2026, 10, 5))


class DailyCliTests(unittest.TestCase):
    def test_timeout_exits_nonzero(self):
        with patch('sys.argv', ['ariadne.py', 'daily']), \
                patch.object(ariadne, 'configure_logging'), \
                patch.object(daily, 'run_daily', side_effect=TimeoutError('deadline')), \
                self.assertLogs('ariadne', level='ERROR'), \
                self.assertRaises(SystemExit) as stopped:
            ariadne.main()
        self.assertEqual(stopped.exception.code, 1)
