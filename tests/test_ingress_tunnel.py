import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from ingress_tunnel import (TunnelError, URLDetector, discovery_json,
                            publish_endpoint, supervise)

URL = 'https://calm-small-test.trycloudflare.com'


class DetectionTests(unittest.TestCase):
    def test_valid_log_and_exactly_one_suffix(self):
        detector = URLDetector()
        self.assertEqual(detector.feed('| Your tunnel: ' + URL + ' |'), URL + '/ingress')
        self.assertEqual(detector.feed(URL + '/ingress'), URL + '/ingress')
        self.assertEqual(detector.feed('ordinary log'), URL + '/ingress')

    def test_invalid_urls(self):
        for url in ['http://calm.trycloudflare.com', 'https://evil.example',
                    'https://bad_host.trycloudflare.com', 'https://-bad.trycloudflare.com',
                    'https://a.b.trycloudflare.com', 'https://user@calm.trycloudflare.com',
                    URL + ':443', URL + '?x=1', URL + '#x', URL + '/other',
                    URL + '.evil.example', 'https://trycloudflare.com']:
            with self.subTest(url=url), self.assertRaises(TunnelError):
                URLDetector().feed(url)

    def test_conflicting_urls(self):
        detector = URLDetector()
        detector.feed(URL)
        with self.assertRaises(TunnelError):
            detector.feed('https://different.trycloudflare.com')

    def test_conflicting_same_line(self):
        with self.assertRaises(TunnelError):
            URLDetector().feed(URL + ' https://different.trycloudflare.com')

    def test_unrelated_cloudflare_help_link(self):
        self.assertIsNone(URLDetector().feed('See https://developers.cloudflare.com/cloudflare-one/'))

    def test_serialization(self):
        self.assertEqual(discovery_json(URL + '/ingress'),
                         '{"url":"' + URL + '/ingress"}\n')


class ProcessTests(unittest.TestCase):
    def process(self, lines, status=0):
        process = Mock()
        process.stdout = io.StringIO(lines)
        process.poll.return_value = None
        process.wait.return_value = status
        return process

    def test_publish_then_keep_reading_and_exit_is_error(self):
        process = self.process(URL + '\nordinary log\n', 7)
        publisher = Mock()
        with self.assertRaisesRegex(TunnelError, '7'):
            supervise(process, publisher, timeout=1)
        publisher.assert_called_once_with(URL + '/ingress')

    def test_exit_before_url_including_zero(self):
        for code in (0, 8):
            with self.subTest(code=code), self.assertRaisesRegex(TunnelError, str(code)):
                supervise(self.process('no URL\n', code), Mock(), timeout=1)

    def test_timeout(self):
        with patch('ingress_tunnel.read_output', return_value=None):
            with self.assertRaisesRegex(TunnelError, 'timeout'):
                supervise(self.process(''), Mock(), timeout=0.01)

    def test_conflict_after_publication(self):
        with self.assertRaises(TunnelError):
            supervise(self.process(URL + '\nhttps://other.trycloudflare.com\n'), Mock(), timeout=1)

    def test_publication_error_propagates(self):
        publisher = Mock(side_effect=TunnelError('push'))
        with self.assertRaisesRegex(TunnelError, 'push'):
            supervise(self.process(URL + '\n'), publisher, timeout=1)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        self.app = self.root / 'app'
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        self.git('init', '--bare', str(self.remote))
        self.git('clone', str(self.remote), str(self.app))
        self.git('-C', str(self.app), 'checkout', '-b', 'main')
        (self.app / 'keep.txt').write_text('keep\n')
        self.git('-C', str(self.app), 'add', '.')
        self.git('-C', str(self.app), '-c', 'user.name=Test', '-c', 'user.email=test@example.org',
                 'commit', '-m', 'Initial')
        self.git('-C', str(self.app), 'push', 'origin', 'main')
        (self.app / 'keep.txt').write_text('local uncommitted\n')
        self.before = self.snapshot()

    def git(self, *args):
        return subprocess.check_output(['git', *args], stderr=subprocess.STDOUT, text=True).strip()

    def snapshot(self):
        return (self.git('-C', str(self.app), 'rev-parse', 'HEAD'),
                self.git('-C', str(self.app), 'status', '--porcelain'),
                self.git('-C', str(self.app), 'worktree', 'list', '--porcelain'),
                (self.app / 'keep.txt').read_bytes())

    def publish(self):
        return publish_endpoint(str(self.remote), URL + '/ingress', temp_root=str(self.scratch))

    def test_one_commit_and_push_only_changed_file_then_noop(self):
        before = self.git('--git-dir', str(self.remote), 'rev-parse', 'main')
        self.assertTrue(self.publish())
        after = self.git('--git-dir', str(self.remote), 'rev-parse', 'main')
        self.assertEqual(self.git('--git-dir', str(self.remote), 'rev-parse', 'main^'), before)
        self.assertEqual(self.git('--git-dir', str(self.remote), 'diff-tree', '--no-commit-id',
                                  '--name-only', '-r', after), 'config/ingress-endpoint.json')
        self.assertEqual(self.git('--git-dir', str(self.remote), 'show',
                                  'main:config/ingress-endpoint.json') + '\n', discovery_json(URL + '/ingress'))
        self.assertFalse(self.publish())
        self.assertEqual(self.git('--git-dir', str(self.remote), 'rev-parse', 'main'), after)
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_changed_url_creates_exactly_one_more_commit(self):
        self.publish()
        before = self.git('--git-dir', str(self.remote), 'rev-parse', 'main')
        changed = 'https://new-tunnel.trycloudflare.com/ingress'
        self.assertTrue(publish_endpoint(str(self.remote), changed, temp_root=str(self.scratch)))
        self.assertEqual(self.git('--git-dir', str(self.remote), 'rev-parse', 'main^'), before)
        self.assertEqual(self.git('--git-dir', str(self.remote), 'show',
                                  'main:config/ingress-endpoint.json') + '\n', discovery_json(changed))
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_clone_failure_cleans_temp_directory(self):
        with self.assertRaises(TunnelError):
            publish_endpoint(str(self.root / 'missing.git'), URL, temp_root=str(self.scratch))
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(self.snapshot(), self.before)

    def test_failure_cleanup_and_no_force_or_worktree(self):
        import ingress_tunnel
        real = ingress_tunnel.run_git
        commands = []
        def fail_push(args, **kwargs):
            commands.append(args)
            if 'push' in args:
                raise TunnelError('push rejected')
            return real(args, **kwargs)
        with patch('ingress_tunnel.run_git', side_effect=fail_push):
            with self.assertRaisesRegex(TunnelError, 'push rejected'):
                self.publish()
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(self.snapshot(), self.before)
        for args in commands:
            self.assertNotIn('--force', args)
            self.assertNotIn('rebase', args)
            self.assertNotIn('worktree', args)
        push = next(args for args in commands if 'push' in args)
        self.assertEqual(push[-2:], ['origin', 'HEAD:refs/heads/main'])

    def test_concurrent_main_update_rejected_without_losing_remote_change(self):
        import ingress_tunnel
        real = ingress_tunnel.run_git
        def advance(args, **kwargs):
            if 'push' in args:
                self.git('-C', str(self.app), 'add', 'keep.txt')
                self.git('-C', str(self.app), '-c', 'user.name=Test', '-c', 'user.email=test@example.org',
                         'commit', '-m', 'Concurrent change')
                self.git('-C', str(self.app), 'push', 'origin', 'main')
            return real(args, **kwargs)
        with patch('ingress_tunnel.run_git', side_effect=advance), self.assertRaises(TunnelError):
            self.publish()
        self.assertEqual(self.git('--git-dir', str(self.remote), 'show', 'main:keep.txt'), 'local uncommitted')
        self.assertEqual(list(self.scratch.iterdir()), [])


