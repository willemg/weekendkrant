-- Independent generic storage; no legacy backfill or runtime routing.
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL CHECK(length(role) BETWEEN 1 AND 128),
    status TEXT NOT NULL DEFAULT 'ready' CHECK(status IN ('ready','running','blocked','succeeded','failed')),
    input_refs TEXT NOT NULL,
    output_contract_ref TEXT NOT NULL,
    output_refs TEXT NOT NULL DEFAULT '[]',
    lease_seconds INTEGER NOT NULL CHECK(lease_seconds BETWEEN 1 AND 86400),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    CHECK((status IN ('succeeded','failed')) = (finished_at IS NOT NULL))
);
CREATE INDEX jobs_status ON jobs(status,id);
CREATE TABLE job_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    activation_id TEXT NOT NULL UNIQUE,
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('running','expired','uncertain','succeeded','failed')),
    started_at TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    finished_at TEXT,
    output_refs TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    CHECK(lease_until > started_at),
    CHECK((status = 'running') = (finished_at IS NULL))
);
CREATE UNIQUE INDEX job_attempts_one_running ON job_attempts(job_id) WHERE status='running';
CREATE INDEX job_attempts_expiry ON job_attempts(status,lease_until);
CREATE TABLE job_recoveries (
    attempt_id INTEGER PRIMARY KEY REFERENCES job_attempts(id),
    decision TEXT NOT NULL CHECK(decision IN ('retry','succeeded','failed')),
    evidence_ref TEXT NOT NULL CHECK(length(evidence_ref) BETWEEN 1 AND 512),
    output_refs TEXT NOT NULL,
    reconciled_at TEXT NOT NULL
);
CREATE TRIGGER job_identity_immutable BEFORE UPDATE ON jobs
WHEN NEW.id != OLD.id OR NEW.role != OLD.role OR NEW.input_refs != OLD.input_refs
 OR NEW.output_contract_ref != OLD.output_contract_ref OR NEW.lease_seconds != OLD.lease_seconds
 OR NEW.created_at != OLD.created_at
BEGIN SELECT RAISE(ABORT,'immutable job identity'); END;
CREATE TRIGGER job_no_delete BEFORE DELETE ON jobs
BEGIN SELECT RAISE(ABORT,'job audit retained'); END;
CREATE TRIGGER job_attempt_identity_immutable BEFORE UPDATE ON job_attempts
WHEN NEW.id != OLD.id OR NEW.job_id != OLD.job_id OR NEW.activation_id != OLD.activation_id
 OR NEW.token != OLD.token OR NEW.started_at != OLD.started_at OR NEW.lease_until != OLD.lease_until
 OR OLD.status != 'running'
BEGIN SELECT RAISE(ABORT,'immutable attempt identity or closed attempt'); END;
CREATE TRIGGER job_attempt_no_delete BEFORE DELETE ON job_attempts
BEGIN SELECT RAISE(ABORT,'attempt audit retained'); END;
CREATE TRIGGER job_recovery_no_update BEFORE UPDATE ON job_recoveries
BEGIN SELECT RAISE(ABORT,'immutable reconciliation'); END;
CREATE TRIGGER job_recovery_no_delete BEFORE DELETE ON job_recoveries
BEGIN SELECT RAISE(ABORT,'immutable reconciliation'); END;
CREATE TRIGGER job_terminal_immutable BEFORE UPDATE ON jobs
WHEN OLD.status IN ('succeeded','failed')
BEGIN SELECT RAISE(ABORT,'terminal job immutable'); END;
CREATE TRIGGER job_no_replace BEFORE INSERT ON jobs
WHEN EXISTS(SELECT 1 FROM jobs WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'job replacement forbidden'); END;
CREATE TRIGGER job_attempt_no_replace BEFORE INSERT ON job_attempts
WHEN EXISTS(SELECT 1 FROM job_attempts WHERE id=NEW.id OR activation_id=NEW.activation_id OR token=NEW.token)
BEGIN SELECT RAISE(ABORT,'attempt replacement forbidden'); END;
CREATE TRIGGER job_recovery_no_replace BEFORE INSERT ON job_recoveries
WHEN EXISTS(SELECT 1 FROM job_recoveries WHERE attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT,'reconciliation replacement forbidden'); END;
