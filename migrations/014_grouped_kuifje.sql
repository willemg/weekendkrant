-- Preserve every frozen snapshot and historical effect while changing relations.
CREATE TEMP TABLE k_assignments AS SELECT * FROM kuifje_assignments;
CREATE TEMP TABLE k_fiches AS SELECT * FROM kuifje_fiches;
CREATE TEMP TABLE k_results AS SELECT * FROM kuifje_results;
DROP TABLE kuifje_results;
DROP TABLE kuifje_fiches;
DROP TABLE kuifje_assignments;
CREATE TABLE kuifje_assignments (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    snapshot TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes > 0),
    tokens INTEGER NOT NULL CHECK(tokens > 0),
    tokenizer TEXT NOT NULL CHECK(tokenizer='cl100k_base')
);
CREATE TABLE kuifje_assignment_missions (
    job_id INTEGER NOT NULL REFERENCES kuifje_assignments(job_id),
    position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 4),
    mission_id TEXT NOT NULL UNIQUE REFERENCES kuifje_missions(mission_id),
    PRIMARY KEY(job_id,position),
    UNIQUE(job_id,mission_id)
);
CREATE TABLE kuifje_fiches (
    queue_item_id INTEGER PRIMARY KEY REFERENCES ingress_queue(id),
    job_id INTEGER NOT NULL REFERENCES kuifje_assignments(job_id),
    attempt_id INTEGER NOT NULL REFERENCES job_attempts(id),
    mission_id TEXT NOT NULL,
    fiche_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    UNIQUE(job_id,mission_id,fiche_id),
    FOREIGN KEY(job_id,mission_id) REFERENCES kuifje_assignment_missions(job_id,mission_id)
);
CREATE TABLE kuifje_results (
    job_id INTEGER PRIMARY KEY REFERENCES kuifje_assignments(job_id),
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES job_attempts(id),
    content TEXT NOT NULL,
    bytes INTEGER NOT NULL CHECK(bytes > 0),
    tokens INTEGER NOT NULL CHECK(tokens > 0),
    tokenizer TEXT NOT NULL CHECK(tokenizer='cl100k_base')
);
INSERT INTO kuifje_assignments SELECT job_id,snapshot,sha256,bytes,tokens,tokenizer FROM k_assignments;
INSERT INTO kuifje_assignment_missions SELECT job_id,1,mission_id FROM k_assignments;
INSERT INTO kuifje_fiches SELECT f.queue_item_id,f.job_id,f.attempt_id,a.mission_id,f.fiche_id,f.payload_sha256
    FROM k_fiches f JOIN k_assignments a USING(job_id);
INSERT INTO kuifje_results SELECT * FROM k_results;
DROP TABLE k_results;
DROP TABLE k_fiches;
DROP TABLE k_assignments;
CREATE TRIGGER kuifje_assignments_no_update BEFORE UPDATE ON kuifje_assignments
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_assignments_no_delete BEFORE DELETE ON kuifje_assignments
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_assignments_no_replace BEFORE INSERT ON kuifje_assignments
WHEN EXISTS(SELECT 1 FROM kuifje_assignments WHERE job_id=NEW.job_id)
BEGIN SELECT RAISE(ABORT,'Kuifje replacement forbidden'); END;
CREATE TRIGGER kuifje_fiches_no_update BEFORE UPDATE ON kuifje_fiches
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_fiches_no_delete BEFORE DELETE ON kuifje_fiches
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_fiches_no_replace BEFORE INSERT ON kuifje_fiches
WHEN EXISTS(SELECT 1 FROM kuifje_fiches WHERE queue_item_id=NEW.queue_item_id OR (job_id=NEW.job_id AND mission_id=NEW.mission_id AND fiche_id=NEW.fiche_id))
BEGIN SELECT RAISE(ABORT,'Kuifje replacement forbidden'); END;
CREATE TRIGGER kuifje_results_no_update BEFORE UPDATE ON kuifje_results
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_results_no_delete BEFORE DELETE ON kuifje_results
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_results_no_replace BEFORE INSERT ON kuifje_results
WHEN EXISTS(SELECT 1 FROM kuifje_results WHERE job_id=NEW.job_id OR attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT,'Kuifje replacement forbidden'); END;
CREATE TRIGGER kuifje_assignment_missions_no_update BEFORE UPDATE ON kuifje_assignment_missions
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_assignment_missions_no_delete BEFORE DELETE ON kuifje_assignment_missions
BEGIN SELECT RAISE(ABORT,'immutable Kuifje audit'); END;
CREATE TRIGGER kuifje_assignment_missions_no_replace BEFORE INSERT ON kuifje_assignment_missions
WHEN EXISTS(SELECT 1 FROM kuifje_assignment_missions WHERE mission_id=NEW.mission_id
    OR (job_id=NEW.job_id AND position=NEW.position))
BEGIN SELECT RAISE(ABORT,'Kuifje replacement forbidden'); END;
-- Historical one-mission jobs remain valid; new memberships must share provenance.
CREATE TRIGGER kuifje_assignment_missions_same_origin BEFORE INSERT ON kuifje_assignment_missions
WHEN EXISTS(
    SELECT 1 FROM kuifje_assignment_missions x
    JOIN kuifje_missions prior ON prior.mission_id=x.mission_id
    JOIN kuifje_missions next ON next.mission_id=NEW.mission_id
    WHERE x.job_id=NEW.job_id AND (prior.dossier_id<>next.dossier_id
        OR prior.state_version<>next.state_version OR prior.producer_job_id<>next.producer_job_id)
)
BEGIN SELECT RAISE(ABORT,'mixed Kuifje mission origin'); END;
