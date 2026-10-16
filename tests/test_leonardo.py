"""Backend slice: explicit assignment, generic dispatch and atomic state commit."""

from datetime import datetime, timedelta, timezone
import json
import sqlite3
import unittest

from dispatcher import Dispatcher
from job_control import JobControl
from leonardo import LeonardoStore
from test_parts import PartFixture


class LeonardoTests(PartFixture):
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

    def enqueue(self, operation="prepare:1"):
        return self.store.enqueue(operation, "dossier:reproduction", 0, [list(self.part)])

    def start(self, activation="slot:1"):
        return Dispatcher(self.conn, lambda: self.now).start(
            dict(operation_id="start:" + activation, activation_id=activation)
        )

    def state(self, version=1):
        ref = "part:%s:%s" % self.part
        return dict(
            schema_version=1,
            dossier_id="dossier:reproduction",
            version=version,
            previous_version=version - 1,
            hypotheses=[dict(id="h1", text="Possible pattern", refs=[ref])],
            claims=[
                dict(
                    id="c1",
                    kind="source_fact",
                    text="Reported result",
                    support=[ref],
                    counterevidence=[],
                )
            ],
            uncertainties=[dict(id="u1", text="Unreplicated", refs=[ref])],
            open_questions=[dict(id="q1", text="Independent reproduction?", refs=[ref])],
            processed_refs=[ref],
        )

    def finish(self, claim, state=None, operation="finish:1", **extra):
        args = {k: claim[k] for k in ("job_id", "attempt_id", "token")}
        args.update(
            operation_id=operation,
            status="succeeded",
            output_refs=[claim["result_ref"]],
            leonardo_state=state or self.state(),
        )
        args.update(extra)
        return JobControl(self.conn, lambda: self.now).execute("finish", args)

    def test_assignment_dispatch_finish_replay_and_next_snapshot(self):
        job = self.enqueue()
        self.assertEqual(job, self.enqueue())
        claim = self.start()
        self.assertEqual(claim["job_id"], job)
        self.assertEqual(claim["role"], "Leonardo")
        self.assertIsNone(claim["input"]["state"])
        self.assertIn("WEEKENDKRANT-PART-1", claim["input"]["parts"][0]["content"])
        self.assertEqual(self.finish(claim), self.finish(claim))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM leonardo_states").fetchone()[0], 1)
        stored = self.store.latest("dossier:reproduction")
        self.assertEqual(stored, self.state())
        job2 = self.store.enqueue("prepare:2", "dossier:reproduction", 1, [list(self.part)])
        claim2 = self.start("slot:2")
        self.assertEqual(claim2["job_id"], job2)
        self.assertEqual(claim2["input"]["state"], stored)
        self.finish(claim2, self.state(2), "finish:2")
        self.assertEqual(self.store.latest("dossier:reproduction")["version"], 2)
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_invalid_output_is_atomic_and_prior_state_survives(self):
        self.enqueue()
        claim = self.start()
        invalid = []
        for key, value in [
            ("dossier_id", "other"),
            ("previous_version", 9),
            ("version", 3),
            ("processed_refs", ["part:999:1"]),
            ("claims", [{"id": "x", "kind": "guess"}]),
            ("open_questions", [{"id": "x", "text": "x" * 40000, "refs": []}]),
            ("hypotheses", [{"id": "h", "text": "x", "refs": ["part:999:1"]}]),
        ]:
            state = self.state()
            state[key] = value
            invalid.append(state)
        for state in invalid:
            with self.subTest(state_key=list(state)[0]), self.assertRaises(ValueError):
                self.finish(claim, state)
            self.assertIsNone(self.store.latest("dossier:reproduction"))
            self.assertEqual(
                self.conn.execute(
                    "SELECT status FROM jobs WHERE id=?", (claim["job_id"],)
                ).fetchone()[0],
                "running",
            )
        self.finish(claim)

    def test_no_generic_success_without_validated_state(self):
        self.enqueue()
        claim = self.start()
        args = {k: claim[k] for k in ("job_id", "attempt_id", "token")}
        args.update(operation_id="bad", status="succeeded", output_refs=[claim["result_ref"]])
        with self.assertRaises(ValueError):
            JobControl(self.conn, lambda: self.now).execute("finish", args)

    def test_stale_base_duplicate_job_and_changed_retry_rejected(self):
        self.enqueue()
        with self.assertRaises(ValueError):
            self.store.enqueue("another", "dossier:reproduction", 0, [list(self.part)])
        with self.assertRaises(ValueError):
            self.store.enqueue("prepare:1", "dossier:reproduction", 1, [list(self.part)])
        claim = self.start()
        self.finish(claim)
        with self.assertRaises(ValueError):
            self.store.enqueue("stale", "dossier:reproduction", 0, [list(self.part)])
        changed = self.state()
        changed["hypotheses"] = []
        with self.assertRaises(ValueError):
            self.finish(claim, changed)

    def test_expiry_recovery_fences_old_claim_same_snapshot(self):
        self.enqueue()
        old = self.start()
        self.now += timedelta(hours=2)
        with self.assertRaises(ValueError):
            self.finish(old)
        self.assertEqual(
            self.conn.execute("SELECT status FROM jobs WHERE id=?", (old["job_id"],)).fetchone()[0],
            "blocked",
        )
        control = JobControl(self.conn, lambda: self.now)
        control.execute(
            "reconcile",
            dict(
                operation_id="recover",
                job_id=old["job_id"],
                attempt_id=old["attempt_id"],
                decision="retry",
                evidence_ref="operator:stopped-and-no-effects",
            ),
        )
        new = self.start("slot:retry")
        self.assertEqual(old["input"], new["input"])
        self.assertNotEqual(old["token"], new["token"])
        with self.assertRaises(ValueError):
            self.finish(old, operation="old:retry")
        self.finish(new)

    def test_snapshot_bounds_unknown_revision_and_immutable_audit(self):
        with self.assertRaises(ValueError):
            self.store.enqueue("unknown", "dossier:reproduction", 0, [[999, 1]])
        with self.assertRaises(ValueError):
            self.store.enqueue("many", "dossier:reproduction", 0, [list(self.part)] * 33)
        self.enqueue()
        claim = self.start()
        self.finish(claim)
        for table in (
            "leonardo_states",
            "leonardo_assignments",
            "leonardo_assignment_parts",
            "leonardo_dossiers",
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute("DELETE FROM " + table)
            self.conn.rollback()
        self.assertEqual(self.store.latest("dossier:reproduction"), self.state())

    def http_post(self):
        import http.client
        import threading
        from ingress_api import Config, create_server

        server = create_server(Config(token="secret", db_path=self.db, port=0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(route, args):
            client = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                client.request("POST", route, json.dumps(args), {"Authorization": "Bearer secret"})
                response = client.getresponse()
                return response.status, json.loads(response.read())
            finally:
                client.close()

        return post

    def test_http_start_finish_state_and_retry(self):
        self.enqueue()
        post = self.http_post()
        code, claim = post(
            "/executor/start", dict(operation_id="http:start", activation_id="http:slot")
        )
        self.assertEqual(code, 200)
        self.assertEqual(claim["role"], "Leonardo")
        args = {k: claim[k] for k in ("job_id", "attempt_id", "token")}
        args.update(
            operation_id="http:finish",
            status="succeeded",
            output_refs=[claim["result_ref"]],
            leonardo_state=self.state(),
        )
        self.assertEqual(post("/jobs/finish", args)[0], 200)
        self.assertEqual(post("/jobs/finish", args)[0], 200)
        before = self.conn.execute("SELECT * FROM leonardo_states").fetchall()
        self.assertEqual(post("/jobs/finish", dict(args, operation_id="http:B"))[0], 200)
        changed = self.state()
        changed["hypotheses"] = []
        self.assertEqual(
            post("/jobs/finish", dict(args, operation_id="http:C", leonardo_state=changed))[0], 409
        )
        self.assertEqual(self.conn.execute("SELECT * FROM leonardo_states").fetchall(), before)
        self.assertEqual(len(before), 1)
        self.assertEqual(self.store.latest("dossier:reproduction"), self.state())

    def test_http_failed_finish_rejects_phantom_output(self):
        self.check_non_success_finish("failed", self.http_post())

    def test_http_uncertain_finish_rejects_phantom_output(self):
        self.check_non_success_finish("uncertain", self.http_post())

    def test_input_budget_and_failed_output_leave_no_state(self):
        from unittest.mock import patch

        with patch("leonardo.token_count", return_value=35001):
            with self.assertRaises(ValueError):
                self.enqueue()
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM leonardo_assignments").fetchone()[0], 0
        )
        self.enqueue()
        claim = self.start()
        args = {k: claim[k] for k in ("job_id", "attempt_id", "token")}
        args.update(operation_id="failed", status="failed", output_refs=[], error="No valid state")
        JobControl(self.conn, lambda: self.now).execute("finish", args)
        self.assertIsNone(self.store.latest("dossier:reproduction"))
        self.enqueue("new:after:failure")

    def test_schema_eleven_rollback_preserves_ten_and_audit_rejects_replacement(self):
        import database
        from unittest.mock import patch

        with sqlite3.connect(":memory:") as db:
            with patch.object(database, "SCHEMA_VERSION", 10):
                database.migrate(db)
            before = list(db.iterdump())
            original = database.migration_sql
            with patch(
                "database.migration_sql",
                side_effect=lambda v: original(v) + "CREATE TABLE jobs(conflict);",
            ):
                with self.assertRaises(sqlite3.Error):
                    database.migrate(db)
            self.assertEqual(list(db.iterdump()), before)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 10)
            database.migrate(db)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.enqueue()
        self.finish(self.start())
        for table in (
            "leonardo_dossiers",
            "leonardo_assignments",
            "leonardo_assignment_parts",
            "leonardo_states",
        ):
            for sql in (
                "UPDATE " + table + " SET rowid=rowid",
                "INSERT OR REPLACE INTO " + table + " SELECT * FROM " + table,
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(sql)
                self.conn.rollback()

    def test_pending_enqueue_is_serialized_across_connections(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        ready = Barrier(2)

        def enqueue(identity):
            with sqlite3.connect(self.db) as db:
                store = LeonardoStore(db, lambda: self.now)
                ready.wait(timeout=5)
                try:
                    return store.enqueue(identity, "dossier:reproduction", 0, [list(self.part)])
                except ValueError:
                    return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(enqueue, identity) for identity in ("parallel:1", "parallel:2")]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM leonardo_assignments").fetchone()[0], 1
        )

    def assert_no_outputs(self, claim, status):
        job = self.conn.execute(
            "SELECT status,output_refs FROM jobs WHERE id=?", (claim["job_id"],)
        ).fetchone()
        attempt = self.conn.execute(
            "SELECT status,output_refs FROM job_attempts WHERE id=?", (claim["attempt_id"],)
        ).fetchone()
        self.assertEqual(job, ("blocked" if status == "uncertain" else status, "[]"))
        self.assertEqual(attempt, (status, "[]"))
        self.assertIsNone(self.store.latest("dossier:reproduction"))

    def check_non_success_finish(self, status, post=None):
        self.enqueue()
        if post:
            code, claim = post(
                "/executor/start", dict(operation_id="http:start", activation_id="http:slot")
            )
            self.assertEqual(code, 200)
        else:
            claim = self.start()
        authority = {k: claim[k] for k in ("job_id", "attempt_id", "token")}
        args = dict(authority, operation_id="non-success", status=status, output_refs=[])
        bad_requests = [
            dict(args, output_refs=[claim["result_ref"]]),
            dict(args, leonardo_state=self.state()),
            dict(args, output_refs=[claim["result_ref"]], leonardo_state=self.state()),
        ]
        for invalid in bad_requests:
            if post:
                self.assertEqual(post("/jobs/finish", invalid)[0], 409)
            else:
                with self.assertRaises(ValueError):
                    JobControl(self.conn, lambda: self.now).execute("finish", invalid)
            self.assert_no_outputs(claim, "running")
            self.assertEqual(
                self.conn.execute(
                    "SELECT count(*) FROM job_operations WHERE operation_id=?",
                    (args["operation_id"],),
                ).fetchone()[0],
                0,
            )
        if post:
            self.assertEqual(post("/jobs/finish", args)[0], 200)
        else:
            JobControl(self.conn, lambda: self.now).execute("finish", args)
        self.assert_no_outputs(claim, status)

    def test_failed_finish_rejects_phantom_output(self):
        self.check_non_success_finish("failed")

    def test_uncertain_finish_rejects_phantom_output(self):
        self.check_non_success_finish("uncertain")

    def test_abandon_has_no_state_or_outputs(self):
        self.enqueue()
        claim = self.start()
        args = {k: claim[k] for k in ("job_id", "attempt_id", "token")}
        JobControl(self.conn, lambda: self.now).execute(
            "abandon", dict(args, operation_id="abandon", error="Unknown outcome")
        )
        self.assert_no_outputs(claim, "uncertain")

    def test_success_finish_new_operation_is_exact_state_noop(self):
        self.enqueue()
        claim = self.start()
        first = self.finish(claim, operation="finish:A")
        before = self.conn.execute("SELECT * FROM leonardo_states").fetchall()
        self.assertEqual(self.finish(claim, operation="finish:B"), first)
        changed = self.state()
        changed["hypotheses"] = []
        with self.assertRaises(ValueError):
            self.finish(claim, changed, operation="finish:C")
        self.assertEqual(self.conn.execute("SELECT * FROM leonardo_states").fetchall(), before)
        self.assertEqual(len(before), 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM job_operations WHERE operation_id IN ('finish:A','finish:B')"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM job_operations WHERE operation_id='finish:C'"
            ).fetchone()[0],
            0,
        )
        # Exact old completion remains a no-op after a later state has committed.
        self.store.enqueue("prepare:next", "dossier:reproduction", 1, [list(self.part)])
        self.finish(self.start("slot:next"), self.state(2), "finish:next")
        self.assertEqual(self.finish(claim, operation="finish:D"), first)
        self.assertEqual(self.store.latest("dossier:reproduction")["version"], 2)
