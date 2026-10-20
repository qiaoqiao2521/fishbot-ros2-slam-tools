"""Motion acceptance rejects visual near-success and incomplete source evidence."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ground_wall_score',
    Path(__file__).resolve().parents[1] / 'fishbot_ground_wall_score.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def episode():
    rows = []
    for i in range(281):
        t = round(i * .02, 8)
        theta = min(math.pi / 2, max(0, t - .2) * math.pi / 4)
        turning = .2 < t < 2.2
        omega = math.pi / 4 if turning else 0
        pos = [.06 + .14 * math.cos(theta), 0, .06 + .14 * math.sin(theta)]
        velocity = [-.14 * math.sin(theta) * omega, 0, .14 * math.cos(theta) * omega]
        if t > 2.2:
            pos[2] += min(.25, (t - 2.2) * .1)
            velocity = [0, 0, .1 if t < 4.7 else 0]
        contacts = ([{'floor': 1, 'wall': 0} for _ in range(4)] if t <= .2 else
                    [{'floor': 0, 'wall': 1} for _ in range(4)] if t >= 2.2 else
                    [{'floor': 0, 'wall': 1} for _ in range(2)] +
                    [{'floor': 1, 'wall': 0} for _ in range(2)])
        rows.append({'source_s': t, 'position_m': pos,
                     'quaternion_wxyz': [math.cos(theta / 2), 0, -math.sin(theta / 2), 0],
                     'pitch_up_rad': theta, 'velocity_m_s': velocity,
                     'angular_velocity_rad_s': [0, -omega, 0],
                     'wheel_contacts': contacts, 'pressure_pa': [0 if t <= .2 else 5000] * 4,
                     'phase': 'hold' if t >= 4.7 else 'moving'})
    return rows


class GroundWallOracle(unittest.TestCase):
    def test_complete_same_vehicle_episode_passes(self):
        result = oracle.score(episode())
        self.assertEqual(result['status'], 'passed', result)
        self.assertTrue(result['task_motion_success'])
        self.assertAlmostEqual(result['metrics']['rise_after_upright_m'], .25)
        self.assertGreaterEqual(result['metrics']['final_stationary_wall_hold_s'], .7)

    def test_natural_settling_keeps_original_clock_and_zero_pressure(self):
        rows = episode()
        for row in rows[:4]:
            row['wheel_contacts'] = [{'floor': 0, 'wall': 0} for _ in range(4)]
        result = oracle.score(rows)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['metrics']['source_start_s'], 0)
        self.assertEqual(result['metrics']['initial_floor_source_s'], .08)
        rows[0]['pressure_pa'][0] = 100
        self.assertFalse(oracle.score(rows)['checks']['starts_on_floor_without_pressure'])

    def test_rear_wheels_still_on_floor_is_not_whole_vehicle_success(self):
        rows = episode()
        for row in rows:
            if row['source_s'] >= 2.2:
                row['wheel_contacts'][2]['floor'] = 1
                row['wheel_contacts'][3]['floor'] = 1
        result = oracle.score(rows)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['all_wheels_wall_and_upright'])

    def test_initially_vertical_fixture_is_rejected(self):
        rows = episode()[110:]
        for row in rows:
            row['source_s'] -= 2.2
        result = oracle.score(rows)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['starts_on_floor_without_pressure'])

    def test_source_nonmonotonic_stale_and_missing_samples_are_unknown(self):
        for change in ('duplicate', 'backward', 'missing', 'gap'):
            with self.subTest(change=change):
                rows = episode()
                if change == 'duplicate':
                    rows[50]['source_s'] = rows[49]['source_s']
                elif change == 'backward':
                    rows[50]['source_s'] = 0
                elif change == 'missing':
                    rows[50] = {'source_s': 1.0}
                else:
                    del rows[40:45]
                result = oracle.score(rows)
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(result['task_motion_success'])
                self.assertGreater(result['metrics']['samples'], 250)

    def test_height_gained_before_upright_does_not_count(self):
        rows = episode()
        for row in rows:
            t = row['source_s']
            if .2 < t < 2.2:
                row['position_m'][2] += .3 * (t - .2) / 2
                row['velocity_m_s'][2] += .15
            elif t >= 2.2:
                row['position_m'][2] = .5
                row['velocity_m_s'] = [0, 0, 0]
        result = oracle.score(rows)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['rises_after_upright'])

    def test_movement_during_hold_is_rejected(self):
        rows = episode()
        for row in rows:
            if row['source_s'] >= 4.7:
                row['velocity_m_s'][2] = .011
        result = oracle.score(rows)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['final_stationary_wall_hold'])

    def test_stall_during_drive_is_not_a_commanded_stop(self):
        rows = episode()
        for row in rows:
            row['phase'] = 'drive'
        result = oracle.score(rows)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['final_stationary_wall_hold'])

    def test_teleport_and_inconsistent_reported_pitch_are_detected(self):
        rows = episode()
        rows[150]['position_m'][2] += .5
        self.assertFalse(oracle.score(rows)['checks']['bounded_pose_increments'])
        rows = episode()
        rows[150]['pitch_up_rad'] = 0
        self.assertEqual(oracle.score(rows)['status'], 'unknown')

    def test_no_pump_expected_control_is_separate_from_task_success(self):
        first = episode()[0]
        rows = []
        for i in range(101):
            row = copy.deepcopy(first)
            row['source_s'] = round(i * .02, 8)
            rows.append(row)
        result = oracle.score(rows, expected='no_pump')
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['task_motion_success'])
        impossible = episode()
        for row in impossible:
            row['pressure_pa'] = [0] * 4
        result = oracle.score(impossible, expected='no_pump')
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['does_not_complete_transition'])

    def test_one_bad_episode_does_not_mutate_or_poison_the_next(self):
        rows = episode()
        before = copy.deepcopy(rows)
        self.assertEqual(oracle.score([{'phase': 'bad'}])['status'], 'unknown')
        self.assertEqual(oracle.score(rows)['status'], 'passed')
        self.assertEqual(rows, before)

    def test_missing_initial_source_window_is_unknown(self):
        rows = episode()[20:]
        self.assertEqual(oracle.score(rows)['status'], 'unknown')

    def test_no_pump_does_not_pass_when_only_handoff_evidence_is_absent(self):
        rows = episode()
        for row in rows:
            row['pressure_pa'] = [0] * 4
            if .2 < row['source_s'] < 2.2:
                row['wheel_contacts'] = [{'floor': 1, 'wall': 0} for _ in range(4)]
        result = oracle.score(rows, expected='no_pump')
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['does_not_complete_transition'])

    def test_hold_must_remain_true_at_end_of_success_episode(self):
        rows = episode()
        rows[-1]['wheel_contacts'][0]['wall'] = 0
        result = oracle.score(rows)
        self.assertIsNotNone(result['metrics']['first_completion_source_s'])
        self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
