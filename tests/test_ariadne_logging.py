from contextlib import redirect_stderr, redirect_stdout
from datetime import date
import io
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ariadne


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'logs' / 'ariadne.log'
        root = logging.getLogger()
        self.old_handlers, self.old_level = root.handlers[:], root.level
        root.handlers = []
        self.addCleanup(self.restore_logging)

    def restore_logging(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        root.handlers = self.old_handlers
        root.setLevel(self.old_level)

    def run_main(self):
        with patch.object(ariadne, 'LOG_PATH', self.path, create=True), patch(
                'sys.argv', ['ariadne.py', '--repo', self.tmp.name,
                             '--date', '2026-09-30']):
            ariadne.main()

    def test_default_path_and_module_logging(self):
        self.assertEqual(ariadne.LOG_PATH,
                         Path('/home/weekendkrant/logs/ariadne.log'))
        with patch.object(ariadne, 'LOG_PATH', self.path):
            ariadne.configure_logging()
        module = logging.getLogger('future_ariadne_module')
        module.info('Normale informatie met accenten: vóór')
        module.debug('Diagnostiek')
        module.warning('Herstelbare afwijking')
        module.error('Echte fout')
        module.critical('Kritieke fout')
        content = self.path.read_text(encoding='utf-8')
        self.assertIn('INFO future_ariadne_module Normale informatie met accenten: vóór', content)
        self.assertNotIn('Diagnostiek', content)
        for level in ('WARNING', 'ERROR', 'CRITICAL'):
            self.assertIn(level + ' future_ariadne_module', content)
        self.assertFalse(module.handlers)

    def test_debug_is_available_when_explicitly_configured(self):
        module = logging.getLogger('future_ariadne_debug_module')
        ariadne.configure_logging(self.path)
        module.debug('Verborgen bij INFO')
        self.assertNotIn('Verborgen bij INFO', self.path.read_text())
        ariadne.configure_logging(self.path, level=logging.DEBUG)
        module.debug('Diagnostiek bij DEBUG')
        content = self.path.read_text()
        self.assertIn('DEBUG future_ariadne_debug_module Diagnostiek bij DEBUG', content)
        self.assertNotIn('Verborgen bij INFO', content)

    def test_rotation_bounds_archives_and_reconfiguration_does_not_duplicate(self):
        ariadne.configure_logging(self.path)
        first = logging.getLogger().handlers[0]
        ariadne.configure_logging(self.path)
        handlers = logging.getLogger().handlers
        self.assertEqual(len(handlers), 1)
        self.assertIsNone(first.stream)
        handler = handlers[0]
        self.assertIsInstance(handler, RotatingFileHandler)
        self.assertEqual(handler.maxBytes, 1024 * 1024)
        self.assertEqual(handler.backupCount, 4)
        handler.maxBytes = 180  # Force real rollover without writing megabytes.
        for number in range(20):
            logging.getLogger('rotation').info('Record %s %s', number, 'x' * 60)
        self.assertEqual({path.name for path in self.path.parent.iterdir()},
                         {'ariadne.log', 'ariadne.log.1', 'ariadne.log.2',
                          'ariadne.log.3', 'ariadne.log.4'})
        self.assertIn('Record 19', self.path.read_text())

    def test_entrypoint_preserves_json_stdout_and_logs_lifecycle_only_to_file(self):
        result = {'week': '2026_W40', 'branch': 'ingress/2026_W40',
                  'ingress_path': 'ingress/2026_W40', 'base_commit': 'abc123'}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(ariadne, 'prepare_week', return_value=result) as prepare, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.run_main()
        prepare.assert_called_once_with(Path(self.tmp.name), date(2026, 9, 30))
        content = self.path.read_text()
        self.assertIn('INFO ariadne Weekvoorbereiding gestart', content)
        self.assertIn('INFO ariadne Weekvoorbereiding voltooid', content)
        for value in result.values():
            self.assertIn(value, content)
        self.assertEqual(stdout.getvalue(), json.dumps(result, indent=2, sort_keys=True) + '\n')
        self.assertEqual(stderr.getvalue(), '')

    def test_entrypoint_logs_expected_and_unexpected_exceptions_with_traceback(self):
        # Ook onverwachte runtimefouten worden aan de unattended grens afgehandeld.
        for error in (ValueError('Ongeldig auditrecord'), OSError('Schijffout'),
                      RuntimeError('Onverwachte fout')):
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(error=error), patch.object(
                    ariadne, 'prepare_week', side_effect=error), \
                    redirect_stdout(stdout), redirect_stderr(stderr), \
                    self.assertRaises(SystemExit) as stopped:
                self.run_main()
            self.assertEqual(stopped.exception.code, 1)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), '')
            content = self.path.read_text()
            self.assertIn('ERROR ariadne Weekvoorbereiding mislukt', content)
            self.assertIn(self.tmp.name, content)
            self.assertIn('2026-09-30', content)
            self.assertIn('Traceback (most recent call last)', content)
            self.assertIn(str(error), content)
        self.assertNotIn('Weekvoorbereiding voltooid', content)

    def test_logging_setup_failure_stops_before_preparation_and_logs_to_stderr(self):
        self.path.parent.write_text('Geen map')
        stderr = io.StringIO()
        with patch.object(ariadne, 'prepare_week', return_value={}) as prepare, \
                redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
            self.run_main()
        self.assertEqual(stopped.exception.code, 1)
        prepare.assert_not_called()
        self.assertIn('ERROR ariadne Logging initialiseren mislukt', stderr.getvalue())
        self.assertIn(str(self.path), stderr.getvalue())
        self.assertIn('Traceback (most recent call last)', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
