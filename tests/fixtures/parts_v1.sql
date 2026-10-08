-- Exact part schema from main f71398a (PR #18), independent migration fixture.

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
CREATE TRIGGER immutable_part_revisions_update BEFORE UPDATE ON part_revisions BEGIN SELECT RAISE(ABORT,'Immutable provenance'); END;
CREATE TRIGGER immutable_part_revisions_delete BEFORE DELETE ON part_revisions BEGIN SELECT RAISE(ABORT,'Immutable provenance'); END;
CREATE TRIGGER immutable_source_archive_update BEFORE UPDATE ON source_archive BEGIN SELECT RAISE(ABORT,'Immutable provenance'); END;
CREATE TRIGGER immutable_source_archive_delete BEFORE DELETE ON source_archive BEGIN SELECT RAISE(ABORT,'Immutable provenance'); END;
CREATE TRIGGER immutable_revision_sources_update BEFORE UPDATE ON revision_sources BEGIN SELECT RAISE(ABORT,'Immutable provenance'); END;
CREATE TRIGGER immutable_revision_sources_delete BEFORE DELETE ON revision_sources BEGIN SELECT RAISE(ABORT,'Immutable provenance'); END;
PRAGMA user_version=1;
