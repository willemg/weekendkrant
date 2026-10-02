from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ariadne


class DateAndCliTests(unittest.TestCase):
    def test_next_week_uses_brussels_even_when_utc_is_still_sunday(self):
        # In Brussel is dit al maandag: de eerstvolgende ISO-week begint op 12/10.
        now = datetime(2026, 10, 4, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(ariadne.next_week_date(now), date(2026, 10, 12))

    def test_sunday_and_iso_year_boundaries(self):
        for now, expected, week in (
            (datetime(2026, 10, 4, 18, tzinfo=timezone.utc), date(2026, 10, 5), '2026_W41'),
            (datetime(2020, 12, 27, 18, tzinfo=timezone.utc), date(2020, 12, 28), '2020_W53'),
            (datetime(2021, 1, 3, 18, tzinfo=timezone.utc), date(2021, 1, 4), '2021_W01'),
        ):
            with self.subTest(now=now):
                target = ariadne.next_week_date(now)
                self.assertEqual(target, expected)
                self.assertEqual(ariadne.week_name(target), week)

    def test_dst_transitions(self):
        for now, expected in (
            (datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc), date(2026, 3, 30)),
            (datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc), date(2026, 3, 30)),
            (datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc), date(2026, 10, 26)),
            (datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc), date(2026, 10, 26)),
        ):
            with self.subTest(now=now):
                self.assertEqual(ariadne.next_week_date(now), expected)

    def test_host_timezone_does_not_change_target(self):
        now = datetime(2026, 10, 4, 22, 30, tzinfo=timezone.utc)
        for host_zone in ('UTC', 'America/Los_Angeles', 'Asia/Tokyo'):
            with self.subTest(zone=host_zone), patch.dict(os.environ, TZ=host_zone):
                self.assertEqual(ariadne.next_week_date(now), date(2026, 10, 12))

    def test_real_clock_is_queried_with_explicit_brussels_zone(self):
        with patch.object(ariadne, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 4, 18, tzinfo=timezone.utc)
            self.assertEqual(ariadne.next_week_date(), date(2026, 10, 5))
            self.assertEqual(clock.now.call_args.args[0].key, 'Europe/Brussels')

    def test_cli_next_week_passes_concrete_date(self):
        result = {'week': '2026_W41', 'branch': 'ingress/2026_W41',
                  'ingress_path': 'ingress/2026_W41', 'base_commit': 'abc'}
        with patch('sys.argv', ['ariadne.py', 'prepare-week', '--next-week']), \
                patch.object(ariadne, 'configure_logging'), \
                patch.object(ariadne, 'next_week_date', return_value=date(2026, 10, 5)), \
                patch.object(ariadne, 'prepare_week_runtime', return_value=result) as run, \
                redirect_stdout(io.StringIO()) as stdout:
            ariadne.main()
        run.assert_called_once_with(Path.cwd(), date(2026, 10, 5),
                                    report_day=date(2026, 9, 28))
        self.assertEqual(stdout.getvalue(), json.dumps(result, indent=2, sort_keys=True) + '\n')

    def test_cli_explicit_date_uses_its_own_week_without_clock(self):
        # --date op zondag blijft de opgegeven week; alleen --next-week schuift door.
        result = {'schema_version': 1, 'week': '2026_W40', 'branch': 'ingress/2026_W40',
                  'ingress_path': 'ingress/2026_W40', 'base_commit': 'abc'}
        with patch('sys.argv', ['ariadne.py', 'prepare-week', '--date', '2026-10-04']), \
                patch.object(ariadne, 'configure_logging'), \
                patch.object(ariadne, 'next_week_date') as clock, \
                patch.object(ariadne, 'prepare_week_runtime', return_value=result) as run, \
                redirect_stdout(io.StringIO()) as stdout:
            ariadne.main()
        clock.assert_not_called()
        run.assert_called_once_with(Path.cwd(), date(2026, 10, 4))
        self.assertEqual(stdout.getvalue(), json.dumps(result, indent=2, sort_keys=True) + '\n')

    def test_cli_requires_exactly_one_date_option(self):
        for args in ([], ['--date', '2026-10-04', '--next-week']):
            with self.subTest(args=args), patch('sys.argv', ['ariadne.py', 'prepare-week', *args]), \
                    redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
                ariadne.main()
            self.assertEqual(error.exception.code, 2)
            self.assertIn('error:', stderr.getvalue())
            self.assertIn('--next-week', stderr.getvalue())


class RuntimeGitFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'work'
        self.remote = Path(self.tmp.name) / 'origin.git'
        self.run_git(Path(self.tmp.name), 'init', '--bare', '-b', 'main', str(self.remote))
        self.run_git(Path(self.tmp.name), 'clone', str(self.remote), str(self.root))
        # Oudere Git-versies kunnen een lege clone op master laten beginnen.
        self.git('checkout', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.root / 'README.md').write_text('Initial\n')
        self.git('add', 'README.md')
        self.git('commit', '-m', 'Initial')
        self.git('push', '-u', 'origin', 'main')
        self.base = self.git('rev-parse', 'HEAD')
        self.branch = 'ingress/2026_W41'
        self.day = date(2026, 10, 5)
        self.paths = ['audit/2026_W41/ingress-preparation.json', 'ingress/2026_W41/.gitkeep']

    def run_git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.PIPE).strip()

    def git(self, *args):
        return self.run_git(self.root, *args)

    def prepare(self):
        return ariadne.prepare_week_runtime(self.root, self.day)

    def remote_ref(self, ref):
        return self.run_git(self.remote, 'rev-parse', ref)

    def other_clone(self):
        other = Path(self.tmp.name) / 'other'
        self.run_git(Path(self.tmp.name), 'clone', str(self.remote), str(other))
        self.run_git(other, 'config', 'user.name', 'Other')
        self.run_git(other, 'config', 'user.email', 'other@example.invalid')
        return other

    def advance_remote_main(self):
        other = self.other_clone()
        (other / 'new.md').write_text('New main\n')
        self.run_git(other, 'add', 'new.md')
        self.run_git(other, 'commit', '-m', 'Remote main')
        self.run_git(other, 'push', 'origin', 'main')
        return self.remote_ref('main')


