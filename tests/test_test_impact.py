"""Impact selection is tested on tiny repositories, not this PR's file names."""

import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_impact


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        for name, text in {
            "a.py": "VALUE=1",
            "b.py": "import a",
            "c.py": "VALUE=2",
            "tests/test_a.py": "import a",
            "tests/test_b.py": "from b import VALUE",
            "tests/test_c.py": "import c",
        }.items():
            self.put(name, text)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def select(self, *files):
        return test_impact.select(self.root, files)

    def test_changed_test_only(self):
        self.assertEqual(set(self.select("tests/test_c.py")), {"tests/test_c.py"})

    def test_direct_and_transitive(self):
        self.assertEqual(set(self.select("a.py")), {"tests/test_a.py", "tests/test_b.py"})
        self.assertIn("a.py", self.select("a.py")["tests/test_b.py"])

    def test_multiple_files(self):
        self.assertEqual(len(self.select("a.py", "c.py")), 3)

    def test_documentation_has_no_impact(self):
        self.assertEqual(self.select("docs/notes.md"), {})

    def test_broad_changes(self):
        for name in (
            "database.py",
            "migrations/011.sql",
            "requirements.txt",
            "start_tests.sh",
            "test_impact.py",
            "config/runtime.json",
        ):
            self.assertEqual(len(self.select(name)), 3, name)

    def test_unknown_deleted_or_dynamic_falls_back(self):
        self.assertEqual(len(self.select("new.py")), 3)
        self.put("a.py", "__import__(module_name)")
        self.assertEqual(len(self.select("c.py")), 3)
        self.put("a.py", "invalid python !")
        self.assertEqual(len(self.select("c.py")), 3)

    def test_uncovered_production_never_zero(self):
        self.put("isolated.py", "VALUE=3")
        self.assertEqual(len(self.select("isolated.py")), 3)

    def test_literal_dynamic_import_and_component_boundary(self):
        self.put("b.py", '__import__("a")')
        self.assertIn("tests/test_b.py", self.select("a.py"))
        self.put("jobs.py", "VALUE=1")
        self.put("tests/test_jobs.py", "import jobs")
        self.put("tests/test_system_e2e.py", "VALUE=2")
        selected = self.select("jobs.py")
        self.assertIn("tests/test_system_e2e.py", selected)
        self.assertIn("boundary", selected["tests/test_system_e2e.py"])

    def test_executable_documentation_broadens_mixed_changes(self):
        self.assertEqual(len(self.select("c.py", "docs/agents/leonardo.md")), 3)

    def test_merge_base_includes_branch_worktree_and_untracked_not_main(self):
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

        git("init", "-b", "main")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        git("add", ".")
        git("commit", "-m", "base")
        git("switch", "-c", "feature")
        self.put("a.py", "VALUE=4")
        git("commit", "-am", "feature")
        git("switch", "main")
        self.put("main_only.py", "VALUE=5")
        git("add", ".")
        git("commit", "-m", "advanced main")
        git("switch", "feature")
        self.put("c.py", "VALUE=6")
        self.put("new.py", "VALUE=7")
        self.assertEqual(set(test_impact.changed_files(self.root)), {"a.py", "c.py", "new.py"})

    def test_cli_all_unknown_and_diff_failure(self):
        with patch("test_impact.run", return_value=0) as run:
            self.assertEqual(test_impact.main(["--all"], self.root), 0)
            self.assertEqual(len(run.call_args.args[1]), 3)
        with self.assertRaises(SystemExit):
            test_impact.main(["--bogus"], self.root)
        with (
            patch("test_impact.changed_files", side_effect=RuntimeError("no git")),
            patch("test_impact.run", return_value=0) as run,
        ):
            self.assertEqual(test_impact.main([], self.root), 0)
            self.assertTrue(all("fallback" in r for r in run.call_args.args[1].values()))
