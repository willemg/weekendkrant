-- Missions are separate immutable runtime input, never Leonardo dossier memory.
CREATE TABLE kuifje_missions (
    mission_id TEXT PRIMARY KEY,
    producer_job_id INTEGER NOT NULL REFERENCES leonardo_assignments(job_id),
    dossier_id TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 4),
    content TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes > 0),
    tokens INTEGER NOT NULL CHECK(tokens > 0),
    tokenizer TEXT NOT NULL CHECK(tokenizer='cl100k_base'),
    created_at TEXT NOT NULL,
    UNIQUE(producer_job_id,ordinal),
    FOREIGN KEY(dossier_id,state_version) REFERENCES leonardo_states(dossier_id,version)
);
CREATE TABLE kuifje_assignments (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    mission_id TEXT NOT NULL UNIQUE REFERENCES kuifje_missions(mission_id),
    snapshot TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes > 0),
    tokens INTEGER NOT NULL CHECK(tokens > 0),
    tokenizer TEXT NOT NULL CHECK(tokenizer='cl100k_base')
);
CREATE TABLE kuifje_fiches (
    queue_item_id INTEGER PRIMARY KEY REFERENCES ingress_queue(id),
    job_id INTEGER NOT NULL REFERENCES kuifje_assignments(job_id),
    attempt_id INTEGER NOT NULL REFERENCES job_attempts(id),
    fiche_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    UNIQUE(job_id,fiche_id)
);
CREATE TABLE kuifje_results (
    job_id INTEGER PRIMARY KEY REFERENCES kuifje_assignments(job_id),
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES job_attempts(id),
    content TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes > 0),
    tokens INTEGER NOT NULL CHECK(tokens > 0),
    tokenizer TEXT NOT NULL CHECK(tokenizer='cl100k_base')
);
CREATE TRIGGER kuifje_missions_no_update BEFORE UPDATE ON kuifje_missions
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_missions_no_delete BEFORE DELETE ON kuifje_missions
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_missions_no_replace BEFORE INSERT ON kuifje_missions
WHEN EXISTS(SELECT 1 FROM kuifje_missions WHERE mission_id=NEW.mission_id OR (producer_job_id=NEW.producer_job_id AND ordinal=NEW.ordinal))
BEGIN SELECT RAISE(ABORT,'Kuifje replacement forbidden'); END;
CREATE TRIGGER kuifje_assignments_no_update BEFORE UPDATE ON kuifje_assignments
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_assignments_no_delete BEFORE DELETE ON kuifje_assignments
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_assignments_no_replace BEFORE INSERT ON kuifje_assignments
WHEN EXISTS(SELECT 1 FROM kuifje_assignments WHERE job_id=NEW.job_id OR mission_id=NEW.mission_id)
BEGIN SELECT RAISE(ABORT,'Kuifje replacement forbidden'); END;
CREATE TRIGGER kuifje_fiches_no_update BEFORE UPDATE ON kuifje_fiches
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_fiches_no_delete BEFORE DELETE ON kuifje_fiches
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_fiches_no_replace BEFORE INSERT ON kuifje_fiches
WHEN EXISTS(SELECT 1 FROM kuifje_fiches WHERE queue_item_id=NEW.queue_item_id OR (job_id=NEW.job_id AND fiche_id=NEW.fiche_id))
BEGIN SELECT RAISE(ABORT,'Kuifje replacement forbidden'); END;
CREATE TRIGGER kuifje_results_no_update BEFORE UPDATE ON kuifje_results
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_results_no_delete BEFORE DELETE ON kuifje_results
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_results_no_replace BEFORE INSERT ON kuifje_results
WHEN EXISTS(SELECT 1 FROM kuifje_results WHERE job_id=NEW.job_id OR attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT,'Kuifje replacement forbidden'); END;
