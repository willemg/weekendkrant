-- Explicit backend Leonardo assignments; no offer producer or scheduler.
CREATE TABLE leonardo_dossiers (
    id TEXT PRIMARY KEY,
    topic INTEGER NOT NULL CHECK(topic IN (1,2,3)),
    created_at TEXT NOT NULL
);
CREATE TABLE leonardo_assignments (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    operation_id TEXT NOT NULL UNIQUE,
    request TEXT NOT NULL,
    dossier_id TEXT NOT NULL REFERENCES leonardo_dossiers(id),
    base_version INTEGER NOT NULL CHECK(base_version >= 0),
    snapshot TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    tokens INTEGER NOT NULL CHECK(tokens BETWEEN 1 AND 35000)
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
CREATE TRIGGER leonardo_dossiers_no_update BEFORE UPDATE ON leonardo_dossiers
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_dossiers_no_delete BEFORE DELETE ON leonardo_dossiers
BEGIN SELECT RAISE(ABORT,'immutable Leonardo audit'); END;
CREATE TRIGGER leonardo_dossiers_no_replace BEFORE INSERT ON leonardo_dossiers
WHEN EXISTS(SELECT 1 FROM leonardo_dossiers WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'Leonardo replacement forbidden'); END;
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
