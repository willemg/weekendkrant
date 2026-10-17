"""Explicit bounded Leonardo backend contract. Persistence, never model memory.

No automatic offer selection, semantic dossier assignment or mission execution.
All source reconstruction/tokenization happens before the short enqueue lock.
"""

import hashlib
import json
import re
from pathlib import Path

import role_contracts
from legacy_contracts import LEONARDO_SCHEMA1_UNVERSIONED_OUTPUT

from jobs import JobStore, _id, _text, _stamp
from ariadne_tokens import token_count, TOKENIZER
from revision_storage import reconstruct

ROOT = Path(__file__).resolve().parent
LEGACY_OUTPUT_PREFIXES = {
    'fine_provenance': ('leonardo-output-v2:', 'leonardo-output-v3:'),
    'missions': ('leonardo-output-v3:',),
}


def supports_capability(snapshot, capability):
    """Recognize frozen schema-1 contracts; new assignments use machine semantics."""
    version = snapshot.get('schema_version')
    if type(version) is not int:
        return False
    if version == 2:
        return capability in LEGACY_OUTPUT_PREFIXES
    if version == 1:
        if snapshot['output_contract'] == LEONARDO_SCHEMA1_UNVERSIONED_OUTPUT:
            return capability in LEGACY_OUTPUT_PREFIXES
        prefixes = LEGACY_OUTPUT_PREFIXES.get(capability, ())
        return snapshot['output_contract'].startswith(prefixes)
    return False


def queue_ref(value):
    """Canonical positive SQLite identity; syntax alone grants no authority."""
    return (isinstance(value, str) and len(value) <= 25
            and re.fullmatch(r'queue:[1-9][0-9]*', value) is not None
            and int(value[6:]) <= 9223372036854775807)


def item_refs(state):
    """All content provenance, excluding coarse processed input provenance."""
    for field in ('hypotheses', 'claims', 'uncertainties', 'open_questions'):
        for item in state[field]:
            for key in (('support', 'counterevidence') if field == 'claims' else ('refs',)):
                yield from item[key]

