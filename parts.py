"""Small storage and deterministic planning layer for immutable week/topic parts."""
from dataclasses import dataclass
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
import sqlite3

from database import SCHEMA_VERSION, migrate  # Public compatibility exports.

TOKENIZER = 'cl100k_base'
# Keep five minutes of slack below the :15/:45 cadence: commit/start jitter
# must not postpone an offer until the next hourly source batch resets its age.
OFFER_QUIET_PERIOD = timedelta(minutes=25)


@dataclass(frozen=True)
class PartOffer:
    id: int
    part_id: int
    revision: int
    created_at: str


@dataclass(frozen=True)
class PlannedRevision:
    week: str
    topic: int
    part: int
    revision: int
    is_open: bool
    sources: tuple
    text: str
    tokens: int
    reserve: int


def render(items, week, topic, part, revision, reserve):
    head = (f'WEEKENDKRANT-PART-1\nweek: {week}\ntopic: {topic}\npart: {part}\n'
            f'revision: {revision}\ntokenizer: {TOKENIZER}\nreserved_tokens: {reserve}\n\n')
    return head + ''.join(
        f'\n--- SOURCE {f.path} date={f.date} sha256={f.sha256} bytes={len(f.data)} ---\n'
        + f.data.decode('utf-8') + '\n--- END SOURCE ---\n' for f in items)


def weave(fiches, week, topic, state, existing, count, limit, reserve):
    """Append, never repack: only the highest open part can grow."""
    opened = [row for row in state if row[2]]
    if opened:
        _, number, _, active = opened[0]
        revision = active + 1
        current = list(existing)
    else:
        number = max((row[1] for row in state), default=0) + 1
        revision, current = 1, []
    changed = False
    plans = []
    close_existing = None

    def finish(is_open):
        text = render(current, week, topic, number, revision, reserve)
        tokens = count(text)
        if tokens + reserve > limit:
            raise ValueError('Part overschrijdt tokenbudget')
        plans.append(PlannedRevision(week, topic, number, revision, is_open,
                                     tuple(current), text, tokens, reserve))

    for fiche in sorted(fiches, key=lambda f: (f.date, int(f.path[6:]))):
        if count(render(current + [fiche], week, topic, number, revision, reserve)) + reserve > limit:
            if current:
                if changed:
                    finish(False)
                else:
                    close_existing = number
                number += 1
                revision, current, changed = 1, [], False
            if count(render([fiche], week, topic, number, revision, reserve)) + reserve > limit:
                raise ValueError(f'Eén fiche overschrijdt tokenbudget: {fiche.path}')
        current.append(fiche)
        changed = True
    if changed:
        finish(True)
    return plans, close_existing


