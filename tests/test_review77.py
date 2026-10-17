"""Upgrade and calendar regressions for frozen worker inputs."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

import database
import daily
from job_control import JobControl
from leonardo import canonical, supports_capability
from test_leonardo import LeonardoFixture


class ReviewTests(LeonardoFixture):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def proposals(self):
        return [dict(question='Independent reproduction?', rationale='Confirmation missing',
                     scope='Primary reports only', refs=['queue:1'])]

    def test_old_source_uses_frozen_brussels_job_date_and_current_week(self):
        # The source is old; preparation is just after midnight in Brussels.
        self.now = datetime(2026, 10, 17, 22, 30, tzinfo=timezone.utc)
        self.enqueue()
        leo = self.start()
        self.finish(leo, kuifje_missions=self.proposals())
        k = self.start('research')
        self.assertEqual(k['input']['date'], '2026-10-18')
        self.assertIn('input.date', k['role_contract'])
        authority = {key:k[key] for key in ('job_id', 'attempt_id', 'token')}
        fiche = dict(schema_version=1, date=k['input']['date'], topic=2,
                     content='Primary preprint https://example.org/report, published 2026-04-30')
        with patch('ingress_queue.datetime') as clock:
            clock.now.return_value = self.now
            with self.assertRaises(ValueError):
                self.queue.add(dict(fiche, date='2026-04-30'), mission_id=k['input']['missions'][0]['mission_id'], fiche_id='source', claim=authority)
            queue_id = self.queue.add(fiche, mission_id=k['input']['missions'][0]['mission_id'], fiche_id='source', claim=authority)
        daily.run_daily(self.root, self.db, self.output, self.now, self.lock)
        week, = self.conn.execute('''SELECT p.week FROM revision_sources r JOIN parts p ON p.id=r.part_id
                                    WHERE r.queue_id=?''', (queue_id,)).fetchone()
        self.assertEqual(week, '2026_W42')
        self.assertEqual(json.loads(self.conn.execute('SELECT payload FROM ingress_queue WHERE id=?', (queue_id,)).fetchone()[0])['date'], '2026-10-18')
        # Neither a later day, recovery nor a deployment file change may redate the job.
        self.now += timedelta(days=2)
        control = JobControl(self.conn, lambda:self.now)
        control.validate(authority)
        control.execute('reconcile', dict(operation_id='recover:date', job_id=k['job_id'], attempt_id=k['attempt_id'], decision='retry', evidence_ref='operator:stopped'))
        with patch('role_contracts.load_contract', side_effect=AssertionError('frozen')):
            retry = self.start('research:retry')
            self.finish(leo, operation='replay:date', kuifje_missions=self.proposals())
        self.assertEqual(retry['input'], k['input'])

    def test_base_main_unversioned_schema1_survives_schema14_upgrade(self):
        # Reproduce the base-main serializer: schema 1, exact unversioned output bytes.
        # Its other snapshot fields are unchanged; only the schema discriminator differs.
        output = (Path(__file__).parent/'fixtures'/'leonardo-schema1-unversioned-output.md').read_text()
        self.assertFalse(output.startswith('leonardo-output-v'))
        def base_snapshot(value):
            if isinstance(value, dict) and 'parts' in value and 'output_contract' in value:
                value = dict(value, schema_version=1, output_contract=output)
            return canonical(value)
        # Use a separate real schema-13 fixture, before freezing the base-main job.
        with patch.object(database, 'SCHEMA_VERSION', 13):
            fixture = LeonardoFixture()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            with patch('leonardo.canonical', side_effect=base_snapshot):
                job = fixture.enqueue()
        before = fixture.conn.execute('SELECT * FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone()
        database.migrate(fixture.conn)
        self.assertEqual(fixture.conn.execute('SELECT * FROM leonardo_assignments WHERE job_id=?', (job,)).fetchone(), before)
        with patch('role_contracts.load_contract', side_effect=AssertionError('frozen')):
            leo = fixture.start()
        self.assertEqual(leo['input']['schema_version'], 1)
        self.assertEqual(leo['output_contract'], output)
        state = fixture.state()
        state['claims'][0]['support'] = ['queue:1']
        fixture.finish(leo, state, kuifje_missions=self.proposals())
        self.assertEqual(fixture.store.latest('dossier:reproduction')['claims'][0]['support'], ['queue:1'])
        self.assertEqual(fixture.conn.execute('SELECT count(*) FROM kuifje_missions').fetchone()[0], 1)
        data = leo['input']
        for capability in ('fine_provenance', 'missions'):
            self.assertTrue(supports_capability(data, capability))
            self.assertFalse(supports_capability(dict(data, output_contract='# Unknown unversioned contract'), capability))
        self.assertEqual(fixture.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
