"""Logical scheduler admission, independent of platform occurrence metadata."""
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import sqlite3
import unittest

from executor_slot import start_arguments
from sherlock_executor import SherlockExecutor
from job_control import JobControl


class SlotTests(unittest.TestCase):
    def args(self, value):
        return start_arguments(datetime.fromisoformat(value))

    def test_brussels_scheduler_jitter_reaches_start(self):
        expected = dict(
            activation_id='weekendkrant:executor-1:2026-10-15T06:00:00Z',
            operation_id='start:weekendkrant:executor-1:2026-10-15T06:00:00Z')
        with sqlite3.connect(':memory:') as db:
            executor = SherlockExecutor(db)
            answers = []
            for hour, minute in ((7, 49), (7, 55), (8, 0), (8, 9), (8, 10), (8, 11)):
                with self.subTest(hour=hour, minute=minute):
                    args = start_arguments(datetime(2026, 10, 15, hour, minute,
                                                   tzinfo=ZoneInfo('Europe/Brussels')))
                    self.assertEqual(args, expected)
                    answers.append(executor.start(args))
            self.assertTrue(all(answer == answers[0] for answer in answers))
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM job_attempts').fetchone()[0], 1)

    def test_inclusive_tolerance_and_half_hour_tie(self):
        previous = self.args('2026-10-15T05:00:00+00:00')
        following = self.args('2026-10-15T06:00:00+00:00')
        for stamp, expected in (
            ('05:14:59.999999', previous), ('05:15:00', previous),
            ('05:15:00.000001', None), ('05:29:59.999999', None),
            ('05:30:00', None), ('05:30:00.000001', None),
            ('05:44:59.999999', None), ('05:45:00', following),
            ('05:45:00.000001', following), ('06:15:00', following),
            ('06:15:00.000001', None)):
            with self.subTest(stamp=stamp):
                self.assertEqual(self.args('2026-10-15T' + stamp + '+00:00'), expected)
        self.assertEqual(self.args('2026-10-15T23:45:00+00:00'),
                         self.args('2026-10-16T00:00:00+00:00'))

    def test_no_job_outside_window_and_receipt_replay_after_hour(self):
        with sqlite3.connect(':memory:') as db:
            executor = SherlockExecutor(db)
            args = self.args('2026-10-15T16:15:00.000001+00:00')
            if args is not None:
                executor.start(args)
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
            frozen = self.args('2026-10-15T16:01:00+00:00')
            answer = executor.start(frozen)
            self.assertEqual(executor.start(self.args('2026-10-15T16:09:00+00:00')), answer)
            claim = {k: answer[k] for k in ('job_id', 'attempt_id', 'token')}
            JobControl(db).execute('finish', dict(claim, operation_id='finish:'+frozen['activation_id'],
                status='succeeded', output_refs=[answer['result_ref']]))
            # Retry after any delay reuses captured arguments, never resamples clock.
            self.assertEqual(executor.start(frozen), answer)
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM job_attempts').fetchone()[0], 1)
            later = executor.start(self.args('2026-10-15T17:00:00+00:00'))
            self.assertEqual(later, {'claim': None})  # New slot, still inside backend cooldown.
            self.assertNotEqual(frozen, self.args('2026-10-15T17:00:00+00:00'))

    def test_concurrent_logical_slot_starts_share_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.sqlite3'
            with sqlite3.connect(path) as db:
                SherlockExecutor(db)
            def start(minute):
                with sqlite3.connect(path, timeout=5) as db:
                    return SherlockExecutor(db).start(self.args(
                        '2026-10-15T16:0' + str(minute) + ':00+00:00'))
            with ThreadPoolExecutor(4) as pool:
                answers = list(pool.map(start, range(4)))
            self.assertTrue(all(answer == answers[0] for answer in answers))
            with sqlite3.connect(path) as db:
                for table in ('jobs', 'job_attempts', 'sherlock_runs', 'executor_activations'):
                    self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 1)

    def test_dst_and_timezone_normalization(self):
        brussels = ZoneInfo('Europe/Brussels')
        for stamp in ('2026-03-29T00:49:00+00:00', '2026-10-25T00:49:00+00:00',
                      '2026-03-29T00:01:00+00:00', '2026-03-29T01:01:00+00:00',
                      '2026-10-25T00:01:00+00:00', '2026-10-25T01:01:00+00:00'):
            instant = datetime.fromisoformat(stamp)
            self.assertEqual(start_arguments(instant), start_arguments(instant.astimezone(brussels)))
        self.assertEqual(self.args('2026-10-15T11:49:00+05:45'),
                         self.args('2026-10-15T06:04:00+00:00'))
        self.assertNotEqual(self.args('2026-10-25T00:01:00+00:00'),
                            self.args('2026-10-25T01:01:00+00:00'))

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError):
            start_arguments(datetime(2026, 10, 15, 16))
