"""Explicit bounded Leonardo backend contract. Persistence, never model memory.

No automatic offer selection, semantic dossier assignment or mission execution.
All source reconstruction/tokenization happens before the short enqueue lock.
"""

import hashlib
import json

from jobs import JobStore, _id, _text, _stamp
from part_format_v1 import token_count
from revision_storage import reconstruct

ROLE = (
    "Leonardo v1. Read the supplied immutable state and source revisions. "
    "Write rolling dossier state; summaries are not primary evidence. "
    "Keep source facts, inferences, hypotheses, uncertainties and questions distinct. "
    "Do not execute missions. Return only the output state. "
)
OUTPUT = (
    "leonardo-state-v1: exact keys schema_version=1, dossier_id, version, "
    "previous_version, hypotheses, claims, uncertainties, open_questions, processed_refs. "
    "version is previous_version+1. hypotheses/uncertainties/open_questions are lists of "
    "{id,text,refs}; claims are {id,kind,text,support,counterevidence}, "
    "kind is source_fact or inference. References are supplied part:<id>:<revision> "
    "identifiers. Preserve all prior processed_refs and include all supplied parts. "
    "At most 64 items per list, 256 processed_refs, 4000 cl100k_base tokens, 32768 UTF-8 bytes."
)
CONTRACT_REF = "sha256:" + hashlib.sha256(OUTPUT.encode()).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def encoded_state(state):
    """Validate structure/size before entering the finish transaction."""
    keys = {
        "schema_version",
        "dossier_id",
        "version",
        "previous_version",
        "hypotheses",
        "claims",
        "uncertainties",
        "open_questions",
        "processed_refs",
    }
    if (
        not isinstance(state, dict)
        or set(state) != keys
        or type(state["schema_version"]) is not int
        or state["schema_version"] != 1
    ):
        raise ValueError("Invalid Leonardo state schema")
    _text(state["dossier_id"], 128)
    _id(state["version"])
    if (
        type(state["previous_version"]) is not int
        or state["previous_version"] != state["version"] - 1
    ):
        raise ValueError("Invalid previous state version")
    refs = state["processed_refs"]
    if (
        not isinstance(refs, list)
        or len(refs) > 256
        or any(not isinstance(r, str) or len(r) > 128 for r in refs)
        or len(set(refs)) != len(refs)
    ):
        raise ValueError("Invalid processed references")
    ids = set()
    for field in ("hypotheses", "claims", "uncertainties", "open_questions"):
        items = state[field]
        if not isinstance(items, list) or len(items) > 64:
            raise ValueError("Too many state items")
        for item in items:
            expected = (
                {"id", "text", "kind", "support", "counterevidence"}
                if field == "claims"
                else {"id", "text", "refs"}
            )
            if not isinstance(item, dict) or set(item) != expected:
                raise ValueError("Invalid state item")
            _text(item["id"], 128)
            _text(item["text"], 8192)
            if item["id"] in ids:
                raise ValueError("Duplicate state item identity")
            ids.add(item["id"])
            if field == "claims" and item["kind"] not in ("source_fact", "inference"):
                raise ValueError("Claim must distinguish fact and inference")
            for key in (("support", "counterevidence") if field == "claims" else ("refs",)):
                values = item[key]
                if (
                    not isinstance(values, list)
                    or len(values) > 256
                    or any(not isinstance(v, str) or v not in refs for v in values)
                ):
                    raise ValueError("State item references unprocessed material")
            if field == "claims" and item["kind"] == "source_fact" and not item["support"]:
                raise ValueError("Source fact requires support")
    content = canonical(state)
    if len(content.encode()) > 32768:
        raise ValueError("State byte budget exceeded")
    tokens = token_count(content)
    if tokens > 4000:
        raise ValueError("State token budget exceeded")
    return content, hashlib.sha256(content.encode()).hexdigest(), tokens


