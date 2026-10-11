
CREATE TABLE part_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL UNIQUE,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(part_id,revision) REFERENCES part_revisions(part_id,revision)
);
CREATE TRIGGER validate_part_offer BEFORE INSERT ON part_offers
BEGIN
    SELECT RAISE(ABORT,'Part already offered') WHERE EXISTS
        (SELECT 1 FROM part_offers WHERE part_id=NEW.part_id OR id=NEW.id);
    SELECT RAISE(ABORT,'Offer requires registered active revision') WHERE NOT EXISTS
        (SELECT 1 FROM parts p JOIN part_revisions r
         ON r.part_id=p.id AND r.revision=p.active_revision
         WHERE p.id=NEW.part_id AND p.active_revision=NEW.revision);
END;
CREATE TRIGGER seal_part_offer AFTER INSERT ON part_offers
BEGIN UPDATE parts SET is_open=0 WHERE id=NEW.part_id AND is_open=1; END;
CREATE TRIGGER immutable_part_offers_update BEFORE UPDATE ON part_offers
BEGIN SELECT RAISE(ABORT,'Immutable offer'); END;
CREATE TRIGGER immutable_part_offers_delete BEFORE DELETE ON part_offers
BEGIN SELECT RAISE(ABORT,'Immutable offer'); END;
CREATE TRIGGER offered_active_revision BEFORE UPDATE OF active_revision ON parts
WHEN EXISTS (SELECT 1 FROM part_offers WHERE part_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Offered revision cannot change'); END;