# Local allocation/serialization guardrails, NOT measured provider context limits
# or economic targets. Apply to start snapshot plus cumulative delivered recalls.
MAX_CONTEXT_TOKENS = 1048576
MAX_CONTEXT_BYTES = 8 * 1024 * 1024


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
                    or any(not isinstance(v, str) or (v not in refs and not queue_ref(v))
                           for v in values)
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

    def _recall_authority(self, args, now):
        """Read-only current fencing, deliberately without a lifecycle expiry sweep."""
        from job_control import ControlConflict
        row = self.db.execute(
            """SELECT l.dossier_id,l.snapshot,l.tokens FROM leonardo_assignments l
               JOIN jobs j ON j.id=l.job_id
               JOIN job_attempts a ON a.job_id=j.id
               WHERE j.id=? AND a.id=? AND a.token=? AND j.role='Leonardo'
                 AND j.status='running' AND a.status='running' AND a.lease_until>?
                 AND a.id=(SELECT max(id) FROM job_attempts WHERE job_id=j.id)
                 AND EXISTS(SELECT 1 FROM executor_activations e
                            WHERE e.job_id=j.id AND e.attempt_id=a.id)""",
            (args['job_id'], args['attempt_id'], args['token'], _stamp(now)),
        ).fetchone()
        if row is None:
            raise ControlConflict('Recall requires current Leonardo authority')
        return row

    def recall(self, args):
        """Selective read under current authority; only audit is appended.

        recall_id is attempt-local: retry exact arguments, never a cached authority.
        Reconstruction and tokenization run outside the short final write lock.
        """
        from job_control import JobControl, ControlConflict
        JobControl._schema(args, {'job_id', 'attempt_id', 'token', 'ref', 'recall_id'})
        JobControl._claim_fields(args)
        _text(args['recall_id'], 128)
        _text(args['ref'], 128)
        self.store._idle()
        dossier, snapshot, start_tokens = self._recall_authority(args, self.store.clock())
        data = json.loads(snapshot)
        allowed = {p['ref'] for p in data['parts']}
        if data['state']:
            allowed.update(data['state']['processed_refs'])
        if args['ref'] not in allowed:
            raise ControlConflict('Reference outside immutable dossier provenance')
        match = re.fullmatch(r'part:([1-9][0-9]*):([1-9][0-9]*)', args['ref'])
        if match is None:
            raise ControlConflict('Invalid historical reference')
        part, revision = map(int, match.groups())
        content = reconstruct(self.db, part, revision)
        text = content.decode('utf-8')
        response = dict(ref=args['ref'], sha256=hashlib.sha256(content).hexdigest(),
                        content=text, bytes=len(content), tokens=token_count(text))
        with self.store._write() as now:
            # Expired/finished/recovered during reconstruction: return no bytes,
            # write no delivery record, and never mutate lifecycle state here.
            self._recall_authority(args, now)
            prior = self.db.execute(
                'SELECT ref,bytes,tokens FROM leonardo_recalls WHERE attempt_id=? AND recall_id=?',
                (args['attempt_id'], args['recall_id']),
            ).fetchone()
            if prior:
                if prior != (args['ref'], response['bytes'], response['tokens']):
                    raise ControlConflict('Recall identity reused with different request')
            else:
                used_bytes, used_tokens = self.db.execute(
                    'SELECT COALESCE(sum(bytes),0),COALESCE(sum(tokens),0) FROM leonardo_recalls WHERE attempt_id=?',
                    (args['attempt_id'],),
                ).fetchone()
                if (start_tokens + used_tokens + response['tokens'] > MAX_CONTEXT_TOKENS
                        or len(snapshot.encode('utf-8')) + used_bytes + len(content) > MAX_CONTEXT_BYTES):
                    raise ControlConflict('Leonardo technical context fail-safe exceeded')
                self.db.execute(
                    """INSERT INTO leonardo_recalls
                       (dossier_id,job_id,attempt_id,recall_id,ref,part_id,revision,bytes,tokens,recalled_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (dossier, args['job_id'], args['attempt_id'], args['recall_id'], args['ref'],
                     part, revision, len(content), response['tokens'], _stamp(now)),
                )
        return response

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

    def reevaluate(self, operation_id, dossier_id, base_version, kuifje_results=None):
        """New editorial work over existing state, never replayed source input."""
        return self.enqueue(operation_id, dossier_id, base_version, [], mode='reevaluation',
                            kuifje_results=kuifje_results)

    def enqueue(self, operation_id, dossier_id, base_version, revisions, mode='new_material',
                kuifje_results=None):
        _text(operation_id, 128)
        _text(dossier_id, 128)
        if type(base_version) is not int or base_version < 0:
            raise ValueError("Invalid base version")
        if mode not in ('new_material', 'reevaluation'):
            raise ValueError('Invalid assignment mode')
        if not isinstance(revisions, list) or not (0 if mode == 'reevaluation' else 1) <= len(revisions) <= 32:
            raise ValueError("Expected 1..32 explicit revisions")
        if mode == 'reevaluation' and (revisions or base_version == 0):
            raise ValueError('Reevaluation requires existing state and zero new parts')
        for pair in revisions:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Expected [part_id,revision]")
            for v in pair:
                _id(v)
        if len({tuple(p) for p in revisions}) != len(revisions):
            raise ValueError("Duplicate revision")
        from kuifje import result_selection, selected_results
        selections = result_selection(kuifje_results)
        # Preserve historical enqueue receipt identity when no feedback is selected.
        request = canonical([dossier_id, base_version, revisions] +
                            (['reevaluation'] if mode == 'reevaluation' else []) +
                            ([{'kuifje_results': selections}] if selections else []))
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
        # Terminal immutable outcomes are resolved from exact job/attempt pairs,
        # never from worker-supplied result text or a mutable latest pointer.
        feedback = selected_results(self.db, dossier_id, base_version, selections)
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
        (_, role_contract), (output_ref, output_contract) = [
            role_contracts.load_contract(ROOT / "roles" / name)
            for name in ("leonardo.md", "leonardo-output.md")
        ]
        snapshot = canonical(
            dict(
                schema_version=2,
                mode=mode,
                tokenizer=TOKENIZER,
                dossier_id=dossier_id,
                base_version=base_version,
                state=state,
                parts=parts,
                research_results=feedback,
                role_contract=role_contract,
                output_contract=output_contract,
            )
        )
        tokens = token_count(snapshot)
        if tokens > MAX_CONTEXT_TOKENS or len(snapshot.encode()) > MAX_CONTEXT_BYTES:
            raise ValueError("Leonardo technical input fail-safe exceeded")
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
            job = atomic.create("Leonardo", ["sha256:" + digest], output_ref)
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
    if (input_state.get('mode') == 'reevaluation'
            and state['processed_refs'] != input_state['state']['processed_refs']):
        raise ValueError('Reevaluation must preserve exact processed reference order')
    if set(state["processed_refs"]) != required:
        raise ValueError("Output must preserve exact processed provenance")
    queues = {ref for ref in item_refs(state) if ref not in required}
    if queues:
        # The immutable assignment determines the output vocabulary. Updating
        # deployment files must not silently widen already frozen contracts.
        if not supports_capability(input_state, 'fine_provenance'):
            raise ValueError('Frozen output contract permits only part references')
        allowed = set()
        for ref in required:
            match = re.fullmatch(r'part:([1-9][0-9]*):([1-9][0-9]*)', ref)
            if match is None:
                raise ValueError('Invalid processed part reference')
            allowed.update(f'queue:{identity}' for (identity,) in db.execute(
                '''SELECT m.queue_id FROM revision_sources m
                   JOIN source_archive a ON a.queue_id=m.queue_id
                   JOIN part_revisions r ON r.part_id=m.part_id AND r.revision=m.revision
                   WHERE m.part_id=? AND m.revision=?''',
                tuple(map(int, match.groups()))))
        if not queues <= allowed:
            raise ValueError('State item references unprocessed queue material')
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

    return True  # Newly committed in this savepoint, not an old state replay.


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
