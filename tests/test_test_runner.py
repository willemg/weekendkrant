"""Exercise the CLI against isolated manifests and real unittest modules."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copyfile(
            Path(__file__).resolve().parents[1] / "test_runner.py", self.root / "test_runner.py"
        )
        self.tests = self.root / "tests"
        self.tests.mkdir()
        self.manifest = self.tests / "fast_track.txt"
        self.manifest.write_text("test_alpha\n", encoding="utf-8")
        (self.tests / "test_alpha.py").write_text("""import unittest
class AlphaTests(unittest.TestCase):
    def test_first(self): print('RAN_ALPHA_FIRST')
    def test_second(self): print('RAN_ALPHA_SECOND')
""")
        (self.tests / "test_beta.py").write_text("""import unittest
class BetaTests(unittest.TestCase):
    def test_beta(self): print('RAN_BETA')
""")
        (self.tests / "test_empty.py").write_text("# No tests\n")

    def run_cli(self, *args):
        # Selection fixtures deliberately exclude the optional deployment trigger.
        env = os.environ.copy()
        env.pop("WEEKENDKRANT_CI_STATE", None)
        return subprocess.run(
            [sys.executable, str(self.root / "test_runner.py"), *args],
            cwd=self.tmp.name,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_parent_ci_trigger_is_not_inherited_by_selection_fixture(self):
        self.manifest.write_text("test_environment\n")
        (self.tests / "test_environment.py").write_text("""import os
import unittest
class EnvironmentTests(unittest.TestCase):
    def test_child_environment(self):
        self.assertNotIn('WEEKENDKRANT_CI_STATE', os.environ)
        print('CHILD_CI_TRIGGER_ABSENT')
""")
        with patch.dict(os.environ):
            os.environ.pop("WEEKENDKRANT_CI_STATE", None)
            baseline = self.run_cli()
        with patch.dict(os.environ, {"WEEKENDKRANT_CI_STATE": "/home/weekendkrant/ci"}):
            inherited = self.run_cli()
            self.assertEqual(os.environ["WEEKENDKRANT_CI_STATE"], "/home/weekendkrant/ci")
        for result in (baseline, inherited):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CHILD_CI_TRIGGER_ABSENT", result.stdout)
        self.assertEqual(baseline.stdout, inherited.stdout)
        self.assertFalse((self.root / "ci_runner.py").exists())

    def test_explicit_module_and_comments_select_only_listed_tests(self):
        self.manifest.write_text("# Chosen impact\n\ntest_alpha # two cases\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Selected 1 modules, 2 tests", result.stdout)
        self.assertIn("test_alpha", result.stdout)
        self.assertIn("RAN_ALPHA_SECOND", result.stdout)
        self.assertNotIn("RAN_BETA", result.stdout)

    def test_individual_case_and_next_pr_list_change(self):
        self.manifest.write_text("test_alpha.AlphaTests.test_first\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Selected 1 modules, 1 tests", result.stdout)
        self.assertNotIn("RAN_ALPHA_SECOND", result.stdout)
        self.manifest.write_text("test_beta\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RAN_BETA", result.stdout)
        self.assertNotIn("RAN_ALPHA", result.stdout)

    def test_empty_or_comment_only_list_fails(self):
        for content in ("", "# No selection\n\n"):
            with self.subTest(content=content):
                self.manifest.write_text(content)
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("empty", result.stderr.lower())

    def test_missing_manifest_fails(self):
        self.manifest.unlink()
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_invalid_deleted_empty_and_overlapping_entries_fail_before_execution(self):
        for entry in (
            "not_a_test",
            "../test_alpha",
            "test_deleted",
            "test_alpha.AlphaTests.test_deleted",
            "test_alpha.DeletedTests",
            "test_empty",
            "test_alpha",
            "test_alpha.AlphaTests.test_first",
        ):
            with self.subTest(entry=entry):
                self.manifest.write_text("test_alpha\n" + entry + "\n")
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("RAN_ALPHA", result.stdout)

    def test_import_error_fails_before_execution(self):
        (self.tests / "test_broken.py").write_text("import nonexistent_dependency\n")
        self.manifest.write_text("test_alpha\ntest_broken\n")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("RAN_ALPHA", result.stdout)

    def test_all_ignores_manifest_and_runs_complete_suite(self):
        self.manifest.write_text("invalid-entry")
        result = self.run_cli("--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Selected 2 modules, 3 tests", result.stdout)
        self.assertIn("RAN_ALPHA_FIRST", result.stdout)
        self.assertIn("RAN_BETA", result.stdout)

    def test_all_cannot_silently_run_zero_tests(self):
        for path in self.tests.glob("test_*.py"):
            path.unlink()
        self.assertNotEqual(self.run_cli("--all").returncode, 0)

    def test_unknown_argument_fails(self):
        result = self.run_cli("--bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_failing_test_propagates_failure(self):
        (self.tests / "test_beta.py").write_text("""import unittest
class BetaTests(unittest.TestCase):
    def test_beta(self): self.fail('expected failure')
""")
        self.manifest.write_text("test_beta\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("expected failure", result.stderr)

    def test_selection_is_identical_without_git_on_clean_main_and_dirty_branch(self):
        no_git = self.run_cli()

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE
            ).strip()

        git("init", "-b", "main")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        git("add", ".")
        git("commit", "-m", "persisted list")
        self.assertEqual(git("status", "--porcelain"), "")
        clean = self.run_cli()
        self.assertEqual(git("status", "--porcelain"), "")
        git("switch", "-c", "next-pr")
        (self.root / "unrelated.txt").write_text("staged")
        git("add", "unrelated.txt")
        (self.root / "other.txt").write_text("untracked")
        dirty = self.run_cli()
        for result in (no_git, clean, dirty):
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(no_git.stdout, clean.stdout)
        self.assertEqual(clean.stdout, dirty.stdout)
