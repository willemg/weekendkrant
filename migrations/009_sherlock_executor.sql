-- Immutable assignments and activation receipts; no legacy backfill.
CREATE TABLE sherlock_contracts (
    ref TEXT PRIMARY KEY,
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 65536)
);
CREATE TABLE sherlock_assignments (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    topic INTEGER NOT NULL CHECK(topic IN (1,2,3)),
    date TEXT NOT NULL,
    role_contract_ref TEXT NOT NULL REFERENCES sherlock_contracts(ref),
    output_contract_ref TEXT NOT NULL REFERENCES sherlock_contracts(ref)
);
CREATE TABLE sherlock_job_runs (
    run_id INTEGER PRIMARY KEY REFERENCES sherlock_runs(id),
    job_id INTEGER NOT NULL REFERENCES sherlock_assignments(job_id),
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES job_attempts(id)
);
CREATE INDEX sherlock_job_runs_by_job ON sherlock_job_runs(job_id,attempt_id);
CREATE TRIGGER sherlock_job_run_validate BEFORE INSERT ON sherlock_job_runs
WHEN NOT EXISTS(SELECT 1 FROM job_attempts a JOIN sherlock_runs r ON r.id=NEW.run_id
    JOIN sherlock_assignments s ON s.job_id=NEW.job_id
    WHERE a.id=NEW.attempt_id AND a.job_id=NEW.job_id AND a.status='running'
    AND r.status='running' AND r.topic=s.topic)
BEGIN SELECT RAISE(ABORT,'invalid Sherlock job/run binding'); END;
CREATE TABLE sherlock_activations (
    operation_id TEXT PRIMARY KEY CHECK(length(operation_id) BETWEEN 1 AND 128),
    activation_id TEXT NOT NULL UNIQUE CHECK(length(activation_id) BETWEEN 1 AND 128),
    job_id INTEGER REFERENCES jobs(id),
    attempt_id INTEGER REFERENCES job_attempts(id),
    response TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    CHECK((job_id IS NULL) = (attempt_id IS NULL))
);
CREATE TRIGGER sherlock_contracts_no_update BEFORE UPDATE ON sherlock_contracts
BEGIN SELECT RAISE(ABORT,'immutable Sherlock executor audit'); END;
CREATE TRIGGER sherlock_contracts_no_delete BEFORE DELETE ON sherlock_contracts
BEGIN SELECT RAISE(ABORT,'immutable Sherlock executor audit'); END;
CREATE TRIGGER sherlock_contracts_no_replace BEFORE INSERT ON sherlock_contracts
WHEN EXISTS(SELECT 1 FROM sherlock_contracts WHERE ref=NEW.ref)
BEGIN SELECT RAISE(ABORT,'Sherlock executor replacement forbidden'); END;
CREATE TRIGGER sherlock_assignments_no_update BEFORE UPDATE ON sherlock_assignments
BEGIN SELECT RAISE(ABORT,'immutable Sherlock executor audit'); END;
CREATE TRIGGER sherlock_assignments_no_delete BEFORE DELETE ON sherlock_assignments
BEGIN SELECT RAISE(ABORT,'immutable Sherlock executor audit'); END;
CREATE TRIGGER sherlock_assignments_no_replace BEFORE INSERT ON sherlock_assignments
WHEN EXISTS(SELECT 1 FROM sherlock_assignments WHERE job_id=NEW.job_id)
BEGIN SELECT RAISE(ABORT,'Sherlock executor replacement forbidden'); END;
CREATE TRIGGER sherlock_job_runs_no_update BEFORE UPDATE ON sherlock_job_runs
BEGIN SELECT RAISE(ABORT,'immutable Sherlock executor audit'); END;
CREATE TRIGGER sherlock_job_runs_no_delete BEFORE DELETE ON sherlock_job_runs
BEGIN SELECT RAISE(ABORT,'immutable Sherlock executor audit'); END;
CREATE TRIGGER sherlock_job_runs_no_replace BEFORE INSERT ON sherlock_job_runs
WHEN EXISTS(SELECT 1 FROM sherlock_job_runs WHERE run_id=NEW.run_id OR attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT,'Sherlock executor replacement forbidden'); END;
CREATE TRIGGER sherlock_activations_no_update BEFORE UPDATE ON sherlock_activations
BEGIN SELECT RAISE(ABORT,'immutable Sherlock executor audit'); END;
CREATE TRIGGER sherlock_activations_no_delete BEFORE DELETE ON sherlock_activations
BEGIN SELECT RAISE(ABORT,'immutable Sherlock executor audit'); END;
CREATE TRIGGER sherlock_activations_no_replace BEFORE INSERT ON sherlock_activations
WHEN EXISTS(SELECT 1 FROM sherlock_activations WHERE operation_id=NEW.operation_id OR activation_id=NEW.activation_id)
BEGIN SELECT RAISE(ABORT,'Sherlock executor replacement forbidden'); END;