class PartStore:
    def __init__(self, db):
        self.db = db

    def offer(self, part_id, revision):
        """Persist one exact active revision and seal its part; no model call.

        Owns a short transaction. An identical retry returns the original offer,
        including its stable ID and timestamp. Stale revision requests fail.
        """
        if self.db.in_transaction:
            raise ValueError('Offer vereist een connection zonder actieve transactie')
        if type(part_id) is not int or type(revision) is not int or revision < 1:
            raise ValueError('Offer vereist integer part-ID en positieve revision')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result = self._offer(part_id, revision)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def _offer(self, part_id, revision):
        active = self.db.execute('''SELECT p.active_revision FROM parts p
            JOIN part_revisions r ON r.part_id=p.id AND r.revision=p.active_revision
            WHERE p.id=?''', (part_id,)).fetchone()
        if active != (revision,):
            raise ValueError('Offer vereist de geregistreerde actieve revision')
        row = self.db.execute('''SELECT id,part_id,revision,created_at
            FROM part_offers WHERE part_id=?''', (part_id,)).fetchone()
        if row is None:
            self.db.execute('INSERT INTO part_offers(part_id,revision) VALUES (?,?)',
                            (part_id, revision))
            row = self.db.execute('''SELECT id,part_id,revision,created_at
                FROM part_offers WHERE part_id=?''', (part_id,)).fetchone()
        elif row[2] != revision:
            raise ValueError('Part werd reeds onder een andere revision aangeboden')
        return PartOffer(*row)

    def offer_ready(self, now=None):
        """Offer closed parts or quiescent open parts, atomically with selection.

        No job/model dispatch. Unknown age never seals an open legacy part.
        Caller holds daily's runtime lock; the short DB lock also fences ingress.
        """
        from ariadne import week_name
        if self.db.in_transaction:
            raise ValueError('Offer vereist een connection zonder actieve transactie')
        if now is not None and (now.tzinfo is None or now.utcoffset() is None):
            raise ValueError('Offerklok moet een timezone bevatten')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            now = datetime.now(timezone.utc) if now is None else now
            cutoff = now - OFFER_QUIET_PERIOD
            pending = set()
            for raw, in self.db.execute("SELECT payload FROM ingress_queue WHERE status='pending'"):
                payload = json.loads(raw)
                pending.add((week_name(date.fromisoformat(payload['date'])), payload['topic']))
            running = {row[0] for row in self.db.execute(
                "SELECT topic FROM sherlock_runs WHERE status='running'")}
            candidates = self.db.execute('''SELECT p.id,p.active_revision,p.week,p.topic,p.is_open
                FROM parts p JOIN part_revisions r
                ON r.part_id=p.id AND r.revision=p.active_revision
                LEFT JOIN part_offers o ON o.part_id=p.id
                WHERE o.id IS NULL ORDER BY p.week,p.topic,p.part''').fetchall()
            offers = []
            for identity, revision, week, topic, is_open in candidates:
                if is_open:
                    if (week, topic) in pending or topic in running:
                        continue
                    stamps = self.db.execute('''SELECT m.materialized_at
                        FROM revision_sources s LEFT JOIN source_materializations m
                        ON m.queue_id=s.queue_id WHERE s.part_id=? AND s.revision=?''',
                        (identity, revision)).fetchall()
                    if not stamps:
                        continue
                    times = []
                    for stamp, in stamps:
                        try:
                            value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                            if value.tzinfo is None or value.utcoffset() is None:
                                break
                            times.append(value)
                        except (AttributeError, ValueError):
                            break
                    if len(times) != len(stamps) or max(times) > cutoff:
                        continue
                offers.append(self._offer(identity, revision))
            self.db.commit()
            return tuple(offers)
        except Exception:
            self.db.rollback()
            raise

    def state(self, week, topic):
        return tuple(self.db.execute(
            'SELECT id,part,is_open,active_revision FROM parts WHERE week=? AND topic=? ORDER BY part',
            (week, topic)).fetchall())

    def active_sources(self, state):
        from daily import Fiche
        opened = [row for row in state if row[2]]
        if not opened:
            return ()
        identity, _, _, revision = opened[0]
        rows = self.db.execute('''SELECT a.queue_id,a.topic,a.content,a.sha256,a.date,a.schema_version
            FROM revision_sources m JOIN source_archive a ON a.queue_id=m.queue_id
            WHERE m.part_id=? AND m.revision=? ORDER BY m.position''', (identity, revision)).fetchall()
        return tuple(Fiche(f'queue:{i}', topic, data, digest, day, version)
                     for i, topic, data, digest, day, version in rows)

    def check_state(self, snapshots):
        for (week, topic), state in snapshots.items():
            if self.state(week, topic) != state:
                raise ValueError(f'Partstaat gewijzigd: {week}/topic_{topic}')

    def archive(self, fiche):
        identity = int(fiche.path[6:])
        values = (identity, fiche.schema_version, fiche.date, fiche.topic, fiche.data, fiche.sha256)
        old = self.db.execute('SELECT * FROM source_archive WHERE queue_id=?', (identity,)).fetchone()
        if old is not None:
            if old != values:
                raise ValueError(f'Andere bronbytes/provenance voor {fiche.path}')
            return
        self.db.execute('INSERT INTO source_archive VALUES (?,?,?,?,?,?)', values)

    def register(self, plans, paths, closures, snapshots, new_sources):
        if not self.db.in_transaction:
            raise ValueError('Partregistratie vereist transactie')
        self.check_state(snapshots)
        for fiche in new_sources:
            self.archive(fiche)
        for (week, topic), number in closures.items():
            if number is not None:
                self.db.execute('UPDATE parts SET is_open=0 WHERE week=? AND topic=? AND part=?',
                                (week, topic, number))
        for plan, path in zip(plans, paths):
            row = self.db.execute('SELECT id,is_open,active_revision FROM parts WHERE week=? AND topic=? AND part=?',
                                  (plan.week, plan.topic, plan.part)).fetchone()
            if row is None:
                identity = self.db.execute('INSERT INTO parts(week,topic,part,is_open) VALUES (?,?,?,?)',
                                          (plan.week, plan.topic, plan.part, int(plan.is_open))).lastrowid
            else:
                identity, is_open, active_revision = row
                if not is_open and active_revision is not None:
                    raise ValueError(f'Gesloten part kan geen nieuwe revisie ontvangen: '
                                     f'{plan.week}/topic_{plan.topic}/part_{plan.part}')
            data = plan.text.encode('utf-8')
            self.db.execute('INSERT INTO part_revisions VALUES (?,?,?,?,?,?,?)',
                            (identity, plan.revision, str(path), hashlib.sha256(data).hexdigest(),
                             plan.tokens, TOKENIZER, plan.reserve))
            for position, fiche in enumerate(plan.sources):
                self.db.execute('INSERT INTO revision_sources VALUES (?,?,?,?)',
                                (identity, plan.revision, position, int(fiche.path[6:])))
            self.db.execute('UPDATE parts SET is_open=?,active_revision=? WHERE id=?',
                            (int(plan.is_open), plan.revision, identity))
