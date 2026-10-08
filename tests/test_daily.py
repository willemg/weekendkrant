from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import ariadne
import daily


class WeaveTests(unittest.TestCase):
    def test_weave_stable_split_and_oversize(self):
        fiches = [daily.Fiche(f'queue:{i}', 2, b'x' * 150, 'abc') for i in range(3)]
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
        fiches = [daily.Fiche(f'queue:{i}', 2, data, 'a' * 64) for i in range(2)]
        result = daily.weave(fiches, '2026_W41', date(2026, 10, 5))
        self.assertEqual(len(result), 2)
        for thread in result:
            self.assertEqual(thread['tokens'], daily.token_count(thread['text']))
            self.assertLessEqual(thread['tokens'] + daily.RESERVE, daily.LIMIT)
        with self.assertRaisesRegex(ValueError, 'fiche'):
            daily.weave([daily.Fiche('queue:99', 1, data * 2, 'b' * 64)],
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
