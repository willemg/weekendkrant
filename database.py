"""Canonical, additive SQLite migrations shared by CLI and runtime."""
import argparse
from contextlib import closing
from pathlib import Path
import re
import sqlite3

SCHEMA_VERSION = 11
MIGRATIONS = Path(__file__).resolve().parent / 'migrations'


def migration_sql(version):
    files = sorted(MIGRATIONS.glob(f'{version:03d}_*.sql'))
    if len(files) != 1:
        raise ValueError(f'Verwacht precies één migratie voor versie {version}')
    return files[0].read_text(encoding='utf-8')


def sql_tokens(sql):
    """Ignore formatting and SQL keyword case, preserving quoted literals."""
    if sql is None:
        return None
    tokens = re.findall(r"'(?:''|[^'])*'|\w+|[^\s\w]", sql)
    return tuple(t if t.startswith("'") else t.lower() for t in tokens if t != ';')


def statements(script):
    """Keep trigger bodies intact without executescript's implicit commit."""
    pending = ''
    for char in script:
        pending += char
        if char == ';' and sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    if pending.strip():
        # Comments and whitespace may follow the final statement.
        if re.sub(r'--[^\n]*', '', pending).strip():
            raise ValueError('Onvolledige SQL-migratie')


def validate_runtime_tables(db):
    """Adopt only the actual legacy schema, never silently bless drift."""
    with closing(sqlite3.connect(':memory:')) as expected:
        expected.executescript(migration_sql(3))
        for name, sql in expected.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            existing = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if existing is not None and sql_tokens(existing[0]) != sql_tokens(sql):
                raise ValueError(f'Afwijkend legacy-schema voor {name}; migratie afgebroken')


def migrate(db):
    """Migrate an idle connection; commit each step or roll it back entirely.

    The version is read under the write lock to serialize concurrent startup.
    A failed later step preserves earlier successfully committed versions.
    """
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError('Onbekende nieuwere SQLite schema-versie')
    if db.in_transaction:
        raise ValueError('Migratie vereist een connection zonder actieve transactie')
    db.execute('PRAGMA foreign_keys=ON')
    if version == SCHEMA_VERSION:
        return
    while True:
        db.execute('BEGIN IMMEDIATE')
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError('Onbekende nieuwere SQLite schema-versie')
            if version == SCHEMA_VERSION:
                db.rollback()
                return
            target = version + 1
            if target == 3:
                validate_runtime_tables(db)
            for statement in statements(migration_sql(target)):
                db.execute(statement)
            db.execute(f'PRAGMA user_version={target}')
            db.commit()
        except Exception:
            db.rollback()
            raise
        if target == SCHEMA_VERSION:
            return


def main():
    parser = argparse.ArgumentParser(description='Bouw of migreer het Weekendkrant-schema')
    parser.add_argument('--db', required=True, type=Path)
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(args.db)) as db:
        migrate(db)
        print(f'Schema versie {SCHEMA_VERSION}: {args.db}')


if __name__ == '__main__':
    main()
