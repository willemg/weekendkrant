"""Local CI invariants; Git integration uses a tiny local fixture, never a network."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import ci_runner as ci

A, B = 'a' * 40, 'b' * 40
ROOT = Path(__file__).resolve().parents[1]


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = ci.State(Path(self.tmp.name) / 'ci')

    def test_mark_idempotent_and_coalesces(self):
        self.state.mark(A)
        first = self.state.read()['pending']
        self.state.mark(A)
        self.assertEqual(self.state.read()['pending'], first)
        self.state.mark(B)
        self.assertEqual(self.state.read()['pending']['sha'], B)
        self.assertNotEqual(self.state.read()['pending']['request'], first['request'])

    def test_invalid_sha_and_checkout_state_rejected(self):
        for sha in ('main', '-x', 'a' * 39, A + ';false'):
            with self.assertRaises(ValueError):
                self.state.mark(sha)
        with self.assertRaises(ValueError):
            ci.State(ROOT / 'ci-state')
        with self.assertRaises(ValueError):
            ci.State(Path('/home/weekendkrant/app/ci-state'))

    def test_malformed_state_fails_closed(self):
        self.state.path.write_text('{broken')
        with self.assertRaises(ValueError):
            self.state.mark(A)
        self.assertEqual(self.state.path.read_text(), '{broken')

    def run_ci(self, work=None, notify=None):
        def success(sha, clone, python, source, fd, log):
            clone.mkdir()
            log.write(b'fixture stdout and stderr\n')
            if work:
                return work(clone)
            return 0
        with patch.object(ci, 'clone_test', side_effect=success):
            return ci.run(self.state, 'https://example.test/repo.git', sys.executable, notify)

    def test_idle_is_silent_and_does_not_clone(self):
        with patch.object(ci, 'clone_test') as task:
            self.assertEqual(ci.run(self.state, 'unused', sys.executable), 0)
        task.assert_not_called()
        self.assertFalse(self.state.read().get('last_result'))

    def test_success_clears_same_request_and_cleans(self):
        self.state.mark(A)
        self.assertEqual(self.run_ci(), 0)
        data = self.state.read()
        self.assertIsNone(data['pending'])
        self.assertEqual(data['last_result']['sha'], A)
        self.assertEqual(data['last_result']['status'], 'succeeded')
        self.assertEqual(data['last_result']['exitcode'], 0)
        self.assertEqual(list((self.state.root / 'work').iterdir()), [])
        self.state.mark(A)
        self.assertIsNone(self.state.read()['pending'])

    def test_new_sha_during_run_survives_success(self):
        self.state.mark(A)
        self.run_ci(lambda clone: (self.state.mark(B), 0)[1])
        self.assertEqual(self.state.read()['pending']['sha'], B)
        self.assertEqual(self.state.read()['last_result']['sha'], A)

    def test_forced_same_sha_during_run_survives_success(self):
        self.state.mark(A)
        self.run_ci(lambda clone: (self.state.mark(A, force=True), 0)[1])
        self.assertEqual(self.state.read()['pending']['sha'], A)

    def test_failure_diagnostics_and_no_hourly_retry_or_notification_spam(self):
        self.state.mark(A)
        messages = []
        self.assertEqual(self.run_ci(lambda clone: 7, messages.append), 7)
        data = self.state.read()
        self.assertEqual(data['pending']['sha'], A)
        self.assertEqual(data['last_failure']['exitcode'], 7)
        self.assertEqual(data['last_failure']['status'], 'failed')
        self.assertIn('stdout and stderr', data['last_failure']['log'])
        self.assertTrue(data['last_failure']['started_at'])
        self.assertTrue(data['last_failure']['finished_at'])
        self.assertEqual(len(messages), 1)
        self.assertIn(A[:12], messages[0])
        self.assertIn(str(self.state.path), messages[0])
        with patch.object(ci, 'clone_test') as task:
            self.assertEqual(ci.run(self.state, 'unused', sys.executable, messages.append), 0)
        task.assert_not_called()
        self.assertEqual(len(messages), 1)
        self.assertEqual(list((self.state.root / 'work').iterdir()), [])
        self.state.mark(A)
        self.assertEqual(self.state.read()['pending'], data['pending'])
        self.state.mark(A, force=True)
        self.assertEqual(self.run_ci(), 0)
        self.assertEqual(self.state.read()['last_failure'], data['last_failure'])

    def test_new_sha_after_failure_runs(self):
        self.state.mark(A)
        self.run_ci(lambda clone: 1)
        self.state.mark(B)
        self.assertEqual(self.run_ci(), 0)
        self.assertEqual(self.state.read()['last_result']['sha'], B)

    def test_notification_failure_does_not_change_test_failure(self):
        self.state.mark(A)
        def broken(message):
            raise OSError('offline')
        self.assertEqual(self.run_ci(lambda clone: 3, broken), 3)
        self.assertEqual(self.state.read()['last_result']['exitcode'], 3)
        self.assertEqual(self.state.read()['last_failure']['status'], 'failed')

    def test_exception_preserves_failure_and_cleans_clone(self):
        self.state.mark(A)
        def broken(clone):
            raise OSError('cannot start test process')
        self.assertNotEqual(self.run_ci(broken), 0)
        self.assertIn('cannot start', self.state.read()['last_failure']['log'])
        self.assertEqual(list((self.state.root / 'work').iterdir()), [])

    def test_busy_runner_is_nonblocking(self):
        self.state.mark(A)
        with (self.state.root / 'runner.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(ci, 'clone_test') as task:
                self.assertEqual(ci.run(self.state, 'unused', sys.executable), 0)
            task.assert_not_called()
        self.assertEqual(self.run_ci(), 0)

    def test_interrupted_running_request_is_retried_and_orphan_removed(self):
        self.state.mark(A)
        with self.state.edit() as data:
            data['last_result'] = dict(data['pending'], status='running')
        orphan = self.state.root / 'work' / 'run-interrupted'
        orphan.mkdir(parents=True)
        (orphan / 'partial').write_text('incomplete clone')
        self.assertEqual(self.run_ci(), 0)
        self.assertFalse(orphan.exists())

    def test_crash_before_result_commit_retries_instead_of_false_green(self):
        self.state.mark(A)
        with patch.object(self.state, 'finish', side_effect=OSError('crash before CAS')):
            with self.assertRaises(OSError):
                self.run_ci()
        self.assertEqual(self.state.read()['last_result']['status'], 'running')
        self.assertEqual(self.state.read()['pending']['sha'], A)
        self.assertEqual(self.run_ci(), 0)
        self.assertIsNone(self.state.read()['pending'])

    def test_output_and_state_are_bounded(self):
        log = ci.TailLog(self.state.root / 'current.log')
        log.write(b'x' * (ci.LOG_LIMIT * 3))
        self.assertLessEqual(len(log.tail), ci.LOG_LIMIT)
        self.assertLessEqual(log.path.stat().st_size, ci.LOG_LIMIT)

    def test_source_live_checkout_is_rejected_before_git(self):
        self.state.mark(A)
        with self.assertRaises(ValueError):
            ci.run(self.state, '/home/weekendkrant/app', sys.executable)
        self.assertEqual(self.state.read()['pending']['sha'], A)

    def test_cleanup_does_not_follow_work_symlink(self):
        target = Path(self.tmp.name) / 'unrelated'
        target.mkdir()
        (target / 'run-valuable').mkdir()
        (self.state.root / 'work').symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            ci.cleanup(self.state)
        self.assertTrue((target / 'run-valuable').exists())

    def test_cleanup_does_not_follow_orphan_symlink(self):
        target = Path(self.tmp.name) / 'unrelated'
        target.mkdir()
        work = self.state.root / 'work'
        work.mkdir()
        (work / 'run-link').symlink_to(target, target_is_directory=True)
        ci.cleanup(self.state)
        self.assertTrue(target.exists())
        self.assertFalse((work / 'run-link').exists())

    def test_bad_notification_configuration_is_best_effort(self):
        self.state.mark(A)
        with patch.dict(os.environ, {'WEEKENDKRANT_CI_NTFY_URL': 'bad-url'}):
            self.assertEqual(self.run_ci(lambda clone: 4, ci.ntfy_from_env()), 4)
        self.assertEqual(self.state.read()['last_failure']['exitcode'], 4)

    def test_ntfy_request_uses_timeout_and_optional_token(self):
        with patch.dict(os.environ, {'WEEKENDKRANT_CI_NTFY_URL': 'https://example.test/topic',
                                    'WEEKENDKRANT_CI_NTFY_TOKEN': 'fixture-token'}):
            with patch.object(ci, 'urlopen') as post:
                ci.ntfy_from_env()('fixture message')
        request = post.call_args.args[0]
        self.assertEqual(request.data, b'fixture message')
        self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-token')
        self.assertEqual(post.call_args.kwargs['timeout'], 10)


class GitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'ci@example.test')
        self.git('config', 'user.name', 'CI fixture')
        self.proof = self.root / 'proof'
        (self.repo / 'start_tests.sh').write_text(
            '#!/bin/bash\nset -eu\n[[ "$1" == "--all" ]]\n'
            'test -z "${WEEKENDKRANT_CI_STATE:-}"\n'
            'git rev-parse HEAD > "$CI_FIXTURE_PROOF"\n'
            'cat value >> "$CI_FIXTURE_PROOF"\n'
            'pwd >> "$CI_FIXTURE_PROOF"\n'
            'while [[ -n "${CI_FIXTURE_WAIT:-}" && ! -e "$CI_FIXTURE_WAIT" ]]; do sleep 0.01; done\n'
            'echo fixture-output\nexit "${CI_FIXTURE_EXIT:-0}"\n')
        (self.repo / 'value').write_text('A\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'A')
        self.a = self.git('rev-parse', 'HEAD')
        (self.repo / 'value').write_text('B\n')
        self.git('commit', '-qam', 'B')
        self.b = self.git('rev-parse', 'HEAD')
        self.state = ci.State(self.root / 'state')
        self.env = patch.dict(os.environ, {'CI_FIXTURE_PROOF': str(self.proof),
                                          'WEEKENDKRANT_CI_STATE': 'must-be-unset'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args],
                                       stderr=subprocess.PIPE, text=True).strip()

    def test_exact_sha_fresh_clones_and_source_untouched(self):
        (self.repo / 'value').write_text('dirty live-like source\n')
        before = self.git('status', '--porcelain')
        self.state.mark(self.a)
        self.assertEqual(ci.run(self.state, str(self.repo), sys.executable), 0)
        sha, value, path = self.proof.read_text().splitlines()
        self.assertEqual((sha, value), (self.a, 'A'))
        self.assertFalse(Path(path).exists())
        first = path
        self.state.mark(self.b)
        self.assertEqual(ci.run(self.state, str(self.repo), sys.executable), 0)
        self.assertNotEqual(first, self.proof.read_text().splitlines()[2])
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertEqual((self.repo / 'value').read_text(), 'dirty live-like source\n')

    def test_inherited_git_directory_cannot_redirect_checkout(self):
        self.state.mark(self.a)
        original_head = self.git('rev-parse', 'HEAD')
        with patch.dict(os.environ, {'GIT_DIR': str(self.repo / '.git'),
                                     'GIT_WORK_TREE': str(self.repo)}):
            result = ci.run(self.state, str(self.repo), sys.executable)
        self.assertEqual(self.git('rev-parse', 'HEAD'), original_head)
        self.assertEqual((self.repo / 'value').read_text(), 'B\n')
        self.assertEqual(result, 0)

    def test_real_test_failure_and_cleanup(self):
        self.state.mark(self.a)
        with patch.dict(os.environ, {'CI_FIXTURE_EXIT': '9'}):
            self.assertEqual(ci.run(self.state, str(self.repo), sys.executable), 9)
        self.assertIn('fixture-output', self.state.read()['last_failure']['log'])
        self.assertFalse(Path(self.proof.read_text().splitlines()[2]).exists())

    def test_clone_and_missing_commit_fail_without_false_green(self):
        for source, sha in ((str(self.root / 'missing'), self.a), (str(self.repo), A)):
            with self.subTest(source=source):
                self.state.mark(sha, force=True)
                self.assertNotEqual(ci.run(self.state, source, sys.executable), 0)
                self.assertEqual(self.state.read()['last_result']['status'], 'failed')
                self.assertEqual(self.state.read()['pending']['sha'], sha)
                self.assertEqual(list((self.state.root / 'work').iterdir()), [])

    def test_dirty_checkout_cannot_be_marked_and_older_trigger_cannot_replace_newer(self):
        ci.mark_checkout(self.state, self.repo, self.b)
        self.git('checkout', '--detach', self.a)
        ci.mark_checkout(self.state, self.repo, self.a)
        self.assertEqual(self.state.read()['pending']['sha'], self.b)
        (self.repo / 'value').write_text('dirty')
        with self.assertRaises(ValueError):
            ci.mark_checkout(self.state, self.repo, self.a)

    def test_killed_parent_keeps_child_lock_until_exit_then_recovers(self):
        self.state.mark(self.a)
        release = self.root / 'release'
        env = dict(os.environ, CI_FIXTURE_WAIT=str(release))
        child = subprocess.Popen([sys.executable, str(ROOT / 'ci_runner.py'),
                                  '--state', str(self.state.root), 'run',
                                  '--source', str(self.repo), '--python', sys.executable],
                                 env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not self.proof.exists() and time.monotonic() < deadline:
                if child.poll() is not None:
                    self.fail(child.stderr.read().decode())
                time.sleep(0.01)
            self.assertTrue(self.proof.exists())
            child.kill()
            child.wait(timeout=5)
            with ci.runner_lock(self.state) as fd:
                self.assertIsNone(fd, 'orphan test process must retain the lock')
            release.touch()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with ci.runner_lock(self.state) as fd:
                    if fd is not None:
                        break
                time.sleep(0.01)
            else:
                self.fail('child did not release runner lock')
            self.assertEqual(self.state.read()['last_result']['status'], 'running')
            self.assertEqual(ci.run(self.state, str(self.repo), sys.executable), 0)
            self.assertEqual(list((self.state.root / 'work').iterdir()), [])
        finally:
            release.touch()
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stderr.close()


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'app'
        self.repo.mkdir()
        for name in ('test_runner.py', 'start_tests.sh', 'ci_runner.py'):
            shutil.copyfile(ROOT / name, self.repo / name)
        (self.repo / 'tests').mkdir()
        (self.repo / 'tests/fast_track.txt').write_text('test_tiny\n')
        (self.repo / 'tests/test_tiny.py').write_text(
            'import unittest\nclass Tiny(unittest.TestCase):\n'
            ' def test_ok(self): pass\n')
        (self.repo / '.gitignore').write_text('__pycache__/\n')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        for args in (('config', 'user.email', 'ci@example.test'),
                     ('config', 'user.name', 'CI'), ('add', '.'), ('commit', '-qm', 'fixture')):
            subprocess.run(['git', '-C', str(self.repo), *args], check=True)
        self.state = self.root / 'state'

    def invoke(self, *args):
        env = dict(os.environ, WEEKENDKRANT_CI_STATE=str(self.state),
                   WEEKENDKRANT_TEST_PYTHON=sys.executable)
        return subprocess.run(['bash', './start_tests.sh', *args], cwd=self.repo,
                              env=env, capture_output=True, text=True)

    def test_cron_wrapper_loads_config_and_runs_outside_checkout(self):
        installed = self.root / 'bin'
        installed.mkdir()
        shutil.copyfile(ROOT / 'start_ci.sh', installed / 'start_ci.sh')
        shutil.copyfile(ROOT / 'ci_runner.py', installed / 'ci_runner.py')
        self.state.mkdir()
        config = self.root / 'env'
        config.write_text(f'WEEKENDKRANT_CI_STATE={self.state}\n'
                          f'WEEKENDKRANT_CI_PYTHON={sys.executable}\n')
        result = subprocess.run(['bash', str(installed / 'start_ci.sh')], cwd=self.repo,
                                env=dict(os.environ, WEEKENDKRANT_CI_CONFIG=str(config)),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIsNone(ci.State(self.state).read()['pending'])

    def test_successful_clean_fasttrack_marks_exact_head(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.state / 'state.json').read_text())
        sha = subprocess.check_output(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], text=True).strip()
        self.assertEqual(data['pending']['sha'], sha)

    def test_failed_fasttrack_never_marks(self):
        (self.repo / 'tests/test_tiny.py').write_text(
            'import unittest\nclass Tiny(unittest.TestCase):\n'
            ' def test_bad(self): self.fail("fixture failure")\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', 'failing fixture'], check=True)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse((self.state / 'state.json').exists())

    def test_dirty_fasttrack_passes_but_reports_no_trigger(self):
        (self.repo / 'untracked').write_text('work in progress')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CI niet gemarkeerd', result.stderr)
        self.assertFalse((self.state / 'state.json').exists())

    def test_explicit_full_fixture_does_not_retrigger(self):
        result = self.invoke('--all')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.state / 'state.json').exists())

    def test_checkout_changed_during_green_tests_is_not_marked(self):
        (self.repo / 'tests/test_tiny.py').write_text(
            'import unittest\nfrom pathlib import Path\nclass Tiny(unittest.TestCase):\n'
            ' def test_change(self): Path("changed-during-tests").touch()\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', 'mutation fixture'], check=True)
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('CI trigger failed', result.stderr)
        self.assertFalse((self.state / 'state.json').exists())

    def test_unwritable_or_invalid_trigger_state_fails_visibly_after_tests(self):
        self.state.write_text('not a directory')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('CI trigger failed', result.stderr)
