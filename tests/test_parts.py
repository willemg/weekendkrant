from datetime import datetime, timezone
import ast
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import daily
from ingress_queue import IngressQueue


class PartFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'app'
        self.root.mkdir()
        self.db = self.base / 'queue.db'
        self.output = self.base / 'parts'
        self.lock = self.base / 'lock'
        self.queue = IngressQueue(self.db)

    def add(self, day='2026-10-05', topic=2, content='bron é\n'):
        return self.queue.add(dict(schema_version=1, date=day, topic=topic, content=content))

    def run_day(self, day=6):
        return daily.run_daily(self.root, self.db, self.output,
                               datetime(2026, 10, day, 10, tzinfo=timezone.utc), self.lock)

    def rows(self, sql, args=()):
        with sqlite3.connect(self.db) as db:
            return db.execute(sql, args).fetchall()

    def active(self):
        return self.rows('SELECT week,topic,part,is_open,active_revision FROM parts ORDER BY week,topic,part')

    def members(self, revision):
        return self.rows('SELECT queue_id,position FROM revision_sources WHERE revision=? ORDER BY position', (revision,))



class PartTests(PartFixture):
    def test_cross_day_revision_and_exact_serialization(self):
        a = self.add(content='A é\n')
        b = self.add(content='B')
        self.assertEqual(self.run_day(5)['threads'], 1)
        first = self.output / '2026_W41/topic_2/part_0001/rev_0001.txt'
        before = first.read_bytes()
        provenance = self.rows('SELECT * FROM part_revisions')
        membership = self.members(1)
        c = self.add('2026-10-06', content='C')
        self.run_day()
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 1, 2)])
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(self.rows('SELECT * FROM part_revisions WHERE revision=1'), provenance)
        self.assertEqual(self.members(1), membership)
        self.assertEqual(self.members(2), [(a, 0), (b, 1), (c, 2)])
        second = first.with_name('rev_0002.txt').read_text()
        expected = 'WEEKENDKRANT-PART-1\nweek: 2026_W41\ntopic: 2\npart: 1\nrevision: 2\ntokenizer: cl100k_base\nreserved_tokens: 5000\n\n'
        for identity, day, content in ((a, '2026-10-05', 'A é\n'), (b, '2026-10-05', 'B'), (c, '2026-10-06', 'C')):
            data = content.encode()
            expected += f'\n--- SOURCE queue:{identity} date={day} sha256={hashlib.sha256(data).hexdigest()} bytes={len(data)} ---\n{content}\n--- END SOURCE ---\n'
        self.assertEqual(second, expected)
        tokens, digest = self.rows('SELECT tokens,sha256 FROM part_revisions WHERE revision=2')[0]
        self.assertEqual(tokens, daily.token_count(second))
        self.assertEqual(digest, hashlib.sha256(second.encode()).hexdigest())
        for table in ('days', 'threads', 'sources', 'attempts'):
            self.assertEqual(self.rows('SELECT * FROM ' + table), [])

    def test_numeric_date_order_and_late_append(self):
        for i in range(12):
            self.add('2026-10-06' if i % 2 else '2026-10-05', content=str(i))
        self.run_day()
        self.assertEqual([i for i, _ in self.members(1)], list(range(1, 13, 2)) + list(range(2, 13, 2)))
        late = self.add('2026-10-05', content='late')
        self.run_day(7)
        self.assertEqual(self.members(2), self.members(1) + [(late, 12)])

    def test_overflow_closes_and_never_reopens(self):
        # Use the real serialization with a small, deterministic character budget.
        from parts import render
        from datetime import date
        f = daily.queue_fiche(1, dict(schema_version=1, topic=2, date='2026-10-05', content='x' * 100), date(2026, 10, 5))
        budget = len(render([f], '2026_W41', 2, 1, 1, 5000)) + 10
        a = self.add(content='x' * 100)
        b = self.add(content='y' * 100)
        with patch.object(daily, 'token_count', side_effect=len), patch.object(daily, 'LIMIT', budget + 5000):
            self.run_day(5)
            self.assertEqual(self.active(), [('2026_W41', 2, 1, 0, 1), ('2026_W41', 2, 2, 1, 1)])
            self.add(content='z' * 100)
            self.run_day()
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 0, 1), ('2026_W41', 2, 2, 0, 1), ('2026_W41', 2, 3, 1, 1)])
        self.assertEqual(self.rows('SELECT queue_id FROM revision_sources WHERE part_id=1'), [(a,)])
        self.assertEqual(self.rows('SELECT queue_id FROM revision_sources WHERE part_id=2'), [(b,)])
        self.add(content='tiny')
        self.run_day(7)
        self.assertEqual(self.active()[-1], ('2026_W41', 2, 3, 1, 2))

    def test_topics_weeks_backlog_and_late_old_week(self):
        self.add('2026-10-11')
        self.add('2026-10-12')
        self.add('2026-10-11', topic=3)
        self.add('2025-12-29', topic=1)
        self.run_day(12)
        self.assertEqual([(w, t) for w, t, *_ in self.active()], [('2026_W01', 1), ('2026_W41', 2), ('2026_W41', 3), ('2026_W42', 2)])
        self.add('2026-10-10')
        self.run_day(13)
        self.assertEqual(self.rows("SELECT active_revision FROM parts WHERE week='2026_W41' AND topic=2"), [(2,)])

    def test_archive_exact_bytes_survives_queue_deletion_and_refuses_change(self):
        data = 'é\r\n漢字\n\n'
        identity = self.add(content=data)
        self.run_day()
        self.assertEqual(self.rows('SELECT queue_id,schema_version,date,topic,content,sha256 FROM source_archive'),
                         [(identity, 1, '2026-10-05', 2, data.encode(), hashlib.sha256(data.encode()).hexdigest())])
        self.assertEqual(self.rows('PRAGMA foreign_key_list(source_archive)'), [])
        with sqlite3.connect(self.db) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('DELETE FROM ingress_queue')
            for sql in ('UPDATE source_archive SET content=x\'61\'', 'DELETE FROM source_archive'):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
        self.add('2026-10-06', content='next')
        self.run_day()
        self.assertIn(data.encode(), (self.output / '2026_W41/topic_2/part_0001/rev_0002.txt').read_bytes())

    def test_schema_constraints_and_immutable_registered_revision(self):
        self.add()
        self.run_day()
        with sqlite3.connect(self.db) as db:
            db.execute('PRAGMA foreign_keys=ON')
            for sql in ("INSERT INTO parts(week,topic,part,is_open) VALUES ('2026_W41',2,2,1)",
                        "INSERT INTO parts(week,topic,part,is_open) VALUES ('2026_W41',2,1,0)",
                        'UPDATE part_revisions SET tokens=0', 'DELETE FROM part_revisions',
                        'UPDATE revision_sources SET position=9', 'DELETE FROM revision_sources',
                        'INSERT INTO revision_sources VALUES (1,1,9,1)',
                        'UPDATE parts SET active_revision=99', 'UPDATE parts SET week=\'2026_W42\''):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)

    def test_failure_and_retry_preserve_active_and_orphan_bytes(self):
        self.add()
        self.run_day(5)
        first = self.output / '2026_W41/topic_2/part_0001/rev_0001.txt'
        before = first.read_bytes()
        old = self.rows('SELECT * FROM part_revisions')
        self.add('2026-10-06')
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER refuse BEFORE UPDATE OF active_revision ON parts BEGIN SELECT RAISE(ABORT,'pointer failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'pointer failure'):
            self.run_day()
        orphan = first.with_name('rev_0002.txt')
        planned = orphan.read_bytes()
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 1, 1)])
        self.assertEqual(self.rows('SELECT * FROM part_revisions'), old)
        self.assertEqual(self.rows('SELECT status FROM ingress_queue ORDER BY id'), [('processed',), ('pending',)])
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER refuse')
        self.run_day(7)
        self.assertEqual(orphan.read_bytes(), planned)
        self.assertEqual(first.read_bytes(), before)

    def test_changed_part_snapshot_is_refused(self):
        self.add()
        self.run_day(5)
        self.add('2026-10-06')
        original = daily.write_thread
        def change(path, data, **kwargs):
            with sqlite3.connect(self.db, timeout=0.05) as db:
                db.execute('UPDATE parts SET is_open=0')
            original(path, data, **kwargs)
        with patch.object(daily, 'write_thread', side_effect=change), self.assertRaisesRegex(ValueError, 'Partstaat'):
            self.run_day()
        self.assertEqual(self.rows('SELECT status FROM ingress_queue ORDER BY id'), [('processed',), ('pending',)])
        self.assertEqual(self.rows('SELECT count(*) FROM part_revisions'), [(1,)])

    def test_oversized_snapshot_all_pending(self):
        self.add(topic=1)
        self.add(topic=2, content='x ' * 40000)
        with self.assertRaisesRegex(ValueError, 'fiche'):
            self.run_day()
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('pending',), ('pending',)])
        self.assertEqual(self.rows('SELECT * FROM parts'), [])

    def test_registered_file_is_never_overwritten(self):
        self.add()
        self.run_day(5)
        path = next(self.output.rglob('*.txt'))
        data = path.read_bytes()
        with self.assertRaises(ValueError):
            daily.write_thread(path, b'different')
        self.assertEqual(path.read_bytes(), data)

    def test_same_queue_id_with_different_bytes_is_refused(self):
        from parts import PartStore
        from datetime import date
        identity = self.add(content='original')
        self.run_day()
        db = daily.database(self.db)
        try:
            changed = daily.queue_fiche(identity, dict(schema_version=1, topic=2, date='2026-10-05', content='changed'), date(2026, 10, 5))
            with self.assertRaisesRegex(ValueError, 'Andere bronbytes'), db:
                PartStore(db).archive(changed)
        finally:
            db.close()
        self.assertEqual(self.rows('SELECT content FROM source_archive'), [(b'original',)])

    def test_every_revision_is_reproducible_from_archive(self):
        from parts import render
        self.add(content='A é\r\n')
        self.run_day(5)
        self.add('2026-10-06', content='B')
        self.run_day()
        for identity, revision, path, digest, tokens, tokenizer, reserve in self.rows('SELECT * FROM part_revisions'):
            from daily import Fiche
            rows = self.rows('''SELECT a.queue_id,a.topic,a.content,a.sha256,a.date,a.schema_version
                FROM revision_sources m JOIN source_archive a ON a.queue_id=m.queue_id
                WHERE m.part_id=? AND m.revision=? ORDER BY m.position''', (identity, revision))
            sources = [Fiche(f'queue:{i}', topic, content, hash_, day, version) for i, topic, content, hash_, day, version in rows]
            text = render(sources, '2026_W41', 2, 1, revision, reserve)
            self.assertEqual(text.encode(), Path(path).read_bytes())
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), digest)
            self.assertEqual(daily.token_count(text), tokens)
            self.assertEqual(tokenizer, 'cl100k_base')

    def test_changed_snapshot_can_replace_only_unregistered_orphan(self):
        self.add()
        self.run_day(5)
        original = self.output / '2026_W41/topic_2/part_0001/rev_0001.txt'
        before = original.read_bytes()
        identity = self.add('2026-10-06', content='B')
        with sqlite3.connect(self.db) as db:
            db.execute(f"CREATE TRIGGER refuse BEFORE UPDATE ON ingress_queue WHEN NEW.id={identity} BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_day()
        self.add('2026-10-06', content='C')
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER refuse')
        self.run_day()
        self.assertEqual(original.read_bytes(), before)
        self.assertIn(b'C', original.with_name('rev_0002.txt').read_bytes())
        self.assertEqual(self.members(2), [(1, 0), (2, 1), (3, 2)])

    def test_changed_active_revision_is_refused(self):
        self.add()
        self.run_day(5)
        self.add('2026-10-06')
        original = daily.write_thread
        def advance(path, data, **kwargs):
            with sqlite3.connect(self.db, timeout=0.05) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute("INSERT INTO part_revisions SELECT part_id,2,path || '.external',sha256,tokens,tokenizer,reserved_tokens FROM part_revisions WHERE revision=1")
                db.execute('INSERT INTO revision_sources SELECT part_id,2,position,queue_id FROM revision_sources WHERE revision=1')
                db.execute('UPDATE parts SET active_revision=2')
            original(path, data, **kwargs)
        with patch.object(daily, 'write_thread', side_effect=advance), self.assertRaisesRegex(ValueError, 'Partstaat'):
            self.run_day()
        self.assertEqual(self.rows('SELECT status FROM ingress_queue ORDER BY id'), [('processed',), ('pending',)])
        # Only the externally committed revision exists; this run archives no new source.
        self.assertEqual(self.rows('SELECT count(*) FROM source_archive'), [(1,)])
        self.assertEqual(self.rows('SELECT path FROM part_revisions WHERE revision=2'),
                         [(str(self.output / '2026_W41/topic_2/part_0001/rev_0001.txt') + '.external',)])

    def closed_part_from_runtime(self):
        for content in ('x' * 100, 'y' * 100, 'z' * 100):
            self.add(content=content)
        with patch.object(daily, 'token_count', side_effect=len), patch.object(daily, 'LIMIT', 5400):
            self.run_day(5)
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 0, 1),
                                         ('2026_W41', 2, 2, 0, 1),
                                         ('2026_W41', 2, 3, 1, 1)])
        self.assertEqual(self.rows('SELECT part_id,revision,position,queue_id FROM revision_sources ORDER BY part_id'),
                         [(1, 1, 0, 1), (2, 1, 0, 2), (3, 1, 0, 3)])

    def test_closed_part_rejects_storage_revision_and_preserves_provenance(self):
        from datetime import date
        from parts import PartStore, PlannedRevision, render
        self.closed_part_from_runtime()
        before = {table: self.rows('SELECT * FROM ' + table)
                  for table in ('parts', 'part_revisions', 'revision_sources', 'source_archive')}
        files = {p: p.read_bytes() for p in self.output.rglob('*.txt')}
        source = daily.queue_fiche(1, dict(schema_version=1, topic=2, date='2026-10-05', content='x' * 100), date(2026, 10, 5))
        text = render([source], '2026_W41', 2, 1, 2, 5000)
        plan = PlannedRevision('2026_W41', 2, 1, 2, False, (source,), text, daily.token_count(text), 5000)
        db = daily.database(self.db)
        try:
            store = PartStore(db)
            snapshot = {('2026_W41', 2): store.state('2026_W41', 2)}
            with self.assertRaisesRegex(ValueError, 'Gesloten part'), db:
                db.execute('BEGIN IMMEDIATE')
                store.register([plan], [self.output / 'forbidden.txt'], {}, snapshot, [])
        finally:
            db.close()
        for table, rows in before.items():
            self.assertEqual(self.rows('SELECT * FROM ' + table), rows)
        for path, data in files.items():
            self.assertEqual(path.read_bytes(), data)

    def test_closed_part_rejects_direct_sql_revision(self):
        self.closed_part_from_runtime()
        before = self.rows('SELECT * FROM part_revisions')
        with sqlite3.connect(self.db) as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'Closed part'):
                db.execute("INSERT INTO part_revisions SELECT part_id,2,path || '.forbidden',sha256,tokens,tokenizer,reserved_tokens FROM part_revisions WHERE part_id=1 AND revision=1")
        self.assertEqual(self.rows('SELECT * FROM part_revisions'), before)
        self.assertEqual(self.active()[0], ('2026_W41', 2, 1, 0, 1))

    def test_multi_overflow_registers_first_revision_of_new_closed_parts(self):
        self.closed_part_from_runtime()
        self.assertEqual(self.rows('SELECT part_id,revision FROM part_revisions ORDER BY part_id'),
                         [(1, 1), (2, 1), (3, 1)])
        self.assertEqual(self.rows('PRAGMA user_version'), [(1,)])

    def test_python39_syntax(self):
        for path in Path('.').glob('*.py'):
            ast.parse(path.read_text(), feature_version=(3, 9))