class RuntimeGitTests(RuntimeGitFixture):
    def test_new_week_commits_only_preparation_and_pushes_with_upstream(self):
        result = self.prepare()
        self.assertEqual(result['base_commit'], self.base)
        self.assertEqual(self.git('show', '--pretty=', '--name-only', 'HEAD').splitlines(), self.paths)
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'Bereid ingress week 2026_W41 voor')
        self.assertEqual(self.remote_ref(self.branch), self.git('rev-parse', 'HEAD'))
        self.assertEqual(self.git('rev-parse', '--abbrev-ref', '@{upstream}'), 'origin/' + self.branch)
        self.assertEqual(self.git('rev-parse', 'main'), self.base)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_dirty_tree_is_rejected_before_fetch_or_switch(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                (self.root / 'README.md').write_text('Keep my work\n')
                if staged:
                    self.git('add', 'README.md')
                before = self.git('status', '--porcelain')
                with patch.object(ariadne, '_git', wraps=ariadne._git) as git, self.assertRaises(ValueError):
                    self.prepare()
                commands = [call.args[1] for call in git.call_args_list]
                self.assertNotIn('fetch', commands)
                self.assertNotIn('switch', commands)
                self.assertEqual(self.git('status', '--porcelain'), before)
                self.assertEqual((self.root / 'README.md').read_text(), 'Keep my work\n')

    def test_fast_forward_main_and_new_branch_use_fetched_commit(self):
        head = self.advance_remote_main()
        result = self.prepare()
        self.assertEqual(self.git('rev-parse', 'main'), head)
        self.assertEqual(result['base_commit'], head)
        self.assertEqual((self.root / 'new.md').read_text(), 'New main\n')

    def test_untracked_work_on_week_branch_is_refused_before_fetch(self):
        self.prepare()
        path = self.root / 'ingress/2026_W41/ingress_0001.md'
        path.write_text('Uncommitted harvest\n')
        with patch.object(ariadne, '_git', wraps=ariadne._git) as git, self.assertRaises(ValueError):
            self.prepare()
        self.assertNotIn('fetch', [call.args[1] for call in git.call_args_list])
        self.assertEqual(self.git('branch', '--show-current'), self.branch)
        self.assertEqual(path.read_text(), 'Uncommitted harvest\n')

    def test_divergent_main_fails_without_discarding_local_commit(self):
        remote = self.advance_remote_main()
        (self.root / 'local.md').write_text('Keep local\n')
        self.git('add', 'local.md')
        self.git('commit', '-m', 'Local main')
        local = self.git('rev-parse', 'HEAD')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.git('rev-parse', 'main'), local)
        self.assertEqual(self.remote_ref('main'), remote)
        self.assertFalse((self.root / 'ingress').exists())

    def test_local_main_ahead_of_origin_is_also_refused(self):
        (self.root / 'local.md').write_text('Unpublished main\n')
        self.git('add', 'local.md')
        self.git('commit', '-m', 'Local main')
        local = self.git('rev-parse', 'HEAD')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)
        self.assertEqual(self.remote_ref('main'), self.base)

    def test_remote_only_week_is_discovered_after_fetch_and_preserves_harvest(self):
        other = self.other_clone()
        self.run_git(other, 'switch', '-c', self.branch)
        (other / 'sherlock.md').write_text('Existing harvest\n')
        self.run_git(other, 'add', 'sherlock.md')
        self.run_git(other, 'commit', '-m', 'Sherlock')
        self.run_git(other, 'push', 'origin', self.branch)
        head = self.remote_ref(self.branch)
        with patch.object(ariadne, '_git', wraps=ariadne._git) as git, \
                patch.object(ariadne, '_has_ref', wraps=ariadne._has_ref) as has_ref:
            events = unittest.mock.Mock()
            events.attach_mock(git, 'git')
            events.attach_mock(has_ref, 'has_ref')
            result = self.prepare()
        fetch = next(i for i, c in enumerate(events.mock_calls) if c[0] == 'git' and c.args[1:] == ('fetch', 'origin'))
        decisions = [i for i, c in enumerate(events.mock_calls) if c[0] == 'has_ref']
        self.assertTrue(decisions)
        self.assertLess(fetch, min(decisions))
        self.assertEqual(result['base_commit'], head)
        self.assertEqual((self.root / 'sherlock.md').read_text(), 'Existing harvest\n')

    def test_repeat_is_idempotent_with_existing_sherlock_files(self):
        first = self.prepare()
        (self.root / 'ingress/2026_W41/ingress_0001.md').write_text('Harvest\n')
        self.git('add', 'ingress/2026_W41/ingress_0001.md')
        self.git('commit', '-m', 'Sherlock')
        self.git('push')
        head = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.prepare(), first)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.remote_ref(self.branch), head)
        self.assertEqual((self.root / 'ingress/2026_W41/ingress_0001.md').read_text(), 'Harvest\n')

    def test_local_only_week_is_reused_without_reset(self):
        self.git('switch', '-c', self.branch)
        (self.root / 'sherlock.md').write_text('Local harvest\n')
        self.git('add', 'sherlock.md')
        self.git('commit', '-m', 'Local harvest')
        head = self.git('rev-parse', 'HEAD')
        self.git('switch', 'main')
        self.assertEqual(self.prepare()['base_commit'], head)
        self.assertEqual((self.root / 'sherlock.md').read_text(), 'Local harvest\n')

    def test_conflicting_audit_is_preserved_and_not_pushed(self):
        self.prepare()
        audit = self.root / self.paths[0]
        audit.write_text('{"week": "wrong"}\n')
        self.git('add', self.paths[0])
        self.git('commit', '-m', 'Conflicting metadata')
        head = self.git('rev-parse', 'HEAD')
        remote = self.remote_ref(self.branch)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.remote_ref(self.branch), remote)
        self.assertEqual(audit.read_text(), '{"week": "wrong"}\n')

    def test_divergent_week_does_not_overwrite_remote_or_harvest(self):
        self.prepare()
        other = self.other_clone()
        self.run_git(other, 'switch', self.branch)
        (other / 'remote-harvest.md').write_text('Remote harvest\n')
        self.run_git(other, 'add', 'remote-harvest.md')
        self.run_git(other, 'commit', '-m', 'Remote harvest')
        self.run_git(other, 'push')
        remote = self.remote_ref(self.branch)
        (self.root / 'local-harvest.md').write_text('Local harvest\n')
        self.git('add', 'local-harvest.md')
        self.git('commit', '-m', 'Local harvest')
        local = self.git('rev-parse', 'HEAD')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.git('rev-parse', self.branch), local)
        self.assertEqual(self.remote_ref(self.branch), remote)
        self.assertEqual(self.git('show', self.branch + ':local-harvest.md'), 'Local harvest')

    def test_week_remote_ahead_is_refused_without_reset_or_merge(self):
        self.prepare()
        local = self.git('rev-parse', 'HEAD')
        other = self.other_clone()
        self.run_git(other, 'switch', self.branch)
        (other / 'sherlock.md').write_text('New remote harvest\n')
        self.run_git(other, 'add', 'sherlock.md')
        self.run_git(other, 'commit', '-m', 'Sherlock')
        self.run_git(other, 'push')
        remote = self.remote_ref(self.branch)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.git('rev-parse', self.branch), local)
        self.assertEqual(self.remote_ref(self.branch), remote)
        self.assertEqual(self.run_git(self.remote, 'show', self.branch + ':sherlock.md'),
                         'New remote harvest')

    def test_push_failure_is_logged_and_retry_pushes_existing_commit(self):
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\necho "Push rejected for test" >&2\nexit 1\n')
        hook.chmod(0o755)
        argv = ['ariadne.py', 'prepare-week', '--repo', str(self.root), '--date', '2026-10-05']
        with patch('sys.argv', argv), patch.object(ariadne, 'configure_logging'), \
                self.assertLogs('ariadne', level='INFO') as logs, \
                redirect_stdout(io.StringIO()) as stdout, self.assertRaises(SystemExit) as stopped:
            ariadne.main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(stdout.getvalue(), '')
        content = '\n'.join(logs.output)
        self.assertIn('Traceback (most recent call last)', content)
        self.assertIn('Push rejected for test', content)
        self.assertIn(str(self.root), content)
        head = self.git('rev-parse', 'HEAD')
        hook.unlink()
        self.prepare()
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.remote_ref(self.branch), head)