class LifecycleTests(unittest.TestCase):
    def test_malformed_bracket_host_is_controlled_error(self):
        with self.assertRaises(TunnelError):
            URLDetector().feed('https://[bad.trycloudflare.com')

    def test_signal_stops_child_and_returns_success(self):
        import ingress_tunnel
        process = Mock()
        process.poll.return_value = None
        handlers = {}
        def register(sig, handler):
            handlers[sig] = handler
            return None
        def signal_during_supervision(*args):
            handlers[ingress_tunnel.signal.SIGTERM](15, None)
        with patch('ingress_tunnel.signal.signal', side_effect=register), \
             patch('ingress_tunnel.subprocess.Popen', return_value=process) as popen, \
             patch('ingress_tunnel.supervise', side_effect=signal_during_supervision):
            self.assertEqual(ingress_tunnel.main(['--cloudflared', '/custom/cloudflared']), 0)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)
        self.assertEqual(popen.call_args.args[0],
                         ['/custom/cloudflared', 'tunnel', '--url', 'http://127.0.0.1:8000'])

    def test_force_kill_only_when_child_does_not_terminate(self):
        from ingress_tunnel import stop_child
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('cloudflared', 10), 0]
        stop_child(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    def test_error_stops_child_and_nonzero_exit(self):
        import ingress_tunnel
        process = Mock()
        process.poll.return_value = None
        with patch('ingress_tunnel.subprocess.Popen', return_value=process), \
             patch('ingress_tunnel.supervise', side_effect=TunnelError('early exit 9')):
            self.assertEqual(ingress_tunnel.main([]), 1)
        process.terminate.assert_called_once()

    def test_child_environment_contains_no_secret_or_git_override(self):
        from ingress_tunnel import child_environment
        with patch.dict('os.environ', {'WEEKENDKRANT_INGRESS_TOKEN': 'fictional',
                                       'GIT_DIR': '/must-not-use', 'GIT_WORK_TREE': '/app'}):
            env = child_environment()
        self.assertNotIn('WEEKENDKRANT_INGRESS_TOKEN', env)
        self.assertNotIn('GIT_DIR', env)
        self.assertNotIn('GIT_WORK_TREE', env)