class LeonardoStore:
    def __init__(self, db, clock=None):
        self.store = JobStore(db, clock)
        self.db = db

    def create_dossier(self, dossier_id, topic):
        _text(dossier_id, 128)
        if type(topic) is not int or topic not in (1, 2, 3):
            raise ValueError("Invalid topic")
        with self.store._write() as now:
            prior = self.db.execute(
                "SELECT topic FROM leonardo_dossiers WHERE id=?", (dossier_id,)
            ).fetchone()
            if prior:
                if prior[0] != topic:
                    raise ValueError("Dossier identity reused")
                return dossier_id
            self.db.execute(
                "INSERT INTO leonardo_dossiers VALUES (?,?,?)", (dossier_id, topic, _stamp(now))
            )
        return dossier_id

    def latest(self, dossier_id):
        row = self.db.execute(
            "SELECT content FROM leonardo_states WHERE dossier_id=? ORDER BY version DESC LIMIT 1",
            (dossier_id,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def enqueue(self, operation_id, dossier_id, base_version, revisions):
        _text(operation_id, 128)
        _text(dossier_id, 128)
        if type(base_version) is not int or base_version < 0:
            raise ValueError("Invalid base version")
        if not isinstance(revisions, list) or not 1 <= len(revisions) <= 32:
            raise ValueError("Expected 1..32 explicit revisions")
        for pair in revisions:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Expected [part_id,revision]")
            for v in pair:
                _id(v)
        if len({tuple(p) for p in revisions}) != len(revisions):
            raise ValueError("Duplicate revision")
        request = canonical([dossier_id, base_version, revisions])
        self.store._idle()
        prior = self.db.execute(
            "SELECT job_id,request FROM leonardo_assignments WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if prior:
            if prior[1] != request:
                raise ValueError("Assignment identity reused")
            return prior[0]
        dossier = self.db.execute(
            "SELECT topic FROM leonardo_dossiers WHERE id=?", (dossier_id,)
        ).fetchone()
        if dossier is None:
            raise ValueError("Unknown dossier")
        state = self.latest(dossier_id)
        if (state["version"] if state else 0) != base_version:
            raise ValueError("Stale dossier state")
        parts = []
        for part, revision in revisions:
            row = self.db.execute(
                "SELECT p.topic,r.sha256 FROM parts p JOIN part_revisions r ON r.part_id=p.id WHERE p.id=? AND r.revision=?",
                (part, revision),
            ).fetchone()
            if row is None or row[0] != dossier[0]:
                raise ValueError("Unknown revision or wrong dossier topic")
            parts.append(
                dict(
                    ref=f"part:{part}:{revision}",
                    sha256=row[1],
                    content=reconstruct(self.db, part, revision).decode("utf-8"),
                )
            )
        snapshot = canonical(
            dict(
                schema_version=1,
                dossier_id=dossier_id,
                base_version=base_version,
                state=state,
                parts=parts,
                role_contract=ROLE,
                output_contract=OUTPUT,
            )
        )
        tokens = token_count(snapshot)
        if tokens > 35000 or len(snapshot.encode()) > 250000:
            raise ValueError("Leonardo input budget exceeded")
        digest = hashlib.sha256(snapshot.encode()).hexdigest()
        from job_control import _AtomicStore

        atomic = _AtomicStore(self.db, self.store.clock)
        with self.store._write() as now:
            prior = self.db.execute(
                "SELECT job_id,request FROM leonardo_assignments WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if prior:
                if prior[1] != request:
                    raise ValueError("Assignment identity reused")
                return prior[0]
            current = self.latest(dossier_id)
            if (current["version"] if current else 0) != base_version:
                raise ValueError("Stale dossier state")
            if self.db.execute(
                "SELECT 1 FROM leonardo_assignments a JOIN jobs j ON j.id=a.job_id WHERE a.dossier_id=? AND j.status IN ('ready','running','blocked')",
                (dossier_id,),
            ).fetchone():
                raise ValueError("Dossier already has pending work")
            atomic.transaction_now = now
            job = atomic.create("Leonardo", ["sha256:" + digest], CONTRACT_REF)
            self.db.execute(
                "INSERT INTO leonardo_assignments VALUES (?,?,?,?,?,?,?,?)",
                (job, operation_id, request, dossier_id, base_version, snapshot, digest, tokens),
            )
            self.db.executemany(
                "INSERT INTO leonardo_assignment_parts VALUES (?,?,?)",
                [(job, *pair) for pair in revisions],
            )
        return job


def commit_state(control, args, encoded):
    """Called only inside generic finish's savepoint, after claim fencing."""
    db = control.db
    row = db.execute(
        "SELECT dossier_id,base_version,snapshot FROM leonardo_assignments WHERE job_id=?",
        (args["job_id"],),
    ).fetchone()
    if row is None:
        if encoded is not None:
            raise ValueError("State supplied for non-Leonardo job")
        return
    if args["status"] != "succeeded":
        if encoded is not None:
            raise ValueError("State requires succeeded finish")
        if args["output_refs"] != []:
            raise ValueError("Leonardo failed/uncertain finish requires empty outputs")
        return
    if encoded is None:
        raise ValueError("Leonardo success requires output state")
    content, digest, tokens = encoded
    state = json.loads(content)
    dossier, base, snapshot = row
    if (
        state["dossier_id"] != dossier
        or state["previous_version"] != base
        or state["version"] != base + 1
    ):
        raise ValueError("Stale or foreign output state")
    result = f"leonardo-state:{dossier}:{base+1}"
    if args["output_refs"] != [result]:
        raise ValueError("Leonardo requires its concrete state result")
    # JobStore.finish has already fenced this claim and checked the exact
    # terminal status/output/error. A new operation ID may confirm that same
    # finish without reapplying its state transition, even after newer states.
    existing = db.execute(
        """SELECT dossier_id,version,previous_version,job_id,attempt_id,content,sha256,tokens
           FROM leonardo_states WHERE job_id=? OR attempt_id=?""",
        (args["job_id"], args["attempt_id"]),
    ).fetchone()
    expected = (
        dossier,
        base + 1,
        base or None,
        args["job_id"],
        args["attempt_id"],
        content,
        digest,
        tokens,
    )
    if existing is not None:
        if existing != expected:
            raise ValueError("Conflicting confirmed Leonardo state")
        return
    current = db.execute(
        "SELECT COALESCE(max(version),0) FROM leonardo_states WHERE dossier_id=?", (dossier,)
    ).fetchone()[0]
    if current != base:
        raise ValueError("Stale or foreign output state")
    input_state = json.loads(snapshot)
    old_refs = set(input_state["state"]["processed_refs"]) if input_state["state"] else set()
    required = old_refs | {p["ref"] for p in input_state["parts"]}
    if set(state["processed_refs"]) != required:
        raise ValueError("Output must preserve exact processed provenance")
    db.execute(
        "INSERT INTO leonardo_states VALUES (?,?,?,?,?,?,?,?,?)",
        (
            dossier,
            base + 1,
            base or None,
            args["job_id"],
            args["attempt_id"],
            content,
            digest,
            tokens,
            _stamp(control.atomic.transaction_now),
        ),
    )


class LeonardoProducer:
    """Ready-only adapter. Explicit enqueue is policy-neutral, not a scheduler."""

    role = "Leonardo"

    def __init__(self, dispatcher):
        self.db = dispatcher.db

    def prepare(self):
        return None

    def produce(self, now, prepared):
        return None

    def ready(self, job_id):
        return (
            self.db.execute(
                "SELECT 1 FROM leonardo_assignments WHERE job_id=?", (job_id,)
            ).fetchone()
            is not None
        )

    def bind(self, job_id, claim, now):
        dossier, base, snapshot, digest = self.db.execute(
            "SELECT dossier_id,base_version,snapshot,sha256 FROM leonardo_assignments WHERE job_id=?",
            (job_id,),
        ).fetchone()
        data = json.loads(snapshot)
        return dict(
            claim,
            role=self.role,
            input=data,
            input_refs=["sha256:" + digest],
            role_contract=data["role_contract"],
            role_contract_ref="sha256:"
            + hashlib.sha256(data["role_contract"].encode()).hexdigest(),
            output_contract=data["output_contract"],
            output_contract_ref=self.db.execute(
                "SELECT output_contract_ref FROM jobs WHERE id=?", (job_id,)
            ).fetchone()[0],
            result_ref=f"leonardo-state:{dossier}:{base+1}",
        )
