"""Collector diagnostics preserve unknowns, timing evidence, and hard bounds."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fishbot_sampling_trace import SamplingTrace


EPOCH = 1_790_000_000_000_000_000


def observed(trace, kind, steady, stamp=None, *, accepted=False, info=None,
             duration=.001, epoch_shift_ns=0, end_epoch_shift_ns=0):
    begin = EPOCH+round(steady*1e9)+epoch_shift_ns
    if info is None:
        info = dict(source_timestamp=begin-20_000_000, received_timestamp=begin-10_000_000,
                    publication_sequence_number=27, reception_sequence_number=None)
    trace.callback(kind, info, steady if stamp is None else stamp, steady, begin,
                   steady+duration, begin+round(duration*1e9)+end_epoch_shift_ns,
                   truth_receipt_steady=steady if accepted else None)


class SamplingTraceEvidence(unittest.TestCase):
    def test_binding_scalars_and_separate_clocks_remain_measured(self):
        trace = SamplingTrace()
        info = dict(source_timestamp=EPOCH+980_000_000, received_timestamp=EPOCH+990_000_000,
                    publication_sequence_number=81, reception_sequence_number=None)
        observed(trace, 'truth', 1., stamp=17.5, accepted=True, info=info, duration=.004)
        result = trace.finalize(2.)
        event = result['rolling_events'][0]
        self.assertEqual(event['message_info_raw'], info)
        self.assertEqual(event['source_stamp'], 17.5)
        self.assertEqual(event['start_epoch_ns'], EPOCH+1_000_000_000)
        self.assertEqual(event['end_epoch_ns'], EPOCH+1_004_000_000)
        self.assertEqual(event['truth_receipt_steady'], 1.)
        self.assertAlmostEqual(event['validated']['duration_seconds'], .004)
        self.assertAlmostEqual(event['validated']['dds_to_callback_wait_seconds'], .010)
        self.assertIsNone(event['validated']['message_info']['reception_sequence_number'])
        self.assertEqual(result['summary']['callbacks']['truth']['dds_wait_known_count'], 1)
        self.assertEqual(result['gap_windows'], [])
        json.dumps(result, allow_nan=False)

    def test_unsupported_zero_foreign_future_and_nonfinite_dds_are_unknown(self):
        trace = SamplingTrace()
        values = [None, 0, 1_000_000_000, EPOCH+4_100_000_000, float('nan')]
        for index, received in enumerate(values):
            observed(trace, 'clock', float(index), info=dict(source_timestamp=0,
                received_timestamp=received, publication_sequence_number=None,
                reception_sequence_number=2**64-1))
        result = trace.finalize(6.)
        for event in result['rolling_events']:
            self.assertIsNone(event['validated']['dds_to_callback_wait_seconds'])
            self.assertTrue(event['validated']['dds_to_callback_wait_status'].startswith('unknown:'))
            self.assertIsNone(event['validated']['message_info']['source_timestamp'])
            self.assertIsNone(event['validated']['message_info']['reception_sequence_number'])
        self.assertEqual(result['rolling_events'][0]['message_info_raw']['received_timestamp'], None)
        self.assertEqual(result['rolling_events'][1]['message_info_raw']['received_timestamp'], 0)
        self.assertEqual(result['rolling_events'][2]['message_info_raw']['received_timestamp'], 1_000_000_000)
        self.assertEqual(result['rolling_events'][-1]['message_info_raw']['received_timestamp'], {'nonfinite': 'nan'})
        self.assertEqual(result['summary']['callbacks']['clock']['dds_wait_unknown_count'], 5)
        json.dumps(result, allow_nan=False)

    def test_epoch_changes_in_and_between_callbacks_invalidate_the_wait(self):
        trace = SamplingTrace()
        observed(trace, 'clock', 1.)
        observed(trace, 'truth', 2., epoch_shift_ns=1_000_000_000)
        observed(trace, 'clock', 3., epoch_shift_ns=1_000_000_000)
        observed(trace, 'clock', 4., epoch_shift_ns=1_000_000_000, end_epoch_shift_ns=-500_000_000)
        events = trace.finalize(5.)['rolling_events']
        self.assertEqual([e['validated']['dds_to_callback_wait_status'] for e in events],
                         ['shared_epoch', 'unknown:epoch_clock_changed',
                          'shared_epoch', 'unknown:epoch_clock_changed'])
        self.assertIsNone(events[1]['validated']['dds_to_callback_wait_seconds'])
        self.assertIsNone(events[3]['validated']['dds_to_callback_wait_seconds'])

    def test_authoritative_gap_trigger_survives_unknown_callback_timing(self):
        trace = SamplingTrace()
        observed(trace, 'truth', 0., stamp=0., accepted=True)
        trace.callback('truth', {}, .5, float('nan'), 0, .501, 0,
                       truth_receipt_steady=.5)
        result = trace.finalize(1.)
        window = result['gap_windows'][0]
        trigger = next(event for event in window['events'] if event['id'] == window['trigger_event_id'])
        self.assertEqual(trigger['start_steady'], {'nonfinite': 'nan'})
        self.assertIsNone(trigger['validated']['duration_seconds'])
        self.assertEqual(trigger['validated']['dds_to_callback_wait_status'], 'unknown:invalid_callback_clock')
        self.assertEqual(window['events_dropped_limit'], 0)
        self.assertEqual(window['gaps']['receipt_gap_seconds'], .5)
        self.assertEqual(window['gaps']['source_gap_seconds'], .5)
        json.dumps(result, allow_nan=False)

    def test_conversion_and_derived_bound_overflow_stay_unknown_and_json_safe(self):
        trace = SamplingTrace(context_seconds=1e308)
        trace.stage('total', 0., 10**400)
        observed(trace, 'truth', 0., accepted=True)
        trace.callback('truth', {}, 1e308, 1e308, EPOCH, 1e308, EPOCH,
                       truth_receipt_steady=1e308)
        result = trace.finalize(1e308)
        self.assertIsNone(result['rolling_events'][0]['duration_seconds'])
        window = result['gap_windows'][0]
        self.assertEqual(window['bounds_status'], 'unknown:nonfinite_window_bounds')
        self.assertEqual(window['until_steady'], {'nonfinite': 'inf'})
        self.assertEqual(window['events'][-1]['id'], window['trigger_event_id'])
        self.assertTrue(window['partial'])
        self.assertEqual(result['summary']['window_bounds_unknown_count'], 1)
        json.dumps(result, allow_nan=False)

    def test_only_original_accepted_truths_trigger_receipt_or_source_gaps(self):
        trace = SamplingTrace()
        observed(trace, 'truth', 0., stamp=0., accepted=True)
        observed(trace, 'truth', .3, stamp=.3, accepted=True)
        observed(trace, 'clock', .6, stamp=99.)
        observed(trace, 'truth', .7, stamp=88.)  # The original recorder rejected it.
        observed(trace, 'truth', .8, stamp=.4, accepted=True)  # Receipt gap only.
        observed(trace, 'truth', .9, stamp=.9, accepted=True)  # Source gap only.
        result = trace.finalize(1.)
        self.assertEqual(result['summary']['accepted_truth_count'], 4)
        self.assertEqual(result['summary']['gap_trigger_count'], 2)
        first, second = result['gap_windows']
        self.assertAlmostEqual(first['gaps']['receipt_gap_seconds'], .5)
        self.assertAlmostEqual(first['gaps']['source_gap_seconds'], .1)
        self.assertAlmostEqual(second['gaps']['receipt_gap_seconds'], .1)
        self.assertAlmostEqual(second['gaps']['source_gap_seconds'], .5)
        self.assertTrue(all(window['partial'] for window in result['gap_windows']))

    def test_window_edges_keep_intersecting_stages_and_close_after_context(self):
        trace = SamplingTrace()
        observed(trace, 'truth', 6.9, stamp=0., accepted=True)
        trace.stage('latest_file_write', 6.9, 7.)
        observed(trace, 'truth', 10., stamp=.1, accepted=True)
        trace.stage('spin_once', 9.9, 10.1)  # The executor encloses the callback.
        trace.stage('total', 13., 13.1)
        trace.stage('lifecycle', 13.2, 13.3)
        result = trace.finalize(14.)
        window = result['gap_windows'][0]
        self.assertEqual((window['from_steady'], window['until_steady']), (7., 13.))
        self.assertFalse(window['partial'])
        self.assertEqual([e.get('stage') for e in window['events'] if e['kind'] == 'stage'],
                         ['latest_file_write', 'spin_once', 'total'])
        self.assertEqual(window['closed_at_steady'], 13.1)
        self.assertNotIn(result['rolling_events'][-1], window['events'])

    def test_later_total_stage_keeps_its_overlap_after_spin_closes_the_horizon(self):
        trace = SamplingTrace()
        observed(trace, 'truth', 0., accepted=True)
        observed(trace, 'truth', .5, accepted=True)
        trace.stage('spin_once', 3.4, 3.6)
        trace.stage('lifecycle', 3.6, 3.7)
        trace.stage('total', 3.4, 3.7)
        window = trace.finalize(4.)['gap_windows'][0]
        self.assertFalse(window['partial'])
        self.assertEqual([event['stage'] for event in window['events'] if event['kind'] == 'stage'],
                         ['spin_once', 'total'])

    def test_finalization_keeps_a_partial_window_and_freezes_counters(self):
        trace = SamplingTrace()
        observed(trace, 'truth', 0., accepted=True)
        observed(trace, 'truth', .5, accepted=True)
        result = trace.finalize(1.)
        self.assertTrue(result['gap_windows'][0]['partial'])
        self.assertEqual(result['gap_windows'][0]['closed_at_steady'], 1.)
        self.assertIs(trace.finalize(99.), result)
        with self.assertRaises(RuntimeError):
            observed(trace, 'clock', 2.)
        with self.assertRaises(RuntimeError):
            trace.stage('total', 2., 3.)
        self.assertEqual(trace.summary['event_count'], 2)
        self.assertEqual(trace.summary['callbacks']['clock']['count'], 0)

    def test_stage_maxima_include_evicted_samples_and_unknown_durations(self):
        trace = SamplingTrace(rolling_limit=2)
        trace.stage('spin_once', 0., .2)
        trace.stage('lifecycle', .2, .3, start_epoch_ns=EPOCH, end_epoch_ns=EPOCH+100_000_000)
        trace.stage('latest_file_write', .3, .35)
        trace.stage('total', 0., .35)
        trace.stage('spin_once', 1., 1.01)
        trace.stage('latest_file_write', 2., 1.)
        result = trace.finalize(3.)
        stages = result['summary']['stages']
        self.assertAlmostEqual(stages['spin_once']['duration_max_seconds'], .2)
        self.assertAlmostEqual(stages['lifecycle']['duration_max_seconds'], .1)
        self.assertAlmostEqual(stages['latest_file_write']['duration_max_seconds'], .05)
        self.assertAlmostEqual(stages['total']['duration_max_seconds'], .35)
        self.assertEqual(stages['latest_file_write']['count'], 2)
        self.assertEqual(stages['latest_file_write']['duration_unknown_count'], 1)
        self.assertEqual(result['summary']['rolling_events_evicted'], 4)
        self.assertIsNone(result['rolling_events'][-1]['duration_seconds'])

    def test_cap_losses_are_explicit_and_the_trigger_is_retained(self):
        trace = SamplingTrace(rolling_limit=8, window_limit=2, window_event_limit=3)
        observed(trace, 'truth', 0., accepted=True)
        for step in range(20):
            observed(trace, 'clock', .01*(step+1))
        observed(trace, 'truth', .5, accepted=True)
        for step in range(10):
            observed(trace, 'clock', .51+.01*step)
        result = trace.finalize(1.)
        window = result['gap_windows'][0]
        self.assertEqual(len(window['events']), 3)
        self.assertEqual(window['events'][-1]['id'], window['trigger_event_id'])
        self.assertEqual(window['events_dropped_limit'], 15)  # Five pre-cap plus ten post-cap.
        self.assertTrue(window['pre_context_truncated'])
        self.assertIsNone(window['pre_context_events_dropped'])
        self.assertEqual(result['summary']['pre_context_truncated_windows'], 1)
        self.assertEqual(result['summary']['window_events_dropped_limit'], 15)

    def test_long_recording_is_bounded_with_all_events_counted(self):
        trace = SamplingTrace()
        # 100,000 callbacks span 30 minutes; gaps continue after the 32-window cap.
        for step in range(100_000):
            steady = step*.018
            if step % 250 == 0:
                observed(trace, 'truth', steady, accepted=True)
            else:
                observed(trace, 'clock', steady)
        result = trace.finalize(1800.)
        summary = result['summary']
        self.assertEqual(summary['event_count'], 100_000)
        self.assertEqual(summary['accepted_truth_count'], 400)
        self.assertEqual(summary['gap_trigger_count'], 399)
        self.assertEqual(summary['windows_dropped_limit'], 367)
        self.assertEqual(summary['rolling_events_evicted'], 100_000-1024)
        self.assertEqual(len(result['rolling_events']), 1024)
        self.assertEqual(len(result['gap_windows']), 32)
        self.assertTrue(all(len(window['events']) <= 1024 for window in result['gap_windows']))
        self.assertLessEqual(len(result['rolling_events'])+sum(
            len(window['events']) for window in result['gap_windows']), 1024+32*1024)
        self.assertEqual(summary['callbacks']['truth']['count']+summary['callbacks']['clock']['count'], 100_000)

    def test_fast_stages_count_without_evicting_callback_context(self):
        trace = SamplingTrace(rolling_limit=4)
        observed(trace, 'truth', 1., accepted=True)
        for index in range(10000):
            start = 1.+index*.00001
            trace.stage('total', start, start+.000001)
        observed(trace, 'truth', 1.4, accepted=True)
        result = trace.finalize(1.5)
        stats = result['summary']['stages']['total']
        self.assertEqual(stats['count'], 10000)
        self.assertEqual(stats['short_events_omitted'], 10000)
        self.assertEqual(result['summary']['callbacks']['truth']['count'], 2)
        self.assertFalse(result['gap_windows'][0]['pre_context_truncated'])
        self.assertEqual(result['summary']['rolling_events_evicted'], 0)


if __name__ == '__main__':
    unittest.main()
