import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('evidence_recording', Path(__file__).parents[1] / 'cooperation_evidence_recording.py')
recording = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recording)
EvidenceRecorder = recording.EvidenceRecorder


def raw_line(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


def physics(manifest, sequence=0, declared='same-declared-hash'):
    return {'topic': 'physics', 'received_monotonic': sequence / 50, 'received_wall_time': 1000 + sequence / 50,
            'source_stamp': sequence / 50, 'sequence': sequence,
            'payload': {'sequence': sequence, 'stamp': sequence / 50, 'car_hold': True,
                        'source': {'scene_sha256': 'scene-identity', 'manifest_sha256': declared,
                                   'episode_id': 'episode-a', 'manifest': manifest}}}


class StreamProxy:
    encoding = 'utf-8'

    def __init__(self, stream):
        self.stream = stream
        self.writes = self.flushes = 0
        self.fail_write_at = self.fail_flush_at = None
        self.fail_close = False
        self.partial_return = False

    @property
    def closed(self):
        return self.stream.closed

    def tell(self):
        return self.stream.tell()

    def write(self, text):
        self.writes += 1
        if self.writes == self.fail_write_at:
            self.stream.write(text[:len(text) // 2])
            self.stream.flush()
            raise OSError('injected mid-write failure')
        if self.partial_return:
            self.stream.write(text[:len(text) // 2])
            return len(text) // 2
        return self.stream.write(text)

    def flush(self):
        self.flushes += 1
        if self.flushes == self.fail_flush_at:
            raise OSError('injected flush failure')
        self.stream.flush()

    def close(self):
        if self.fail_close:
            raise OSError('injected close failure')
        self.stream.close()


class EvidenceRecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'evidence.jsonl'

    def stream(self):
        stream = os.fdopen(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8')
        self.addCleanup(lambda: stream.close() if not stream.closed else None)
        return stream

    def test_1000_records_keep_all_dynamic_fields_and_reduce_bytes_over_70_percent(self):
        manifest = {'static_model_description': 'x' * 8192, 'configuration': {'version': 3, 'axes': ['x', 'y', 'z']}}
        recorder = EvidenceRecorder(self.stream())
        originals = [physics(manifest, index) for index in range(1000)]
        preserved = copy.deepcopy(originals)
        full_size = sum(len(raw_line(value)) for value in originals)
        for value in originals:
            self.assertTrue(recorder.record(value))
        self.assertFalse(recorder.snapshot()['capture_complete'])
        recorder.close()
        data = self.path.read_bytes()
        rows = [json.loads(line) for line in data.splitlines()]
        self.assertEqual(len(rows), 1000)
        self.assertEqual(originals, preserved)
        self.assertLess(len(data), full_size * .3)
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                                           separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        for index, row in enumerate(rows):
            expected = copy.deepcopy(originals[index])
            expected['manifest_ref_sha256'] = digest
            if index:
                del expected['payload']['source']['manifest']
            self.assertEqual(row, expected)
        self.assertEqual(recorder.snapshot()['written'], 1000)
        self.assertEqual(recorder.snapshot()['offered'], 1000)
        self.assertEqual(recorder.snapshot()['deduplicated'], 999)
        self.assertEqual(recorder.snapshot()['incomplete'], 0)
        self.assertEqual(recorder.snapshot()['bytes'], len(data))
        self.assertTrue(recorder.snapshot()['capture_complete'])

    def test_first_actual_manifest_of_each_content_is_kept_despite_identical_declared_hash(self):
        recorder = EvidenceRecorder(self.stream())
        for manifest in ({'v': 1}, {'v': 2}, {'v': 1}, {'v': 2}):
            self.assertTrue(recorder.record(physics(manifest)))
        recorder.close()
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertIn('manifest', rows[0]['payload']['source'])
        self.assertIn('manifest', rows[1]['payload']['source'])
        self.assertNotEqual(rows[0]['manifest_ref_sha256'], rows[1]['manifest_ref_sha256'])
        self.assertNotIn('manifest', rows[2]['payload']['source'])
        self.assertNotIn('manifest', rows[3]['payload']['source'])
        self.assertEqual(rows[0]['payload']['source']['manifest_sha256'], rows[1]['payload']['source']['manifest_sha256'])
        self.assertEqual(recorder.snapshot()['manifest_sources'], 2)

    def test_canonical_key_order_deduplicates_but_never_mutates_or_retains_input_containers(self):
        recorder = EvidenceRecorder(self.stream())
        value = physics({'a': 1, 'b': {'name': '标定'}})
        first = copy.deepcopy(value)
        self.assertTrue(recorder.record(value))
        value['payload']['source']['manifest']['b']['name'] = 'new'
        self.assertTrue(recorder.record(physics({'b': {'name': '标定'}, 'a': 1})))
        recorder.close()
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual(rows[0]['payload']['source']['manifest'], first['payload']['source']['manifest'])
        self.assertNotIn('manifest', rows[1]['payload']['source'])
        self.assertIn('manifest', value['payload']['source'])
        self.assertEqual(value['payload']['source']['manifest']['b']['name'], 'new')

    def test_utf8_exact_budget_counts_actual_encoded_bytes_including_newline(self):
        value = {'topic': 'status', 'sequence': 7, 'payload': {'text': '鱼' * 100, 'padding': ''}}
        value['payload']['padding'] = 'p' * (1024 - len(raw_line(value)))
        self.assertEqual(len(raw_line(value)), 1024)
        recorder = EvidenceRecorder(self.stream(), max_bytes=1024)
        self.assertTrue(recorder.record(value))
        recorder.close()
        self.assertEqual(self.path.stat().st_size, 1024)
        self.assertEqual(recorder.snapshot()['bytes'], 1024)
        self.assertTrue(recorder.snapshot()['capture_complete'])

    def test_one_byte_over_budget_writes_no_partial_line_and_latches_failure(self):
        value = {'topic': 'status', 'sequence': 0, 'payload': {'padding': ''}}
        value['payload']['padding'] = 'p' * (1025 - len(raw_line(value)))
        recorder = EvidenceRecorder(self.stream(), max_bytes=1024)
        self.assertFalse(recorder.record(value))
        self.assertFalse(recorder.record({'topic': 'status'}))
        recorder.close()
        self.assertEqual(self.path.read_bytes(), b'')
        self.assertEqual(recorder.snapshot()['error_code'], 'byte_budget')
        self.assertEqual(recorder.snapshot()['offered'], 2)
        self.assertEqual(recorder.snapshot()['incomplete'], 2)
        self.assertTrue(recorder.snapshot()['truncated'])
        self.assertFalse(recorder.snapshot()['capture_complete'])

    def test_budget_rejection_keeps_earlier_complete_lines_unchanged(self):
        recorder = EvidenceRecorder(self.stream(), max_bytes=1024)
        first = {'topic': 'status', 'sequence': 1}
        self.assertTrue(recorder.record(first))
        self.assertFalse(recorder.record({'topic': 'status', 'payload': 'x' * 1024}))
        recorder.close()
        self.assertEqual(self.path.read_bytes(), raw_line(first))
        self.assertEqual(recorder.snapshot()['written'], 1)
        self.assertEqual(recorder.snapshot()['incomplete'], 1)

    def test_mid_write_io_failure_preserves_prior_line_and_reports_uncertain_tail_as_incomplete(self):
        proxy = StreamProxy(self.stream())
        proxy.fail_write_at = 2
        recorder = EvidenceRecorder(proxy)
        first = {'topic': 'status', 'sequence': 1, 'text': '初始'}
        self.assertTrue(recorder.record(first))
        self.assertFalse(recorder.record({'topic': 'status', 'sequence': 2, 'text': '失败'}))
        self.assertFalse(recorder.record({'topic': 'status', 'sequence': 3}))
        recorder.close()
        raw = self.path.read_bytes()
        self.assertTrue(raw.startswith(raw_line(first)))
        self.assertEqual(json.loads(raw.splitlines()[0]), first)
        self.assertEqual(proxy.writes, 2)
        self.assertEqual(recorder.snapshot()['bytes'], len(raw))
        self.assertEqual(recorder.snapshot()['written'], 1)
        self.assertEqual(recorder.snapshot()['incomplete'], 2)
        self.assertEqual(recorder.snapshot()['error_code'], 'write_failed')
        self.assertFalse(recorder.snapshot()['capture_complete'])

    def test_short_write_return_is_not_accepted_as_a_complete_record(self):
        proxy = StreamProxy(self.stream())
        proxy.partial_return = True
        recorder = EvidenceRecorder(proxy)
        self.assertFalse(recorder.record({'topic': 'status', 'text': '中文'}))
        recorder.close()
        self.assertEqual(recorder.snapshot()['written'], 0)
        self.assertEqual(recorder.snapshot()['error_code'], 'partial_write')
        self.assertEqual(recorder.snapshot()['bytes'], self.path.stat().st_size)
        self.assertFalse(recorder.snapshot()['capture_complete'])

    def test_failed_flush_and_failed_close_are_visible_and_do_not_restore_completeness(self):
        proxy = StreamProxy(self.stream())
        proxy.fail_flush_at = 1
        proxy.fail_close = True
        recorder = EvidenceRecorder(proxy)
        self.assertFalse(recorder.record({'topic': 'status', 'sequence': 1}))
        recorder.close()
        state = recorder.snapshot()
        self.assertEqual(state['written'], 0)
        self.assertEqual(state['error_code'], 'flush_failed')
        self.assertEqual([entry['code'] for entry in state['errors']], ['flush_failed', 'close_failed'])
        self.assertTrue(state['failed'])
        self.assertTrue(state['truncated'])
        self.assertFalse(state['capture_complete'])
        # The caller can release its stream after a reported close error.
        proxy.stream.close()

    def test_close_flush_failure_after_valid_records_is_still_an_incomplete_capture(self):
        proxy = StreamProxy(self.stream())
        proxy.fail_flush_at = 2
        recorder = EvidenceRecorder(proxy)
        self.assertTrue(recorder.record({'topic': 'status'}))
        recorder.close(); recorder.close()
        self.assertEqual(recorder.snapshot()['error_code'], 'close_flush_failed')
        self.assertEqual(recorder.snapshot()['incomplete'], 0)
        self.assertFalse(recorder.snapshot()['capture_complete'])

    def test_invalid_json_latches_without_throwing_and_does_not_corrupt_valid_lines(self):
        recorder = EvidenceRecorder(self.stream())
        first = {'topic': 'status', 'sequence': 1}
        self.assertTrue(recorder.record(first))
        self.assertFalse(recorder.record({'topic': 'status', 'payload': float('nan')}))
        self.assertFalse(recorder.record({'topic': 'status', 'sequence': 2}))
        recorder.close()
        self.assertEqual(self.path.read_bytes(), raw_line(first))
        self.assertEqual(recorder.snapshot()['error_code'], 'invalid_json')
        self.assertEqual(recorder.snapshot()['incomplete'], 2)

    def test_manifest_source_limit_is_finite_and_an_existing_source_does_not_consume_an_extra_slot(self):
        recorder = EvidenceRecorder(self.stream(), max_bytes=65536)
        for index in range(16):
            self.assertTrue(recorder.record(physics({'index': index}, index)))
        self.assertTrue(recorder.record(physics({'index': 3}, 16)))
        self.assertFalse(recorder.record(physics({'index': 17}, 17)))
        recorder.close()
        self.assertEqual(recorder.snapshot()['manifest_sources'], 16)
        self.assertEqual(recorder.snapshot()['written'], 17)
        self.assertEqual(recorder.snapshot()['error_code'], 'manifest_limit')
        self.assertFalse(recorder.snapshot()['capture_complete'])

    def test_malformed_physics_and_conflicting_manifest_refs_fail_without_throwing(self):
        for value in [None, {'topic': 'physics'}, {'topic': 'physics', 'payload': {'source': {}}},
                      {**physics({'v': 1}), 'manifest_ref_sha256': 'wrong'}]:
            with self.subTest(value_type=type(value).__name__):
                # Each recorder gets a separate exclusive file.
                path = Path(self.directory.name) / ('case-' + str(len(list(Path(self.directory.name).iterdir()))))
                with path.open('x', encoding='utf-8') as stream:
                    recorder = EvidenceRecorder(stream)
                    self.assertFalse(recorder.record(value))
                    recorder.close()
                    self.assertTrue(recorder.snapshot()['failed'])
                    self.assertEqual(path.stat().st_size, 0)

    def test_budget_inputs_reject_boolean_nonintegers_and_out_of_range(self):
        stream = self.stream()
        for budget in [True, False, 1.0, '1024', 0, -1, 1023, 4 * 1024 ** 3 + 1]:
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                EvidenceRecorder(stream, budget)
        self.assertEqual(EvidenceRecorder(stream, 4 * 1024 ** 3).snapshot()['max_bytes'], 4 * 1024 ** 3)

    def test_recording_after_close_is_not_silently_accepted_and_snapshot_isolated(self):
        recorder = EvidenceRecorder(self.stream())
        recorder.close()
        self.assertTrue(recorder.snapshot()['capture_complete'])
        self.assertFalse(recorder.record({'topic': 'status'}))
        snapshot = recorder.snapshot()
        snapshot['errors'][0]['code'] = 'changed'
        self.assertEqual(recorder.snapshot()['error_code'], 'closed')
        self.assertEqual(recorder.snapshot()['errors'][0]['code'], 'closed')
        self.assertFalse(recorder.snapshot()['capture_complete'])


if __name__ == '__main__':
    unittest.main()
