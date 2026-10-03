from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import ariadne
from test_prepare_week_runtime import RuntimeGitFixture


class PorcelainTests(unittest.TestCase):
    def record(self, path):
        return f'worktree {path}\nHEAD {"a" * 40}\nbranch refs/heads/main\n'

    def test_plain_and_git_c_quoted_paths(self):
        for encoded, expected in (
            ('/tmp/app with spaces', '/tmp/app with spaces'),
            ('"/tmp/quoted space"', '/tmp/quoted space'),
            (r'"/tmp/quote\"slash\\tab\tline\n"', '/tmp/quote"slash\\tab\tline\n'),
            (r'"/tmp/Brugge-\303\251"', '/tmp/Brugge-é'),
            ('/tmp/Brugge-é', '/tmp/Brugge-é'),
            (r'"/tmp/\a\b\v\f\r"', '/tmp/\a\b\v\f\r'),
            ('/tmp/$(touch sentinel)', '/tmp/$(touch sentinel)'),
        ):
            with self.subTest(path=encoded):
                self.assertEqual(ariadne.parse_worktree_porcelain(self.record(encoded))[0]['worktree'], expected)

    def test_multiple_records_and_safety_flags(self):
        raw = self.record('/tmp/app') + '\n' + self.record('/tmp/weekworktree') + 'locked why\nprunable missing\n\n'
        records = ariadne.parse_worktree_porcelain(raw)
        self.assertEqual(len(records), 2)
        self.assertIn('locked', records[1])
        self.assertIn('prunable', records[1])

    def test_ambiguous_or_malformed_output_is_refused(self):
        good = self.record('/tmp/app')
        for raw in ('', 'HEAD abc\n', good + 'unknown value\n', good + 'branch refs/heads/other\n',
                    good + self.record('/tmp/other'), good + '\n' + good,
                    self.record('relative'), self.record(r'"/tmp/bad\q"'),
                    self.record('"/tmp/unclosed'), self.record(r'"/tmp/\000"'),
                    self.record(r'"/tmp/\400"'), good.replace('a' * 40, 'no-sha'),
                    good + 'detached\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                ariadne.parse_worktree_porcelain(raw)


class Git230CompatibilityTests(RuntimeGitFixture):
    def test_git_without_z_option_is_supported(self):
        real = ariadne._git
        def git230(root, *args, **kwargs):
            if args[:2] == ('worktree', 'list') and '-z' in args:
                raise ValueError("git worktree list: error: unknown switch `z'")
            return real(root, *args, **kwargs)
        with patch.object(ariadne, '_git', side_effect=git230):
            self.prepare()
            managed, record = ariadne.inspect_worktrees(self.root)
            self.assertEqual(managed, self.weekroot)
            self.assertEqual(record['branch'], 'refs/heads/' + self.branch)

    def test_real_inventory_handles_spaces_quotes_and_unicode(self):
        moved = self.root.parent / 'app space " é'
        self.root.rename(moved)
        self.root = moved
        self.prepare()
        self.assertEqual(ariadne.inspect_worktrees(self.root)[0], self.weekroot)

    def test_missing_registered_worktree_is_not_pruned(self):
        self.prepare()
        shutil.rmtree(self.weekroot)
        with self.assertRaisesRegex(ValueError, 'ontbrekende'):
            ariadne.inspect_worktrees(self.root)
        self.assertEqual(self.git('worktree', 'list', '--porcelain').count('worktree '), 2)
