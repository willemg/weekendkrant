CREATE TABLE sherlock_fiches (
    queue_item_id INTEGER PRIMARY KEY REFERENCES ingress_queue(id),
    run_id INTEGER NOT NULL REFERENCES sherlock_runs(id)
);
CREATE INDEX sherlock_fiches_by_run ON sherlock_fiches(run_id,queue_item_id);
CREATE TRIGGER sherlock_fiches_validate BEFORE INSERT ON sherlock_fiches
BEGIN
    SELECT RAISE(ABORT,'Fiche already attributed') WHERE EXISTS
        (SELECT 1 FROM sherlock_fiches WHERE queue_item_id=NEW.queue_item_id);
    SELECT RAISE(ABORT,'Fiche requires existing queue item and running run') WHERE NOT EXISTS
        (SELECT 1 FROM ingress_queue q JOIN sherlock_runs r ON r.id=NEW.run_id
         WHERE q.id=NEW.queue_item_id AND r.status='running');
END;
CREATE TRIGGER sherlock_fiches_immutable_update BEFORE UPDATE ON sherlock_fiches
BEGIN SELECT RAISE(ABORT,'Immutable fiche provenance'); END;
CREATE TRIGGER sherlock_fiches_immutable_delete BEFORE DELETE ON sherlock_fiches
BEGIN SELECT RAISE(ABORT,'Immutable fiche provenance'); END;
