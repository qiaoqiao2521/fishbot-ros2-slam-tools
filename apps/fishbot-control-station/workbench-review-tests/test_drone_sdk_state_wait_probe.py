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


if __name__ == '__main__':
    unittest.main()
