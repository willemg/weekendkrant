"""Small storage and deterministic planning layer for immutable week/topic parts."""
from dataclasses import dataclass
import hashlib
import sqlite3

SCHEMA_VERSION = 1
TOKENIZER = 'cl100k_base'

SCHEMA = '''
CREATE TABLE parts (
    id INTEGER PRIMARY KEY,
    week TEXT NOT NULL,
    topic INTEGER NOT NULL CHECK(topic IN (1,2,3)),
    part INTEGER NOT NULL CHECK(part > 0),
    is_open INTEGER NOT NULL CHECK(is_open IN (0,1)),
    active_revision INTEGER,
    UNIQUE(week,topic,part),
    FOREIGN KEY(id,active_revision) REFERENCES part_revisions(part_id,revision)

);
CREATE UNIQUE INDEX one_open_part ON parts(week,topic) WHERE is_open=1;
CREATE TABLE part_revisions (
    part_id INTEGER NOT NULL REFERENCES parts(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    tokens INTEGER NOT NULL CHECK(tokens >= 0),
    tokenizer TEXT NOT NULL,
    reserved_tokens INTEGER NOT NULL CHECK(reserved_tokens >= 0),
    PRIMARY KEY(part_id,revision)
);
CREATE TABLE source_archive (
    queue_id INTEGER PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    date TEXT NOT NULL,
    topic INTEGER NOT NULL,
    content BLOB NOT NULL CHECK(typeof(content)='blob'),
    sha256 TEXT NOT NULL
);
CREATE TABLE revision_sources (
    part_id INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK(position >= 0),
    queue_id INTEGER NOT NULL REFERENCES source_archive(queue_id),
    PRIMARY KEY(part_id,revision,position),
    UNIQUE(part_id,revision,queue_id),
    FOREIGN KEY(part_id,revision) REFERENCES part_revisions(part_id,revision)
);
CREATE TRIGGER stable_part_identity BEFORE UPDATE OF id,week,topic,part ON parts
BEGIN SELECT RAISE(ABORT,'Immutable part identity'); END;
CREATE TRIGGER never_reopen BEFORE UPDATE OF is_open ON parts
WHEN OLD.is_open=0 AND NEW.is_open=1
BEGIN SELECT RAISE(ABORT,'Closed part cannot reopen'); END;
CREATE TRIGGER closed_part_no_new_revision BEFORE INSERT ON part_revisions
WHEN EXISTS (SELECT 1 FROM parts WHERE id=NEW.part_id
             AND is_open=0 AND active_revision IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'Closed part cannot receive new revisions'); END;
CREATE TRIGGER monotone_active_revision BEFORE UPDATE OF active_revision ON parts
WHEN OLD.active_revision IS NOT NULL AND
     (NEW.active_revision IS NULL OR NEW.active_revision <= OLD.active_revision)
BEGIN SELECT RAISE(ABORT,'Active revision must advance'); END;
CREATE TRIGGER sealed_membership BEFORE INSERT ON revision_sources
WHEN NEW.revision <= (SELECT active_revision FROM parts WHERE id=NEW.part_id)
BEGIN SELECT RAISE(ABORT,'Immutable revision membership'); END;
'''


def migrate(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError('Onbekende nieuwere SQLite schema-versie')
    if version == SCHEMA_VERSION:
        return
    # One transactional DDL migration; legacy rows are never touched.
    immutable = ''
    for table in ('part_revisions', 'source_archive', 'revision_sources'):
        for operation in ('UPDATE', 'DELETE'):
            immutable += (f'CREATE TRIGGER immutable_{table}_{operation.lower()} '
                          f'BEFORE {operation} ON {table} '
                          "BEGIN SELECT RAISE(ABORT,'Immutable provenance'); END;\n")
    try:
        db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + immutable +
                         f'PRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;')
    except Exception:
        db.rollback()
        raise


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
