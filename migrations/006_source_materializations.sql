CREATE TABLE source_materializations (
    queue_id INTEGER PRIMARY KEY REFERENCES source_archive(queue_id),
    materialized_at TEXT NOT NULL
);
CREATE INDEX source_materializations_by_time ON source_materializations(materialized_at,queue_id);
CREATE TRIGGER source_materializations_validate BEFORE INSERT ON source_materializations
BEGIN
    SELECT RAISE(ABORT,'Materialization already recorded') WHERE EXISTS
        (SELECT 1 FROM source_materializations WHERE queue_id=NEW.queue_id);
    SELECT RAISE(ABORT,'Materialization requires archived processed queue item') WHERE NOT EXISTS
        (SELECT 1 FROM source_archive a JOIN ingress_queue q ON q.id=a.queue_id
         WHERE a.queue_id=NEW.queue_id AND q.status='processed');
END;
CREATE TRIGGER source_materializations_immutable_update BEFORE UPDATE ON source_materializations
BEGIN SELECT RAISE(ABORT,'Immutable materialization time'); END;
CREATE TRIGGER source_materializations_immutable_delete BEFORE DELETE ON source_materializations
BEGIN SELECT RAISE(ABORT,'Immutable materialization time'); END;
