"""Protocol evidence checks, no SDK process or vehicle."""
import importlib.util
import math
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1]/'workbench-tools/drone-sdk-state-wait-probe.py'
spec = importlib.util.spec_from_file_location('sdk_state_wait_probe_fixture', path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class EvidenceChecks(unittest.TestCase):
    def fixture(self):
        phases = [('pva_pending', 0, 99), ('position_before_late', 100, 199),
                  ('position_after_late', 200, 299), ('after_stop', 300, 399)]
        rows = []
        for i, (name, start, _) in enumerate(phases[:-1]):
            for n in range(3):
                values = [0., 1., -1., .1, .2, 0., 0., .01, 0.] if not i else [0., 0., -1., 0., 0., 0., 0., 0., 0.]
                rows.append(dict(type='SET_POSITION_TARGET_LOCAL_NED', host_monotonic_ns=start+n,
                    type_mask=2048 if not i else 2552, time_boot_ms=start+n, coordinate_frame=1,
                    target_system=7, target_component=1, yaw=math.pi/2-(.25 if not i else 0.),
                    **dict(zip(('x', 'y', 'z', 'vx', 'vy', 'vz', 'afx', 'afy', 'afz'), values))))
        return rows, phases

    def test_valid_cache_windows_and_stop_are_distinct(self):
        rows, phases = self.fixture()
        self.assertTrue(all(probe.wire_checks(rows, phases).values()))

    def test_a_late_pva_packet_or_wrong_frame_cannot_count_as_position_hold(self):
        for key, value in [('type_mask', 2048), ('coordinate_frame', 0), ('x', 2.)]:
            with self.subTest(key=key):
                rows, phases = self.fixture()
                rows[-1][key] = value
                self.assertFalse(probe.wire_checks(rows, phases)['position_after_late'])

    def test_missing_window_or_packets_after_stop_fail_evidence(self):
        rows, phases = self.fixture()
        self.assertFalse(probe.wire_checks(rows, phases[:-1])['all_windows_observed'])
        rows.append(dict(rows[-1], host_monotonic_ns=301))
        self.assertFalse(probe.wire_checks(rows, phases)['after_stop'])

    def fault_fixture(self, mode):
        rows, phases = self.fixture()
        names = {'position_before_late': 'cache_after_unconfirmed',
                 'position_after_late': 'cache_after_late_response'}
        phases = [(names.get(name, name), start, end) for name, start, end in phases]
        if mode == 'before_forward':
            payload = {k: v for k, v in rows[0].items()
                       if k not in ('host_monotonic_ns', 'time_boot_ms')}
            for row in rows[3:]:
                row.update(payload)
        return rows, phases

    def test_recovery_response_loss_preserves_two_distinct_remote_outcomes(self):
        for mode, other in (('before_forward', 'after_forward'), ('after_forward', 'before_forward')):
            with self.subTest(mode=mode):
                rows, phases = self.fault_fixture(mode)
                self.assertTrue(all(probe.wire_checks(rows, phases, mode).values()))
                self.assertFalse(probe.wire_checks(rows, phases, other)['cache_after_unconfirmed'])

    def test_late_distinct_pva_cannot_pass_as_retained_cache(self):
        for mode in ('before_forward', 'after_forward'):
            with self.subTest(mode=mode):
                rows, phases = self.fault_fixture(mode)
                # Same old PVA mask is insufficient: the late response has a new position.
                rows[-1].update(type_mask=2048, x=2., y=3., z=-1.5)
                self.assertFalse(probe.wire_checks(rows, phases, mode)['cache_after_late_response'])

    def test_fault_injection_still_requires_every_window_and_explicit_stop(self):
        for mode in ('before_forward', 'after_forward'):
            with self.subTest(mode=mode):
                rows, phases = self.fault_fixture(mode)
                self.assertFalse(probe.wire_checks(rows, phases[:-1], mode)['all_windows_observed'])
                rows.append(dict(rows[-1], host_monotonic_ns=301))
                self.assertFalse(probe.wire_checks(rows, phases, mode)['after_stop'])


if __name__ == '__main__':
    unittest.main()
