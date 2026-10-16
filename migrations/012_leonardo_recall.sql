-- Rebuild CHECK constraints through the central atomic migration chain.
CREATE TEMP TABLE recall_assignment_backup AS SELECT * FROM leonardo_assignments;
CREATE TEMP TABLE recall_parts_backup AS SELECT * FROM leonardo_assignment_parts;
CREATE TEMP TABLE recall_states_backup AS SELECT * FROM leonardo_states;
DROP TABLE leonardo_states;
DROP TABLE leonardo_assignment_parts;
DROP TABLE leonardo_assignments;
CREATE TABLE leonardo_assignments (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    operation_id TEXT NOT NULL UNIQUE,
    request TEXT NOT NULL,
    dossier_id TEXT NOT NULL REFERENCES leonardo_dossiers(id),
    base_version INTEGER NOT NULL CHECK(base_version >= 0),
    snapshot TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    tokens INTEGER NOT NULL CHECK(tokens BETWEEN 1 AND 1048576)
);
CREATE TABLE leonardo_assignment_parts (
    job_id INTEGER NOT NULL REFERENCES leonardo_assignments(job_id),
    part_id INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY(job_id,part_id,revision),
    FOREIGN KEY(part_id,revision) REFERENCES part_revisions(part_id,revision)
);
CREATE TABLE leonardo_states (
    dossier_id TEXT NOT NULL REFERENCES leonardo_dossiers(id),
    version INTEGER NOT NULL CHECK(version > 0),
    previous_version INTEGER,
    job_id INTEGER NOT NULL UNIQUE REFERENCES leonardo_assignments(job_id),
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES job_attempts(id),
    content TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    tokens INTEGER NOT NULL CHECK(tokens BETWEEN 1 AND 4000),
    created_at TEXT NOT NULL,
    PRIMARY KEY(dossier_id,version),
    CHECK((version=1 AND previous_version IS NULL) OR (version>1 AND previous_version IS NOT NULL AND previous_version=version-1)),
    FOREIGN KEY(dossier_id,previous_version) REFERENCES leonardo_states(dossier_id,version)
);
INSERT INTO leonardo_assignments SELECT * FROM recall_assignment_backup;
INSERT INTO leonardo_assignment_parts SELECT * FROM recall_parts_backup;
INSERT INTO leonardo_states SELECT * FROM recall_states_backup ORDER BY dossier_id,version;
DROP TABLE recall_assignment_backup;
DROP TABLE recall_parts_backup;
DROP TABLE recall_states_backup;
CREATE TRIGGER leonardo_assignments_no_update BEFORE UPDATE ON leonardo_assignments
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_assignments_no_delete BEFORE DELETE ON leonardo_assignments
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_assignments_no_replace BEFORE INSERT ON leonardo_assignments
WHEN EXISTS(SELECT 1 FROM leonardo_assignments WHERE job_id=NEW.job_id OR operation_id=NEW.operation_id)
BEGIN SELECT RAISE(ABORT,'Leonardo replacement forbidden'); END;
CREATE TRIGGER leonardo_assignment_parts_no_update BEFORE UPDATE ON leonardo_assignment_parts
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_assignment_parts_no_delete BEFORE DELETE ON leonardo_assignment_parts
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_assignment_parts_no_replace BEFORE INSERT ON leonardo_assignment_parts
WHEN EXISTS(SELECT 1 FROM leonardo_assignment_parts WHERE job_id=NEW.job_id AND part_id=NEW.part_id AND revision=NEW.revision)
BEGIN SELECT RAISE(ABORT,'Leonardo replacement forbidden'); END;
CREATE TRIGGER leonardo_states_no_update BEFORE UPDATE ON leonardo_states
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_states_no_delete BEFORE DELETE ON leonardo_states
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_states_no_replace BEFORE INSERT ON leonardo_states
WHEN EXISTS(SELECT 1 FROM leonardo_states WHERE (dossier_id=NEW.dossier_id AND version=NEW.version) OR job_id=NEW.job_id OR attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT,'Leonardo replacement forbidden'); END;

-- Content remains in the existing archive. Audit contains no claim secrets or source copies.
CREATE TABLE leonardo_recalls (
    id INTEGER PRIMARY KEY,
    dossier_id TEXT NOT NULL REFERENCES leonardo_dossiers(id),
    job_id INTEGER NOT NULL REFERENCES leonardo_assignments(job_id),
    attempt_id INTEGER NOT NULL REFERENCES job_attempts(id),
    recall_id TEXT NOT NULL,
    ref TEXT NOT NULL,
    part_id INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes > 0),
    tokens INTEGER NOT NULL CHECK(tokens > 0),
    recalled_at TEXT NOT NULL,
    UNIQUE(attempt_id,recall_id),
    FOREIGN KEY(part_id,revision) REFERENCES part_revisions(part_id,revision)
);
CREATE TRIGGER leonardo_recalls_no_update BEFORE UPDATE ON leonardo_recalls
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_recalls_no_delete BEFORE DELETE ON leonardo_recalls
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_recalls_no_replace BEFORE INSERT ON leonardo_recalls
WHEN EXISTS(SELECT 1 FROM leonardo_recalls WHERE id=NEW.id OR (attempt_id=NEW.attempt_id AND recall_id=NEW.recall_id))
BEGIN SELECT RAISE(ABORT,'Leonardo replacement forbidden'); END;
