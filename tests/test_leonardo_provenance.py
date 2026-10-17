"""Fine provenance remains inside the immutable processed revision boundary."""
from pathlib import Path
from unittest.mock import patch

import role_contracts
from leonardo_operator import inspect_job
from test_leonardo import LeonardoFixture


class ProvenanceTests(LeonardoFixture):
    def queue_state(self):
        state = self.state()
        for field in ('hypotheses', 'uncertainties', 'open_questions'):
            state[field][0]['refs'].append('queue:1')
        state['claims'][0]['support'] = ['queue:1']
        state['claims'][0]['counterevidence'] = ['queue:1']
        return state

    def assert_refused(self, claim, state):
        with self.assertRaises(ValueError):
            self.finish(claim, state)
        self.assertIsNone(self.store.latest('dossier:reproduction'))
        self.assertEqual(self.conn.execute('SELECT status FROM jobs WHERE id=?',
                                         (claim['job_id'],)).fetchone(), ('running',))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM job_operations').fetchone(), (0,))

    def test_mixed_refs_all_item_fields_and_exact_retry(self):
        other = self.add(content='independent counterevidence')
        self.run_day()
        self.part = (self.part[0], 2)
        self.enqueue()
        claim = self.start()
        state = self.queue_state()
        state['claims'][0]['counterevidence'] = [f'queue:{other}']
        first = self.finish(claim, state)
        self.assertEqual(first, self.finish(claim, state))
        self.assertEqual(first, self.finish(claim, state, operation='finish:other'))
        self.assertEqual(self.store.latest('dossier:reproduction'), state)
        usage = inspect_job(self.conn, claim['job_id'], compact=True)['context_usage']
        self.assertEqual(usage['state_provenance'], dict(part_ref_count=1, queue_ref_count=2))

    def test_existing_unprocessed_and_other_part_queue_are_refused(self):
        pending = self.add(content='not processed')
        other = self.add(topic=3, content='other part')
        self.run_day()
        self.enqueue()
        claim = self.start()
        for identity in (pending, other, 999999):
            # pending became a newer revision of our part; neither it nor the
            # other topic/part belongs to the explicitly assigned old revision.
            for field, key in (('hypotheses', 'refs'), ('uncertainties', 'refs'),
                               ('open_questions', 'refs'), ('claims', 'support'),
                               ('claims', 'counterevidence')):
                state = self.state()
                state[field][0][key] = [f'queue:{identity}']
                self.assert_refused(claim, state)
        self.finish(claim)  # Existing ordinary partrefs still work.

    def test_pending_queue_existence_is_not_membership(self):
        identity = self.add(content='still pending')
        self.enqueue()
        claim = self.start()
        state = self.state()
        state['hypotheses'][0]['refs'] = [f'queue:{identity}']
        self.assert_refused(claim, state)

    def test_malformed_queue_refs_in_each_field_are_refused(self):
        self.enqueue()
        claim = self.start()
        for field, key in (('hypotheses', 'refs'), ('uncertainties', 'refs'),
                           ('open_questions', 'refs'), ('claims', 'support'),
                           ('claims', 'counterevidence')):
            for value in ('queue:', 'queue:0', 'queue:-1', 'queue:+1', 'queue:01',
                          'queue:1:2', 'queue:1\n', 'queue:１', 'queue:1.0',
                          'queue:9223372036854775808', None, 1):
                with self.subTest(field=field, key=key, value=value):
                    state = self.state()
                    state[field][0][key] = [value]
                    self.assert_refused(claim, state)

    def test_mutable_queue_and_active_revision_cannot_change_authority(self):
        self.enqueue()
        claim = self.start()
        later = self.add(content='only in newer revision')
        self.run_day()
        self.assertEqual(self.conn.execute('SELECT active_revision FROM parts').fetchone(), (2,))
        with self.conn:
            self.conn.execute('DELETE FROM ingress_queue')
        state = self.queue_state()
        state['claims'][0]['counterevidence'] = [f'queue:{later}']
        self.assert_refused(claim, state)
        self.finish(claim, self.queue_state())  # Original archived fiche survives.

    def test_previous_processed_revision_authorizes_queue_in_next_state(self):
        self.enqueue()
        self.finish(self.start(), self.queue_state())
        self.add(content='new input')
        self.run_day()
        self.store.enqueue('prepare:2', 'dossier:reproduction', 1, [[self.part[0], 2]])
        claim = self.start('slot:2')
        state = self.queue_state()
        state.update(version=2, previous_version=1)
        state['processed_refs'].append(f'part:{self.part[0]}:2')
        self.finish(claim, state, operation='finish:2')
        self.assertEqual(self.store.latest('dossier:reproduction'), state)

    def test_processed_refs_cannot_be_expanded_by_output(self):
        self.add(content='new revision')
        self.run_day()
        self.enqueue()
        claim = self.start()
        state = self.queue_state()
        state['processed_refs'].append(f'part:{self.part[0]}:2')
        self.assert_refused(claim, state)
        state = self.queue_state()
        state['processed_refs'].append('queue:1')
        self.assert_refused(claim, state)

    def test_frozen_old_contract_keeps_part_only_semantics(self):
        original = role_contracts.load_contract
        legacy = Path(__file__).parent / 'fixtures' / 'leonardo-output-v1.md'
        def load(path):
            return original(legacy if path.name == 'leonardo-output.md' else path)
        from test_phase12 import frozen_leonardo
        with patch('role_contracts.load_contract', side_effect=load), frozen_leonardo('leonardo-output-v1:'):
            self.enqueue()
        claim = self.start()
        self.assertTrue(claim['output_contract'].endswith(legacy.read_text()))
        self.assert_refused(claim, self.queue_state())
        self.finish(claim, self.state())
