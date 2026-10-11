CREATE TABLE IF NOT EXISTS days (
    day TEXT PRIMARY KEY, week TEXT NOT NULL, status TEXT NOT NULL,
    commit_sha TEXT, manifest_sha256 TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY, day TEXT NOT NULL, status TEXT NOT NULL,
    error TEXT, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS threads (
    path TEXT PRIMARY KEY, day TEXT NOT NULL REFERENCES days(day),
    topic INTEGER NOT NULL, part INTEGER NOT NULL, sha256 TEXT NOT NULL,
    tokens INTEGER NOT NULL, tokenizer TEXT NOT NULL, reserved_tokens INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
    day TEXT NOT NULL REFERENCES days(day), source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL, thread_path TEXT NOT NULL REFERENCES threads(path),
    position INTEGER NOT NULL, PRIMARY KEY(day, source_path));

CREATE TABLE IF NOT EXISTS ingress_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
