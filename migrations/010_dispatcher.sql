CREATE TABLE executor_activations (
    operation_id TEXT PRIMARY KEY CHECK(length(operation_id) BETWEEN 1 AND 128),
    activation_id TEXT NOT NULL UNIQUE CHECK(length(activation_id) BETWEEN 1 AND 128),
    job_id INTEGER REFERENCES jobs(id),
    attempt_id INTEGER REFERENCES job_attempts(id),
    response TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    CHECK((job_id IS NULL) = (attempt_id IS NULL))
);
INSERT INTO executor_activations
SELECT operation_id,activation_id,job_id,attempt_id,
 CASE WHEN attempt_id IS NULL THEN response ELSE json_set(response,
 '$.role_contract',(SELECT content FROM sherlock_contracts WHERE ref=json_extract(response,'$.role_contract_ref')),
 '$.output_contract',(SELECT content FROM sherlock_contracts WHERE ref=json_extract(response,'$.output_contract_ref'))) END,
 confirmed_at FROM sherlock_activations;
CREATE TRIGGER executor_activations_no_update BEFORE UPDATE ON executor_activations
BEGIN SELECT RAISE(ABORT,'immutable executor audit'); END;
CREATE TRIGGER executor_activations_no_delete BEFORE DELETE ON executor_activations
BEGIN SELECT RAISE(ABORT,'immutable executor audit'); END;
CREATE TRIGGER executor_activations_no_replace BEFORE INSERT ON executor_activations
WHEN EXISTS(SELECT 1 FROM executor_activations WHERE operation_id=NEW.operation_id OR activation_id=NEW.activation_id)
BEGIN SELECT RAISE(ABORT,'executor replacement forbidden'); END;

CREATE TABLE dispatcher_policy (
    id INTEGER PRIMARY KEY CHECK(id=1),
    paused INTEGER NOT NULL CHECK(paused IN (0,1)),
    max_running INTEGER NOT NULL CHECK(max_running BETWEEN 1 AND 64)
);
INSERT INTO dispatcher_policy VALUES (1,0,1);
CREATE TRIGGER dispatcher_policy_no_delete BEFORE DELETE ON dispatcher_policy
BEGIN SELECT RAISE(ABORT,'dispatcher policy required'); END;
