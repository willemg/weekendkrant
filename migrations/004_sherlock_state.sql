CREATE TABLE sherlock_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic INTEGER NOT NULL CHECK(typeof(topic)='integer' AND topic IN (1,2,3)),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','completed','failed')),
    CHECK((status='running' AND finished_at IS NULL)
       OR (status IN ('completed','failed') AND finished_at IS NOT NULL))
);

CREATE TABLE sherlock_sources (
    canonical_url TEXT NOT NULL PRIMARY KEY,
    original_url TEXT NOT NULL,
    topic INTEGER NOT NULL CHECK(typeof(topic)='integer' AND topic IN (1,2,3)),
    run_id INTEGER NOT NULL REFERENCES sherlock_runs(id),
    reviewed_at TEXT NOT NULL,
    title TEXT,
    outcome TEXT NOT NULL CHECK(length(trim(outcome)) > 0),
    rationale TEXT NOT NULL CHECK(length(trim(rationale)) > 0)
);
