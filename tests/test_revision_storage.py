"""Storage retention keeps all logical history and only required physical input."""
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch

import daily
from parts import PartStore
from revision_storage import cleanup, reconstruct, retire
from test_parts import PartFixture


class RevisionStorageTests(PartFixture):
    def grow(self, count=4):
        for n in range(count):
            self.add(content='source %s é\r\n漢字 ' % n + 'x' * 1000)
            self.run_day()

    def test_multiple_revisions_keep_only_active_file_and_exact_history(self):
        expected = {}
        for n in range(6):
            self.add(content='source %s é\r\n漢字 ' % n + 'x' * 1000)
            self.run_day()
            path, digest, tokens = self.rows('SELECT path,sha256,tokens FROM part_revisions WHERE revision=?', (n + 1,))[0]
            expected[n + 1] = Path(path).read_bytes()
            self.assertEqual(hashlib.sha256(expected[n + 1]).hexdigest(), digest)
            self.assertEqual(daily.token_count(expected[n + 1].decode()), tokens)
            self.assertEqual(len(list(self.output.rglob('rev_*.txt'))), 1)
        with sqlite3.connect(self.db) as db:
            for revision, data in expected.items():
                self.assertEqual(reconstruct(db, 1, revision), data)
        self.assertEqual(len(self.rows('SELECT * FROM part_revisions')), 6)
        self.assertEqual(len(self.rows('SELECT * FROM source_archive')), 6)
        self.assertEqual(len(self.rows('SELECT * FROM revision_sources')), 21)

    def test_active_closed_and_offered_files_are_always_protected(self):
        self.grow(2)
        with daily.database(self.db) as db:
            active = Path(db.execute('SELECT path FROM part_revisions WHERE revision=2').fetchone()[0])
            self.assertEqual(retire(db, 1, 2, self.output, True)['status'], 'protected')
            db.execute('UPDATE parts SET is_open=0')
            db.commit()
            self.assertEqual(retire(db, 1, 2, self.output, True)['status'], 'protected')
            PartStore(db).offer(1, 2)
            self.assertEqual(cleanup(db, self.output, True)['bytes'], 0)
        self.assertTrue(active.is_file())

    def test_explicit_legacy_cleanup_dry_run_apply_and_repeat_preserve_database(self):
        # Suppress new retirement to emulate an existing schema-9 installation.
        with patch('revision_storage.retire', return_value={'status': 'protected', 'bytes': 0}):
            self.grow()
        paths = self.rows('SELECT path FROM part_revisions ORDER BY revision')
        before = {p: Path(p).read_bytes() for p, in paths}
        with daily.database(self.db) as db:
            dump = list(db.iterdump())
            version = db.execute('PRAGMA user_version').fetchone()
            report = cleanup(db, self.output)
            self.assertEqual(report['bytes'], sum(len(before[p]) for p, in paths[:-1]))
            self.assertEqual({p: Path(p).read_bytes() for p, in paths}, before)
            self.assertEqual(cleanup(db, self.output, True)['bytes'], report['bytes'])
            self.assertEqual(cleanup(db, self.output, True)['bytes'], 0)
            self.assertEqual(list(db.iterdump()), dump)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), version)
            for rev, (path,) in enumerate(paths, 1):
                self.assertEqual(reconstruct(db, 1, rev), before[path])
        self.assertEqual(len(list(self.output.rglob('*.txt'))), 1)

    def test_failed_registration_does_not_retire_previous_active_file(self):
        self.grow(1)
        path = Path(self.rows('SELECT path FROM part_revisions')[0][0])
        before = path.read_bytes()
        self.add(content='next')
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER fail_revision BEFORE INSERT ON part_revisions BEGIN SELECT RAISE(ABORT,'no revision'); END")
        with self.assertLogs('daily', level='ERROR'), self.assertRaises(sqlite3.IntegrityError):
            self.run_day()
        self.assertEqual(path.read_bytes(), before)
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER fail_revision')
        self.run_day()
        self.assertFalse(path.exists())
        self.assertEqual(len(list(self.output.rglob('*.txt'))), 1)

    def test_crash_before_unlink_leaves_recoverable_copy_after_committed_growth(self):
        self.grow(1)
        path = Path(self.rows('SELECT path FROM part_revisions')[0][0])
        self.add(content='next')
        with patch.object(Path, 'unlink', side_effect=OSError('unlink failure')), \
                self.assertLogs('daily', level='ERROR'), self.assertRaises(OSError):
            self.run_day()
        self.assertTrue(path.exists())
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('processed',), ('processed',)])
        with sqlite3.connect(self.db) as db:
            self.assertGreater(cleanup(db, self.output, True)['bytes'], 0)
            self.assertEqual(cleanup(db, self.output, True)['bytes'], 0)
        self.assertEqual(len(list(self.output.rglob('*.txt'))), 1)

    def test_crash_after_unlink_remains_reconstructible_and_retry_safe(self):
        self.grow(1)
        original = Path(self.rows('SELECT path FROM part_revisions')[0][0]).read_bytes()
        self.add(content='next')
        with patch('revision_storage.sync_directory', side_effect=OSError('directory fsync')), \
                self.assertLogs('daily', level='ERROR'), self.assertRaises(OSError):
            self.run_day()
        self.assertEqual(self.rows('SELECT status FROM ingress_queue'), [('processed',), ('processed',)])
        self.assertFalse(Path(self.rows('SELECT path FROM part_revisions WHERE revision=1')[0][0]).exists())
        with sqlite3.connect(self.db) as db:
            self.assertEqual(reconstruct(db, 1, 1), original)
            self.assertEqual(cleanup(db, self.output, True)['bytes'], 0)

    def test_corrupt_copy_or_audit_mismatch_is_never_deleted(self):
        with patch('revision_storage.retire', return_value={}):
            self.grow(2)
        path = Path(self.rows('SELECT path FROM part_revisions WHERE revision=1')[0][0])
        before = path.read_bytes()
        path.write_bytes(b'corrupt')
        with sqlite3.connect(self.db) as db:
            with self.assertRaisesRegex(ValueError, 'wijkt af'):
                cleanup(db, self.output, True)
            self.assertEqual(path.read_bytes(), b'corrupt')
            path.write_bytes(before)
            with patch('daily.token_count', return_value=-1), self.assertRaisesRegex(ValueError, 'hash/tokenaudit'):
                cleanup(db, self.output, True)
        self.assertTrue(path.exists())

    def test_cli_dry_run_is_default_and_missing_database_is_not_created(self):
        self.grow(2)
        script = Path(daily.__file__).with_name('revision_storage.py')
        args = [sys.executable, str(script), '--db', str(self.db), '--output', str(self.output), '--lock', str(self.lock)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"apply": false', result.stdout)
        missing = self.base / 'missing.sqlite3'
        args[3] = str(missing)
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())

    def test_cleanup_never_follows_symlink_or_deletes_unregistered_orphan(self):
        with patch('revision_storage.retire', return_value={}):
            self.grow(2)
        path = Path(self.rows('SELECT path FROM part_revisions WHERE revision=1')[0][0])
        target = self.base / 'outside.txt'
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        with sqlite3.connect(self.db) as db, self.assertRaises(ValueError):
            cleanup(db, self.output, True)
        self.assertTrue(target.is_file())
        path.unlink()
        path.write_bytes(target.read_bytes())
        orphan = path.with_name('rev_9999.txt')
        orphan.write_bytes(b'orphan')
        with sqlite3.connect(self.db) as db:
            cleanup(db, self.output, True)
        self.assertEqual(orphan.read_bytes(), b'orphan')

    def test_dry_run_before_apply_failure_and_retry_preserves_remaining_history(self):
        with patch('revision_storage.retire', return_value={}):
            self.grow(3)
        paths = [Path(p) for p, in self.rows('SELECT path FROM part_revisions ORDER BY revision')]
        original_unlink = Path.unlink
        def fail_second(path, **kwargs):
            if path == paths[1]:
                raise OSError('second copy unavailable')
            return original_unlink(path, **kwargs)
        with sqlite3.connect(self.db) as db:
            self.assertEqual([r['status'] for r in cleanup(db, self.output)['revisions']],
                             ['eligible', 'eligible', 'protected'])
            with patch.object(Path, 'unlink', fail_second), self.assertRaises(OSError):
                cleanup(db, self.output, True)
            self.assertFalse(paths[0].exists())
            self.assertTrue(paths[1].exists())
            self.assertEqual([r['status'] for r in cleanup(db, self.output, True)['revisions']],
                             ['missing', 'removed', 'protected'])
            self.assertEqual(len([reconstruct(db, 1, r) for r in (1, 2, 3)]), 3)
