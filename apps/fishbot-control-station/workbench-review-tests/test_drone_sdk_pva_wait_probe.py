"""Wire gate negative controls; no SDK or vehicle is started."""
import importlib.util
from pathlib import Path
import unittest
import test_drone_sdk_state_wait_probe as state_fixture

path = Path(__file__).resolve().parents[1]/'workbench-tools/drone-sdk-pva-wait-probe.py'
spec = importlib.util.spec_from_file_location('sdk_pva_wait_fixture', path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class PvaWireChecks(unittest.TestCase):
    def rows(self, mode):
        source, _ = state_fixture.EvidenceChecks().fixture()
        rows = [p for p in source if p['host_monotonic_ns'] < 200]
        if mode == 'before_forward':
            for p in rows[:3]:
                p.update(type_mask=2552, x=0., y=0., z=-1., yaw=rows[3]['yaw'])
        return rows, [('pending_unconfirmed',0,99), ('recovery_position',100,199), ('after_stop',200,299)]

    def test_before_and_after_forward_have_different_pending_payload_contracts(self):
        for mode in ('before_forward','after_forward'):
            rows, phases = self.rows(mode)
            self.assertTrue(all(probe.wire_checks(rows, phases, mode).values()))
            other = 'after_forward' if mode == 'before_forward' else 'before_forward'
            self.assertFalse(probe.wire_checks(rows, phases, other)['pending_unconfirmed'])

    def test_wrong_recovery_frame_or_late_pva_is_not_a_position_replacement(self):
        for key, value in [('coordinate_frame',0), ('type_mask',2048), ('z',1.)]:
            rows, phases = self.rows('after_forward')
            rows[-1][key] = value
            self.assertFalse(probe.wire_checks(rows, phases, 'after_forward')['recovery_position'])

    def test_missing_stop_window_or_extra_packet_fails(self):
        rows, phases = self.rows('after_forward')
        self.assertFalse(probe.wire_checks(rows, phases[:-1], 'after_forward')['all_windows_observed'])
        rows.append(dict(rows[-1],host_monotonic_ns=201))
        self.assertFalse(probe.wire_checks(rows, phases, 'after_forward')['after_stop'])


if __name__ == '__main__':
    unittest.main()
