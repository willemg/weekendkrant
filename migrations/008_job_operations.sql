-- Receipts and mutations commit together. Tokens are never copied into audit.
CREATE TABLE job_operations (
    operation_id TEXT PRIMARY KEY CHECK(length(operation_id) BETWEEN 1 AND 128),
    operation TEXT NOT NULL CHECK(operation IN ('claim','finish','abandon','reconcile')),
    request_digest TEXT NOT NULL CHECK(length(request_digest)=64),
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    attempt_id INTEGER REFERENCES job_attempts(id),
    response TEXT NOT NULL,
    confirmed_at TEXT NOT NULL
);
CREATE TRIGGER job_operation_no_update BEFORE UPDATE ON job_operations
BEGIN SELECT RAISE(ABORT,'immutable operation receipt'); END;
CREATE TRIGGER job_operation_no_delete BEFORE DELETE ON job_operations
BEGIN SELECT RAISE(ABORT,'operation audit retained'); END;
CREATE TRIGGER job_operation_no_replace BEFORE INSERT ON job_operations
WHEN EXISTS(SELECT 1 FROM job_operations WHERE operation_id=NEW.operation_id)
BEGIN SELECT RAISE(ABORT,'operation replacement forbidden'); END;
