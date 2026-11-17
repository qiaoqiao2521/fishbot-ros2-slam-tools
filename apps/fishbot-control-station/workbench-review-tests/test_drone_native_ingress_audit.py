import importlib.util
from pathlib import Path
import tempfile
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1]/'workbench-tools/drone-native-ingress-audit.py'
spec = importlib.util.spec_from_file_location('native_ingress_audit', SOURCE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def sample(prefix, **extra):
    row = {f'{prefix}{field}[{axis}]': float(axis) for field in ('position', 'velocity', 'acceleration') for axis in range(3)}
    return {**row, **extra}


class NativeAuditTests(unittest.TestCase):
    def test_future_reception_is_reported_and_same_tick_remains_valid(self):
        control = sample('raw_', raw_input_timestamp=100, timestamp=100,
                         raw_input_available=True, input_updated=True)
        for field in ('position', 'velocity'):
            for axis in range(3):
                control[f'used_{field}[{axis}]'] = float('nan')
        control.update({f'used_acceleration[{axis}]': value for axis, value in enumerate([0., 0., 100.])})
        reception = sample('decoded_', decision=5, setpoint_timestamp=100,
                           receive_timestamp=100, timestamp=100, receiver_sequence=1,
                           receiver_channel=1, sender_system=245, sender_component=190,
                           coordinate_frame=1, type_mask=2048, wire_time_boot_ms=999,
                           message_sequence=255)
        future = dict(reception, receive_timestamp=101, receiver_sequence=2, message_sequence=0)
        class Scalar:
            def __init__(self, value): self.value = value
            def item(self): return self.value
        def dataset(name, entries):
            return types.SimpleNamespace(name=name, multi_id=0,
                data={key: [Scalar(row[key]) for row in entries] for key in entries[0]})
        log = types.SimpleNamespace(dropouts=[], data_list=[
            dataset('mavlink_setpoint_ingress', [reception, future]),
            dataset('position_control_handoff', [control])])
        with patch.dict(sys.modules, {'pyulog': types.SimpleNamespace(ULog=lambda path: log)}):
            result = audit.audit_file(Path('/fake/flight.ulg'), Path('/fake'))
        self.assertEqual(result['future_compatible_receptions_excluded'], 1)
        self.assertEqual(result['recorded_stamp_and_pva_matches'], 1)
        self.assertEqual(result['receive_to_control_native_us'], {'count': 1, 'min': 0, 'max': 0})
        self.assertEqual(result['nonincreasing_receiver_sequences'], 0)

    def test_interleaved_channel_does_not_hide_sequence_regression(self):
        self.assertEqual(audit.sequence_regressions([
            {'receiver_channel': 1, 'receiver_sequence': 5},
            {'receiver_channel': 2, 'receiver_sequence': 7},
            {'receiver_channel': 1, 'receiver_sequence': 4}]), 1)

    def test_equal_stamp_with_different_payload_does_not_associate(self):
        control = sample('raw_', raw_input_timestamp=100)
        reception = sample('decoded_', decision=5, setpoint_timestamp=100)
        reception['decoded_acceleration[2]'] = 8.
        self.assertEqual(audit.associate(control, [reception]), ([], 1))

    def test_same_stamp_and_payload_remains_ambiguous(self):
        control = sample('raw_', raw_input_timestamp=100)
        reception = sample('decoded_', decision=5, setpoint_timestamp=100)
        matches, stamps = audit.associate(control, [dict(reception, receiver_sequence=1), dict(reception, receiver_sequence=2)])
        self.assertEqual(stamps, 2)
        self.assertEqual([r['receiver_sequence'] for r in matches], [1, 2])

    def test_rejected_or_different_timestamp_never_counts_as_published(self):
        control = sample('raw_', raw_input_timestamp=100)
        rejected = sample('decoded_', decision=4, setpoint_timestamp=100)
        other = sample('decoded_', decision=5, setpoint_timestamp=101)
        self.assertEqual(audit.associate(control, [rejected, other]), ([], 0))

    def test_position_only_nan_components_match_but_finite_replacement_does_not(self):
        control = sample('raw_', raw_input_timestamp=100)
        reception = sample('decoded_', decision=5, setpoint_timestamp=100)
        for field in ('velocity', 'acceleration'):
            for axis in range(3):
                control[f'raw_{field}[{axis}]'] = float('nan')
                reception[f'decoded_{field}[{axis}]'] = float('nan')
        self.assertEqual(len(audit.associate(control, [reception])[0]), 1)
        reception['decoded_velocity[1]'] = 0.
        self.assertEqual(audit.associate(control, [reception]), ([], 1))

    def test_missing_ulog_stays_unknown_not_an_empty_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit.audit(Path(directory))
        self.assertTrue(result['warnings'])
        self.assertFalse(result['flight_accepted'])
        self.assertEqual(result['unique_rpc_adoption'], 'not_proven')
        self.assertEqual(result['native_files'], [])


if __name__ == '__main__':
    unittest.main()
