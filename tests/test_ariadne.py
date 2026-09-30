import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import date

from ariadne import prepare_week, week_name


class WeekTests(unittest.TestCase):
    def test_iso_year_boundary(self):
        self.assertEqual(week_name(date(2021, 1, 1)), '2020_W53')
        self.assertEqual(week_name(date(2026, 9, 30)), '2026_W40')


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.root / 'README.md').write_text('Design\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Initial')
        self.base = self.git('rev-parse', 'HEAD')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def prepare(self):
        return prepare_week(self.root, date(2026, 9, 30))

    def test_creates_branch_directory_and_audit(self):
        result = self.prepare()
        self.assertEqual(self.git('branch', '--show-current'), 'ingress/2026_W40')
        self.assertTrue((self.root / 'ingress/2026_W40/.gitkeep').is_file())
        audit = json.loads((self.root / 'audit/2026_W40/ingress-preparation.json').read_text())
        self.assertEqual(audit, result)
        self.assertEqual(audit['base_commit'], self.base)
        self.assertEqual(audit['week'], '2026_W40')
        self.assertEqual(audit['ingress_path'], 'ingress/2026_W40')
        self.assertEqual(self.git('rev-parse', 'main'), self.base)

    def test_repeat_preserves_audit_and_sherlock_files(self):
        first = self.prepare()
        item = self.root / 'ingress/2026_W40/ingress_0001.md'
        item.write_text('Sherlock output\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Oogst')
        self.assertEqual(self.prepare(), first)
        self.assertEqual(item.read_text(), 'Sherlock output\n')

    def test_reuses_existing_local_week_branch(self):
        self.git('branch', 'ingress/2026_W40')
        self.prepare()
        self.assertEqual(self.git('branch', '--show-current'), 'ingress/2026_W40')

    def test_reuses_remote_week_without_resetting_it(self):
        self.git('checkout', '-b', 'remote-week')
        (self.root / 'existing.md').write_text('Existing harvest')
        self.git('add', '.')
        self.git('commit', '-m', 'Remote harvest')
        remote_head = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/ingress/2026_W40', remote_head)
        self.git('checkout', 'main')
        self.assertEqual(self.prepare()['base_commit'], remote_head)
        self.assertEqual((self.root / 'existing.md').read_text(), 'Existing harvest')

    def test_refuses_dirty_switch_without_changes(self):
        (self.root / 'README.md').write_text('Uncommitted')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.git('branch', '--show-current'), 'main')
        self.assertFalse((self.root / 'ingress').exists())

    def test_conflicting_audit_is_not_overwritten(self):
        self.prepare()
        path = self.root / 'audit/2026_W40/ingress-preparation.json'
        path.write_text('{"week": "wrong"}')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(path.read_text(), '{"week": "wrong"}')

    def test_checks_paths_on_existing_week_branch(self):
        self.git('checkout', '-b', 'ingress/2026_W40')
        (self.root / 'ingress').symlink_to('outside', target_is_directory=True)
        self.git('add', '.')
        self.git('commit', '-m', 'Symlink on target')
        self.git('checkout', 'main')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.root / 'audit').exists())

    def test_symlink_ingress_is_refused(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'ingress').symlink_to(outside, target_is_directory=True)
        self.git('add', '.')
        self.git('commit', '-m', 'Symlink')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
