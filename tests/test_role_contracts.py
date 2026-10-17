"""Runtime files are creation inputs; durable jobs own their contract bytes."""
from datetime import datetime, timezone, timedelta
import sqlite3
import ast
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dispatcher import Dispatcher
from job_control import JobControl
import test_dispatcher
import test_leonardo
import test_parts
from leonardo import LeonardoStore

ROOT = Path(__file__).resolve().parents[1]


def assert_contracts(test, claim, role, output):
    for key, content in (("role_contract", role), ("output_contract", output)):
        test.assertEqual(claim[key], content.decode("utf-8"))
        test.assertEqual(claim[key + "_ref"], "sha256:" + hashlib.sha256(content).hexdigest())


class ContractFiles:
    def files(self, module, name):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "roles").mkdir()
        self.role = root / "roles" / (name + ".md")
        self.output = root / "roles" / (name + "-output.md")
        self.patch_root = patch(module + ".ROOT", root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.original = ("Rol é\r\nexact ".encode(), b"Output\r\nexact")
        self.write(*self.original)

    def write(self, role, output):
        self.role.write_bytes(role)
        self.output.write_bytes(output)

    def recover(self, db, now, claim):
        JobControl(db, lambda: now).execute("reconcile", dict(
            operation_id="recover:files", job_id=claim["job_id"],
            attempt_id=claim["attempt_id"], decision="retry", evidence_ref="audit:stopped"))


# Reuse fixture setup/helpers without inheriting their test methods.
class SherlockContracts(ContractFiles, unittest.TestCase):
    setUp = test_dispatcher.DispatcherTests.setUp
    start = test_dispatcher.DispatcherTests.start
    finish = test_dispatcher.DispatcherTests.finish
    policy = test_dispatcher.DispatcherTests.policy

    def test_creation_snapshot_recovery_replay_and_future_version(self):
        from sherlock_executor import SherlockProducer
        self.files("sherlock_executor", "sherlock")
        dispatcher = Dispatcher(self.db, lambda: self.now, (SherlockProducer,))
        first = self.start(dispatcher=dispatcher)
        assert_contracts(self, first, *self.original)
        self.write(b"new role", b"new output")
        self.finish(first, "uncertain")
        self.recover(self.db, self.now, first)
        # Neither missing nor malformed deploymentfiles may affect ready bind/replay.
        self.role.unlink()
        self.output.write_bytes(b"\xff")
        with patch("role_contracts.load_contract", side_effect=AssertionError("file IO")):
            recovered = self.start("recovered", dispatcher)
            assert_contracts(self, recovered, *self.original)
            self.assertEqual(self.start("recovered", dispatcher), recovered)
        self.finish(recovered)
        self.write(b"new role", b"new output")
        self.now += timedelta(hours=31)
        next_claim = self.start("next", dispatcher)
        assert_contracts(self, next_claim, b"new role", b"new output")

    def test_admission_refusal_never_reads_files(self):
        from sherlock_executor import SherlockProducer
        self.files("sherlock_executor", "sherlock")
        dispatcher = Dispatcher(self.db, lambda: self.now, (SherlockProducer,))
        self.role.unlink()
        self.policy(paused=1)
        with patch("role_contracts.load_contract", side_effect=AssertionError("file IO")):
            self.assertEqual(self.start(dispatcher=dispatcher), {"claim": None})
        self.policy(paused=0)
        # Actual new production must read the missing file and fail without a receipt.
        with self.assertRaises(FileNotFoundError):
            self.start("new", dispatcher)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_running_and_blocked_admission_never_reads_files(self):
        from sherlock_executor import SherlockProducer
        from jobs import JobStore
        for mode in ("running", "blocked"):
            with self.subTest(mode=mode), sqlite3.connect(":memory:") as db:
                dispatcher = Dispatcher(db, lambda: self.now, (SherlockProducer,))
                store = JobStore(db, lambda: self.now)
                job = store.create("Other", [], "output:other")
                claim = store.claim(job, "other")
                if mode == "blocked":
                    store.finish(claim, "uncertain", [])
                with patch("role_contracts.load_contract", side_effect=AssertionError("file IO")):
                    args = dict(operation_id="start:refused", activation_id="refused")
                    self.assertEqual(dispatcher.start(args), {"claim": None})
                    self.assertEqual(dispatcher.start(args), {"claim": None})

    def test_new_production_rejects_invalid_files(self):
        from sherlock_executor import SherlockProducer
        self.files("sherlock_executor", "sherlock")
        dispatcher = Dispatcher(self.db, lambda: self.now, (SherlockProducer,))
        for data in (b"\xff", b" ", b"x" * 65537):
            with self.subTest(data=data[:10]):
                self.role.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.start(dispatcher=dispatcher)
                self.assertEqual(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)


class LeonardoContracts(ContractFiles, test_parts.PartFixture):
    def setUp(self):
        super().setUp()
        self.add()
        self.run_day()
        self.conn = sqlite3.connect(self.db)
        self.addCleanup(self.conn.close)
        self.now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
        self.store = LeonardoStore(self.conn, lambda: self.now)
        self.store.create_dossier("dossier:reproduction", 2)
        self.part = self.conn.execute("SELECT id,active_revision FROM parts").fetchone()

    enqueue = test_leonardo.LeonardoTests.enqueue
    start = test_leonardo.LeonardoTests.start
    state = test_leonardo.LeonardoTests.state
    finish = test_leonardo.LeonardoTests.finish

    def test_creation_snapshot_recovery_replay_and_future_version(self):
        self.files("leonardo", "leonardo")
        job = self.enqueue()
        self.write(b"new role", b"new output")
        first = self.start()
        assert_contracts(self, first, *self.original)
        self.assertEqual(first["input"]["role_contract"], first["role_contract"])
        self.assertEqual(first["input"]["output_contract"], first["output_contract"])
        self.role.unlink()
        self.output.write_bytes(b"\xff")
        with patch("role_contracts.load_contract", side_effect=AssertionError("file IO")):
            self.assertEqual(self.enqueue(), job)
            self.assertEqual(self.start(), first)
            self.now += timedelta(hours=2)
            self.assertEqual(self.start("expire"), {"claim": None})
            self.recover(self.conn, self.now, first)
            recovered = self.start("retry")
            assert_contracts(self, recovered, *self.original)
            self.finish(recovered)
        self.write(b"new role", b"new output")
        self.store.enqueue("prepare:next", "dossier:reproduction", 1, [list(self.part)])
        assert_contracts(self, self.start("next"), b"new role", b"new output")

    def test_bad_contracts_leave_no_job_or_assignment(self):
        self.files("leonardo", "leonardo")
        for data in (b"\xff", b" ", b"x" * 65537):
            with self.subTest(data=data[:10]):
                self.role.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.enqueue()
                self.assertEqual(self.conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
                self.assertEqual(self.conn.execute("SELECT count(*) FROM leonardo_assignments").fetchone()[0], 0)


class LoaderTests(unittest.TestCase):
    def test_exact_utf8_bytes_bounded_read_and_invalid_inputs(self):
        from role_contracts import load_contract
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.md"
            for data in (b"\xff", b"", b" ", b"x" * 65537, "é".encode() * 32769):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    load_contract(path)
            data = ("é\r\n" * 10).encode()
            path.write_bytes(data)
            ref, content = load_contract(path)
            self.assertEqual(content.encode(), data)
            self.assertEqual(ref, "sha256:" + hashlib.sha256(data).hexdigest())
            path.write_bytes(b"x" * 65536)
            self.assertEqual(len(load_contract(path)[1]), 65536)

    def test_runtime_contract_hygiene_keeps_prose_dutch_and_role_local(self):
        contracts = (
            "sherlock.md", "sherlock-output.md",
            "leonardo.md", "leonardo-output.md",
            "kuifje.md", "kuifje-output.md",
        )
        old_english_instruction_fragments = (
            "Read the supplied", "Write rolling", "Do not undertake",
            "You may propose", "When input.research_results is present",
            "Transport: call", "Separate optional", "Optional input.",
            "Execute only", "Search for primary evidence", "Source refs are",
            "This role has no recall tool", "Publish sources only",
            "Stop if authority is refused", "Summarize concrete findings",
            "For failure use", "Retry exact terminal arguments",
            "Missions cannot be created",
        )
        for name in contracts:
            text = (ROOT / "roles" / name).read_text()
            for fragment in old_english_instruction_fragments:
                self.assertNotIn(fragment, text, (name, fragment))

        foreign_roles = {
            "sherlock.md": ("Leonardo", "Ariadne", "Einstein", "Kuifje", "Striktland", "Minos"),
            "sherlock-output.md": ("Leonardo", "Ariadne", "Einstein", "Kuifje", "Striktland", "Minos"),
            "leonardo.md": ("Sherlock", "Ariadne", "Einstein", "Kuifje", "Striktland", "Minos"),
            "leonardo-output.md": ("Sherlock", "Ariadne", "Einstein", "Kuifje", "Striktland", "Minos"),
            "kuifje.md": ("Sherlock", "Ariadne", "Einstein", "Leonardo", "Striktland", "Minos"),
            "kuifje-output.md": ("Sherlock", "Ariadne", "Einstein", "Leonardo", "Striktland", "Minos"),
        }
        for name, forbidden in foreign_roles.items():
            text = (ROOT / "roles" / name).read_text()
            for role in forbidden:
                self.assertNotIn(role, text, (name, role))

    def test_executor_has_no_concrete_roles_and_python_has_no_prompt_constants(self):
        executor = (ROOT / "docs/agents/executor.md").read_text()
        for name in ("Sherlock", "Leonardo", "Kuifje", "Einstein", "Striktland", "Minos"):
            self.assertNotIn(name.lower(), executor.lower())
        tree = ast.parse((ROOT / "leonardo.py").read_text())
        names = {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                 for target in node.targets if isinstance(target, ast.Name)}
        self.assertFalse(names & {"ROLE", "OUTPUT", "CONTRACT_REF"})
        for name in ("sherlock", "sherlock-output", "leonardo", "leonardo-output"):
            self.assertTrue((ROOT / "roles" / (name + ".md")).is_file())
        self.assertFalse((ROOT / "docs/agents/sherlock.md").exists())
