"""Bounded collector observations; no ROS dependency, file IO, or causal verdicts.

The four MessageInfo fields follow rclpy 7.1.12's subscription binding.  Its
unsupported sequence numbers are None.  DDS timestamps and time.time_ns() use
epoch nanoseconds; source_stamp and steady times belong to separate clocks.
Only a positive DDS epoch within 60 seconds of a stable callback epoch is
validated.  Other values stay raw, with derived measurements marked unknown.
"""

from collections import deque
from copy import deepcopy
import math


MESSAGE_INFO_FIELDS = ('source_timestamp', 'received_timestamp',
                       'publication_sequence_number', 'reception_sequence_number')
STAGES = ('spin_once', 'lifecycle', 'latest_file_write', 'total')


def _finite(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return value if math.isfinite(value) else None
        except OverflowError:
            return None
    return None


def _raw(value):
    """Keep binding scalars; tag invalid input so strict JSON stays possible."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {'nonfinite': str(value)}
    return {'unsupported_type': type(value).__name__}


def _positive_ns(value):
    return value if type(value) is int and 0 < value < 2**63 else None


def _sequence(value):
    return value if type(value) is int and 0 <= value < 2**64-1 else None


def _duration(start, end):
    start, end = _finite(start), _finite(end)
    return end-start if start is not None and end is not None and 0 <= start <= end else None


class SamplingTrace:
    """Keep all-event counters and a bounded tail plus bounded gap windows.

    Call callback() after the original callback.  Supply truth_receipt_steady
    only when the existing recorder accepts a truth sample; gap triggers then
    use that original receipt time and source stamp.  stage() accepts measured
    monotonic boundaries.  Optional stage epochs are raw observations only.
    finalize() returns a strict-JSON-safe artifact for the caller's final flush.
    """

    def __init__(self, *, rolling_limit=1024, window_limit=32, window_event_limit=1024,
                 gap_seconds=.300, context_seconds=3., epoch_tolerance_seconds=.05,
                 dds_epoch_window_seconds=60., stage_event_min_seconds=.001):
        if any(type(value) is not int or value < 1 for value in
               (rolling_limit, window_limit, window_event_limit)):
            raise ValueError('Trace limits must be positive integers')
        if any(_finite(value) is None or value <= 0 for value in
               (gap_seconds, context_seconds, epoch_tolerance_seconds, dds_epoch_window_seconds,
                stage_event_min_seconds)):
            raise ValueError('Trace time bounds must be positive finite seconds')
        self.config = dict(rolling_limit=rolling_limit, window_limit=window_limit,
                          window_event_limit=window_event_limit, gap_seconds=gap_seconds,
                          context_seconds=context_seconds,
                          epoch_tolerance_seconds=epoch_tolerance_seconds,
                          dds_epoch_window_seconds=dds_epoch_window_seconds,
                          stage_event_min_seconds=stage_event_min_seconds)
        self.recent = deque(maxlen=rolling_limit)
        self.windows = []
        self.summary = dict(event_count=0, rolling_events_evicted=0, gap_trigger_count=0,
                            windows_dropped_limit=0, pre_context_truncated_windows=0,
                            window_bounds_unknown_count=0,
                            window_events_dropped_limit=0, accepted_truth_count=0,
                            truth_receipt_gap_max_seconds=None, truth_source_gap_max_seconds=None,
                            callbacks={kind: dict(count=0, duration_unknown_count=0,
                                duration_max_seconds=None, dds_wait_known_count=0,
                                dds_wait_unknown_count=0, dds_wait_max_seconds=None)
                                for kind in ('truth', 'clock')},
                            stages={name: dict(count=0, duration_unknown_count=0,
                                              duration_max_seconds=None, short_events_omitted=0)
                                    for name in STAGES})
        self._previous_truth = None
        self._previous_epoch_pair = None
        self._last_evicted_end = None
        self._watermark = None
        self._result = None

    @staticmethod
    def _maximum(summary, key, value):
        if value is not None and (summary[key] is None or value > summary[key]):
            summary[key] = value

    def _epoch_validity(self, start, start_ns, end, end_ns):
        elapsed = _duration(start, end)
        begin, finish = _positive_ns(start_ns), _positive_ns(end_ns)
        if elapsed is None or begin is None or finish is None:
            self._previous_epoch_pair = None
            return 'unknown:invalid_callback_clock'
        tolerance = self.config['epoch_tolerance_seconds']
        changed = abs((finish-begin)*1e-9-elapsed) > tolerance
        if self._previous_epoch_pair is not None:
            previous_steady, previous_ns = self._previous_epoch_pair
            changed = changed or start < previous_steady or abs(
                (begin-previous_ns)*1e-9-(start-previous_steady)) > tolerance
        self._previous_epoch_pair = (end, finish)
        return 'unknown:epoch_clock_changed' if changed else 'shared_epoch'

    def callback(self, kind, info, source_stamp, start_steady, start_epoch_ns,
                 end_steady, end_epoch_ns, *, truth_receipt_steady=None):
        if self._result is not None:
            raise RuntimeError('Trace already finalized')
        if kind not in self.summary['callbacks']:
            raise ValueError('Callback kind must be truth or clock')
        metadata = {key: info.get(key) if isinstance(info, dict) else getattr(info, key, None)
                    for key in MESSAGE_INFO_FIELDS}
        clock_status = self._epoch_validity(start_steady, start_epoch_ns, end_steady, end_epoch_ns)
        valid_metadata = {key: _sequence(metadata[key]) for key in MESSAGE_INFO_FIELDS[2:]}
        maximum_age = self.config['dds_epoch_window_seconds'] * 1e9
        for key in MESSAGE_INFO_FIELDS[:2]:
            value = _positive_ns(metadata[key])
            valid_metadata[key] = (value if clock_status == 'shared_epoch' and value is not None
                                   and 0 <= start_epoch_ns-value <= maximum_age else None)
        received = valid_metadata['received_timestamp']
        wait = (start_epoch_ns-received)*1e-9 if received is not None else None
        wait_status = clock_status if clock_status != 'shared_epoch' else (
            'shared_epoch' if received is not None else 'unknown:dds_received_epoch_unavailable')
        duration = _duration(start_steady, end_steady)
        event = dict(kind='callback', callback=kind,
                     start_steady=_raw(start_steady), end_steady=_raw(end_steady),
                     start_epoch_ns=_raw(start_epoch_ns), end_epoch_ns=_raw(end_epoch_ns),
                     source_stamp=_raw(source_stamp),
                     message_info_raw={key: _raw(value) for key, value in metadata.items()},
                     validated=dict(source_stamp=_finite(source_stamp), duration_seconds=duration,
                                    message_info=valid_metadata, dds_to_callback_wait_seconds=wait,
                                    dds_to_callback_wait_status=wait_status))
        stats = self.summary['callbacks'][kind]
        stats['count'] += 1
        stats['duration_unknown_count'] += duration is None
        stats['dds_wait_known_count'] += wait is not None
        stats['dds_wait_unknown_count'] += wait is None
        self._maximum(stats, 'duration_max_seconds', duration)
        self._maximum(stats, 'dds_wait_max_seconds', wait)
        gaps = None
        if kind == 'truth' and truth_receipt_steady is not None:
            self.summary['accepted_truth_count'] += 1
            receipt, source = _finite(truth_receipt_steady), _finite(source_stamp)
            event['truth_receipt_steady'] = _raw(truth_receipt_steady)
            if self._previous_truth is not None:
                previous_receipt, previous_source = self._previous_truth
                receipt_gap = _duration(previous_receipt, receipt)
                source_gap = _duration(previous_source, source)
                gaps = dict(receipt_gap_seconds=receipt_gap, source_gap_seconds=source_gap,
                            previous_receipt_steady=_raw(previous_receipt),
                            previous_source_stamp=_raw(previous_source))
                event['truth_gaps'] = gaps
                self._maximum(self.summary, 'truth_receipt_gap_max_seconds', receipt_gap)
                self._maximum(self.summary, 'truth_source_gap_max_seconds', source_gap)
            self._previous_truth = (receipt, source)
        self._append(event)
        if gaps is not None and receipt is not None and any(
                gaps[key] is not None and gaps[key] > self.config['gap_seconds']
                for key in ('receipt_gap_seconds', 'source_gap_seconds')):
            self._open_window(event, receipt, gaps)

    def stage(self, name, start_steady, end_steady, *, start_epoch_ns=None, end_epoch_ns=None):
        if self._result is not None:
            raise RuntimeError('Trace already finalized')
        if name not in self.summary['stages']:
            raise ValueError('Unknown collector stage')
        duration = _duration(start_steady, end_steady)
        stats = self.summary['stages'][name]
        stats['count'] += 1
        stats['duration_unknown_count'] += duration is None
        self._maximum(stats, 'duration_max_seconds', duration)
        # Count every measured call; retain raw spans for slow/unknown calls.
        # Fast empty spins must not evict three seconds of callback context.
        if duration is not None and duration < self.config['stage_event_min_seconds']:
            stats['short_events_omitted'] += 1
            return
        self._append(dict(kind='stage', stage=name, start_steady=_raw(start_steady),
                          end_steady=_raw(end_steady), start_epoch_ns=_raw(start_epoch_ns),
                          end_epoch_ns=_raw(end_epoch_ns), duration_seconds=duration))

    @staticmethod
    def _overlaps(event, lower, upper):
        start, end = _finite(event['start_steady']), _finite(event['end_steady'])
        lower, upper = _finite(lower), _finite(upper)
        return (start is not None and end is not None and lower is not None and upper is not None
                and start <= end and end >= lower and start <= upper)

    def _append(self, event):
        if self._result is not None:
            raise RuntimeError('Trace already finalized')
        self.summary['event_count'] += 1
        event['id'] = self.summary['event_count']
        if len(self.recent) == self.recent.maxlen:
            self.summary['rolling_events_evicted'] += 1
            end = _finite(self.recent[0]['end_steady'])
            if end is not None:
                self._last_evicted_end = max(self._last_evicted_end or end, end)
        self.recent.append(event)
        end = _finite(event['end_steady'])
        if end is not None:
            self._watermark = max(self._watermark or end, end)
        for window in self.windows:
            if self._overlaps(event, window['from_steady'], window['until_steady']):
                self._retain(window, event)
            # Enclosing stages arrive after callbacks and may overlap a closed horizon.
            until = _finite(window['until_steady'])
            if (window['closed_at_steady'] is None and self._watermark is not None
                    and until is not None and self._watermark > until):
                window['closed_at_steady'] = self._watermark
                window['partial'] = False

    def _retain(self, window, event):
        if len(window['events']) < self.config['window_event_limit']:
            window['events'].append(event)
        else:
            window['events_dropped_limit'] += 1
            self.summary['window_events_dropped_limit'] += 1

    def _open_window(self, event, receipt, gaps):
        self.summary['gap_trigger_count'] += 1
        if len(self.windows) >= self.config['window_limit']:
            self.summary['windows_dropped_limit'] += 1
            return
        lower, upper = receipt-self.config['context_seconds'], receipt+self.config['context_seconds']
        bounds_valid = _finite(lower) is not None and _finite(upper) is not None
        truncated = None
        if _finite(lower) is not None:
            truncated = self._last_evicted_end is not None and self._last_evicted_end >= lower
        window = dict(trigger_event_id=event['id'], trigger_steady=receipt, gaps=gaps,
                      from_steady=_raw(lower), until_steady=_raw(upper), closed_at_steady=None, partial=True,
                      bounds_status='finite' if bounds_valid else 'unknown:nonfinite_window_bounds',
                      pre_context_truncated=truncated,
                      pre_context_events_dropped=0 if truncated is False else None,
                      rolling_events_evicted_at_trigger=self.summary['rolling_events_evicted'],
                      events_dropped_limit=0, events=[])
        self.summary['pre_context_truncated_windows'] += truncated is True
        self.summary['window_bounds_unknown_count'] += not bounds_valid
        candidates = [item for item in self.recent if item is event or self._overlaps(item, lower, upper)]
        # Preserve the trigger even with a smaller window cap than the rolling cap.
        excess = max(0, len(candidates)-self.config['window_event_limit'])
        window['events_dropped_limit'] += excess
        self.summary['window_events_dropped_limit'] += excess
        window['events'] = candidates[excess:]
        self.windows.append(window)

    def finalize(self, final_steady):
        if self._result is None:
            final = _finite(final_steady)
            for window in self.windows:
                if window['closed_at_steady'] is None:
                    window['closed_at_steady'] = final
                    until = _finite(window['until_steady'])
                    window['partial'] = final is None or until is None or final < until
            self._result = deepcopy(dict(schema_version=1, config=self.config, summary=self.summary,
                final_steady=_raw(final_steady), rolling_events=list(self.recent), gap_windows=self.windows,
                association='Events use measured local monotonic intervals. Header stamps use the source clock. '
                            'DDS wait is unknown without a stable shared epoch; no cause is assigned.',
                truncation='Rolling evictions and window cap losses are counted. Exact lost pre-context '
                           'event count is unknown after rolling eviction. Short measured stages are '
                           'counted in short_events_omitted; callbacks are not filtered.'))
        return self._result