class MigrationTests(PartFixture):
    # Build the EXACT pre-PR schema independently, not using the new initializer.
    LEGACY = '''
    CREATE TABLE ingress_queue(id INTEGER PRIMARY KEY AUTOINCREMENT,received_at TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending');
    CREATE TABLE days(day TEXT PRIMARY KEY,week TEXT NOT NULL,status TEXT NOT NULL,commit_sha TEXT,manifest_sha256 TEXT,error TEXT);
    CREATE TABLE attempts(id INTEGER PRIMARY KEY,day TEXT NOT NULL,status TEXT NOT NULL,error TEXT,recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE threads(path TEXT PRIMARY KEY,day TEXT NOT NULL REFERENCES days(day),topic INTEGER NOT NULL,part INTEGER NOT NULL,sha256 TEXT NOT NULL,tokens INTEGER NOT NULL,tokenizer TEXT NOT NULL,reserved_tokens INTEGER NOT NULL);
    CREATE TABLE sources(day TEXT NOT NULL REFERENCES days(day),source_path TEXT NOT NULL,sha256 TEXT NOT NULL,thread_path TEXT NOT NULL REFERENCES threads(path),position INTEGER NOT NULL,PRIMARY KEY(day,source_path));
    '''

    def test_realistic_legacy_migration_and_idempotence(self):
        self.db.unlink()
        legacyfile = self.base / '2026-10-05_0001.txt'
        legacyfile.write_bytes(b'legacy bytes')
        with sqlite3.connect(self.db) as db:
            db.executescript(self.LEGACY)
            db.execute("INSERT INTO days VALUES ('2026-10-05','2026_W41','success','commit','manifest',NULL)")
            db.execute("INSERT INTO attempts(day,status) VALUES ('2026-10-05','success')")
            db.execute("INSERT INTO threads VALUES (?,'2026-10-05',2,1,'hash',7,'cl100k_base',5000)", (str(legacyfile),))
            db.execute("INSERT INTO sources VALUES ('2026-10-05','queue:1','hash',?,0)", (str(legacyfile),))
            db.execute("INSERT INTO ingress_queue(received_at,payload,status) VALUES ('now','{}','processed')")
        identity = self.add()
        tables = ('days', 'attempts', 'threads', 'sources')
        before = {t: self.rows('SELECT * FROM ' + t) for t in tables}
        processed = self.rows('SELECT * FROM ingress_queue WHERE id=1')
        statements = []
        original = sqlite3.connect
        def traced(*args, **kwargs):
            db = original(*args, **kwargs)
            db.set_trace_callback(statements.append)
            return db
        with patch('sqlite3.connect', side_effect=traced):
            self.run_day()
            for _ in range(2):
                db = daily.database(self.db)
                db.close()
        for t in tables:
            self.assertEqual(self.rows('SELECT * FROM ' + t), before[t])
        self.assertEqual(self.rows('SELECT * FROM ingress_queue WHERE id=1'), processed)
        self.assertEqual(self.rows('SELECT status FROM ingress_queue WHERE id=?', (identity,)), [('processed',)])
        self.assertEqual(legacyfile.read_bytes(), b'legacy bytes')
        self.assertEqual(self.active(), [('2026_W41', 2, 1, 1, 1)])
        self.assertEqual(self.rows('PRAGMA user_version'), [(1,)])
        self.assertFalse(any(s.lstrip().upper().startswith(('DELETE', 'VACUUM')) for s in statements))

    def test_fresh_database_and_version(self):
        self.db.unlink()
        db = daily.database(self.db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (1,))
        self.assertIn(('parts',), db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        db.close()

    def test_unknown_newer_version_refused(self):
        with sqlite3.connect(self.db) as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaisesRegex(ValueError, 'schema'):
            daily.database(self.db)
