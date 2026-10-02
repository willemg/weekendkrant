from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import ariadne
import daily
from test_prepare_week_runtime import RuntimeGitFixture


class WorktreeTests(RuntimeGitFixture):
    def setUp(self):
        super().setUp()
        self.weekroot = self.root.parent / 'weekworktree'
        self.db = self.root.parent / 'state.sqlite3'
        self.output = self.root.parent / 'draden'
        # Remote ingress is deliberately based on old main without daily.py.
        other = self.other_clone()
        self.run_git(other, 'switch', '-c', self.branch)
        marker = other / 'ingress/2026_W41/closed/2026-10-05.json'
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({'schema_version': 1, 'date': '2026-10-05',
                                     'week': '2026_W41', 'files': []}))
        self.run_git(other, 'add', 'ingress')
        self.run_git(other, 'commit', '-m', 'Oude code met afgesloten oogst')
        self.run_git(other, 'push', '-u', 'origin', self.branch)
        self.old_head = self.remote_ref(self.branch)
        for name in ('ariadne.py', 'daily.py'):
            shutil.copy(Path(ariadne.__file__).parent / name, self.root / name)
        self.git('add', '*.py')
        self.git('commit', '-m', 'Actuele uitvoercode')
        self.git('push')
        self.code_head = self.git('rev-parse', 'HEAD')

    def daily(self):
        return daily.run_daily(self.root, self.db, self.output,
                               now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc))

    def assert_code_available(self):
        self.assertEqual(self.git('branch', '--show-current'), 'main')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.code_head)
        result = subprocess.run([sys.executable, str(self.root / 'ariadne.py'),
                                 'daily', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('daily', result.stdout)

    def test_old_ingress_daily_and_new_cli_process(self):
        self.daily()
        self.assert_code_available()
        self.assertFalse((self.weekroot / 'daily.py').exists())
        self.assertEqual(self.run_git(self.weekroot, 'branch', '--show-current'), self.branch)
        self.assertEqual(self.remote_ref(self.branch), self.old_head)
        self.daily()
        self.assertEqual(self.git('worktree', 'list', '--porcelain').count('worktree '), 2)

    def test_week_transition_keeps_code_branch_and_old_harvest(self):
        self.daily()
        ariadne.prepare_week_runtime(self.root, date(2026, 10, 12))
        self.assert_code_available()
        self.assertEqual(self.run_git(self.weekroot, 'branch', '--show-current'), 'ingress/2026_W42')
        self.assertEqual(self.git('rev-parse', self.branch), self.old_head)
        self.assertEqual(self.remote_ref(self.branch), self.old_head)
        self.assertIn('files', self.git('show', self.branch + ':ingress/2026_W41/closed/2026-10-05.json'))
        ariadne.prepare_week_runtime(self.root, date(2026, 10, 12))
        self.assertEqual(self.git('worktree', 'list', '--porcelain').count('worktree '), 2)

    def test_dirty_week_preserved(self):
        self.daily()
        path = self.weekroot / 'unpublished.txt'
        path.write_text('Niet weggooien')
        for run in (self.daily, lambda: ariadne.prepare_week_runtime(self.root, date(2026, 10, 12))):
            with self.assertRaisesRegex(ValueError, 'Vuile|wijzigingen'):
                run()
            self.assertEqual(path.read_text(), 'Niet weggooien')
        self.assert_code_available()

    def test_unexpected_worktree_stops_without_cleanup(self):
        extra = self.root.parent / 'unexpected'
        self.git('worktree', 'add', '--detach', str(extra), 'main')
        with self.assertRaisesRegex(ValueError, 'worktree'):
            self.daily()
        self.assertTrue(extra.exists())
        self.assertFalse(self.weekroot.exists())
        self.assert_code_available()

    def test_third_worktree_stops_even_on_success_repeat(self):
        self.daily()
        extra = self.root.parent / 'unexpected'
        self.git('worktree', 'add', '--detach', str(extra), 'main')
        with self.assertRaisesRegex(ValueError, 'worktree'):
            self.daily()
        self.assertTrue(extra.exists())
        self.assertTrue(self.weekroot.exists())

    def test_locked_managed_worktree_not_removed(self):
        self.daily()
        self.git('worktree', 'lock', str(self.weekroot))
        with self.assertRaises(ValueError):
            ariadne.prepare_week_runtime(self.root, date(2026, 10, 12))
        self.assertTrue(self.weekroot.exists())

    def test_ignored_week_files_are_not_discarded(self):
        self.daily()
        self.week_git('config', 'core.excludesFile', str(self.root.parent / 'excludes'))
        (self.root.parent / 'excludes').write_text('precious.tmp\n')
        precious = self.weekroot / 'precious.tmp'
        precious.write_text('Behouden ondanks ignore')
        with self.assertRaisesRegex(ValueError, 'Vuile'):
            ariadne.prepare_week_runtime(self.root, date(2026, 10, 12))
        self.assertTrue(precious.exists())

    def test_week_report_precedes_retention_and_preparation(self):
        events = []
        def report(path, day):
            events.append('report')
            return [{'date': str(day), 'status': 'timeout'}]
        def prune(path, day):
            events.append('prune')
        with patch.object(daily, 'week_report', side_effect=report), \
                patch.object(daily, 'prune_history', side_effect=prune), \
                patch.object(ariadne, '_prepare_week_runtime', side_effect=lambda *args: events.append('prepare')):
            ariadne.prepare_week_runtime(self.root, date(2026, 10, 12), report_day=self.day)
        self.assertEqual(events, ['report', 'prune', 'prepare'])

    def test_existing_unregistered_path_is_not_removed(self):
        self.weekroot.mkdir()
        precious = self.weekroot / 'precious'
        precious.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'niet geregistreerd'):
            self.daily()
        self.assertEqual(precious.read_text(), 'keep')

    def test_state_cannot_be_written_into_weekworktree(self):
        with self.assertRaises(ValueError):
            daily.run_daily(self.root, self.weekroot / 'state.sqlite3', self.output,
                            now=datetime(2026, 10, 5, 8, tzinfo=timezone.utc))
        self.assertFalse((self.weekroot / 'state.sqlite3').exists())



class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'audit.sqlite3'

    def seed(self, day, state='success'):
        db = daily.database(self.path)
        with db:
            daily.status(db, day, state)
            db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?)',
                       (str(day), str(day), 1, 1, 'hash', 1, 'cl100k_base', 5000))
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?)',
                       (str(day), 'source', 'hash', str(day), 0))
        db.close()

    def test_eight_iso_weeks_and_all_related_rows(self):
        # Aflopende 2021_W01: retain 2020_W47 through 2021_W01 (includes W53).
        report_day = date(2021, 1, 10)
        boundary = date(2020, 11, 16)
        self.seed(boundary - timedelta(days=1), 'processing_error')
        self.seed(boundary, 'timeout')
        self.seed(report_day)
        self.seed(report_day + timedelta(days=1))
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO attempts(day,status) VALUES (?,?)', ('2020-01-01', 'timeout'))
        self.assertEqual(daily.prune_history(self.path, report_day), boundary)
        with sqlite3.connect(self.path) as db:
            for table in ('days', 'attempts', 'threads', 'sources'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 3)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA freelist_count').fetchone()[0], 0)
        daily.prune_history(self.path, report_day)

    def test_retention_rolls_back_on_related_delete_failure(self):
        self.seed(date(2020, 1, 1))
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER refuse BEFORE DELETE ON days BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            daily.prune_history(self.path, date(2021, 1, 10))
        with sqlite3.connect(self.path) as db:
            for table in ('days', 'attempts', 'threads', 'sources'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 1)

    def test_fixed_topic_catalog(self):
        for topic in ('0', '5', '999999999999999999999', '-1', '01'):
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                daily.parse_fiche(f'WEEKENDKRANT-INGRESS-1\ntopic: {topic}\ndate: 2026-10-05\n\nBody'.encode())
        for topic in range(1, 5):
            self.assertEqual(daily.parse_fiche(
                f'WEEKENDKRANT-INGRESS-1\ntopic: {topic}\ndate: 2026-10-05\n\nBody'.encode())[0], topic)

    def test_vacuum_reclaims_space_after_deletion(self):
        self.seed(date(2020, 1, 1), 'processing_error')
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE days SET error=?', ('x' * 1000000,))
        before = self.path.stat().st_size
        daily.prune_history(self.path, date(2021, 1, 10))
        self.assertLess(self.path.stat().st_size, before // 2)
