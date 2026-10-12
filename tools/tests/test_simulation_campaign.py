"""Campaign policies without starting ROS or a simulator."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fishbot_simulation_campaign import fresh_checkpoint, leg_recording, random_cases
import fishbot_simulation_campaign as campaign


class CampaignBoundaries(unittest.TestCase):
    def test_random_cases_replay_exactly_and_expand_all_four_axes(self):
        cases = random_cases(1200, 20)
        self.assertEqual(cases, random_cases(1200, 20))
        self.assertEqual(len({c['seed'] for c in cases}), 20)
        self.assertEqual(len({tuple(c['target']) for c in cases}), 20)
        self.assertEqual(sum(c['kind'] == 'scan_gap' for c in cases), 5)
        self.assertNotEqual(cases, random_cases(1201, 20))
        for case in cases:
            self.assertTrue(.36 <= case['door_width_m'] <= .46)
            self.assertTrue(abs(case['initial_yaw_rad']) <= .25)

    def test_checkpoint_rejects_stale_source_stale_receipt_and_nonfinite_pose(self):
        sample = dict(steady_time=10., ros_now=5., stamp=4.99,
                      x=0., y=0., yaw=0., linear_speed=0., angular_speed=0.)
        self.assertTrue(fresh_checkpoint(sample, 10.1))
        self.assertFalse(fresh_checkpoint(sample, 10.3))
        self.assertFalse(fresh_checkpoint(dict(sample, stamp=3.), 10.1))
        self.assertFalse(fresh_checkpoint(dict(sample, x=float('nan')), 10.1))
        self.assertFalse(fresh_checkpoint({}, 10.1))

    def test_leg_window_keeps_observed_clock_and_does_not_rejuvenate_truth(self):
        recording = dict(domain=96, truth=[dict(steady_time=t, stamp=t) for t in (1., 2., 3., 4.)],
                         events=[dict(steady_time=t) for t in (1., 2., 4.)], final_ros_now=99.)
        selected = leg_recording(recording, 2., dict(observed_steady_time=3.2, truth={'ros_now':3.1}))
        self.assertEqual([s['steady_time'] for s in selected['truth']], [2., 3.])
        self.assertEqual(selected['final_ros_now'], 3.1)
        self.assertEqual(selected['final_steady_time'], 3.2)
        self.assertEqual(recording['final_ros_now'], 99.)

    def test_guard_events_belong_only_to_the_observed_leg_window(self):
        selected = getattr(campaign, 'events_for_leg', None)
        self.assertTrue(callable(selected), 'Per-leg guard event filtering is not implemented')
        before = {'steady_time': 8., 'kind': 'timing_pause'}
        in_leg = {'steady_time': 10.2, 'kind': 'timing_recovered'}
        future = {'steady_time': 30., 'kind': 'timing_pause'}
        unknown = {'kind': 'timing_pause'}
        original = [before, in_leg, future, unknown]
        result = selected(original, 10., {'observed_steady_time': 12.})
        self.assertEqual(result, [in_leg])
        self.assertEqual(original, [before, in_leg, future, unknown])

    def test_spawned_goal_with_unknown_result_remains_a_failed_case_without_resend(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            spawned = []
            goals_started = []
            class Process:
                returncode = None
                def __init__(self, label):
                    self.pid, self.label = 20000+len(spawned), label
                def poll(self):
                    # The launch fails after the Goal client was admitted.
                    if self.label == 'launch' and goals_started:
                        self.returncode = 1
                        return 1
                    return None
            def start(command, **_options):
                label = 'launch' if command[0] == 'ros2' else 'recorder'
                if any(str(part).endswith('/fishbot_passage_goal.py') for part in command):
                    label = 'goal'
                    goals_started.append(command)
                elif '--collect' in command:
                    (output/'ready.json').write_text('{}')
                    (output/'recording.json').write_text(json.dumps({'domain':96,'truth':[], 'events':[]}))
                process = Process(label)
                spawned.append(process)
                return process
            report = {'cases': [], 'status': 'running'}
            with (patch.object(campaign, 'domain_is_empty'),
                  patch.object(campaign.subprocess, 'Popen', side_effect=start),
                  patch.object(campaign, 'finish_process', return_value=True),
                  patch.object(campaign, 'resource_sample', return_value={}),
                  patch.object(campaign.time, 'sleep')):
                with self.assertRaises(RuntimeError):
                    campaign.run_soak(report, output, 15., {})
            self.assertEqual(len(goals_started), 1)
            self.assertEqual(report['case_count'], 1, 'An admitted unknown Goal disappeared from the denominator')
            self.assertEqual(len(report['cases']), 1)
            case = report['cases'][0]
            self.assertEqual(case['status'], 'failed')
            self.assertFalse(case['passed'])
            self.assertNotEqual(case.get('goal', {}).get('completed'), True)
            self.assertIn('navigation_result', case['unknown_checks'])
            self.assertIn('command_exit', case['unknown_checks'])
            artifacts = output/case['artifact_directory']
            self.assertTrue(artifacts.is_dir())
            self.assertTrue((artifacts/'result.json').is_file())
            self.assertTrue((artifacts/'recording.json').is_file())

    def test_client_exit_before_goal_send_is_attempted_but_not_a_terminal_goal(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            class Process:
                def __init__(self, label):
                    self.pid, self.label = 20001, label
                    self.returncode = 1 if label == 'goal' else None
                def poll(self):
                    return self.returncode
            def start(command, **_options):
                label = 'launch' if command[0] == 'ros2' else 'recorder'
                if any(str(part).endswith('/fishbot_passage_goal.py') for part in command):
                    label = 'goal'
                    goal_output = Path(command[command.index('--output')+1])
                    goal_output.write_text(json.dumps({'completed':False,
                        'error':'guard is not ready; no goal sent'}))
                elif '--collect' in command:
                    (output/'ready.json').write_text('{}')
                    (output/'recording.json').write_text(json.dumps({'domain':96,'truth':[], 'events':[]}))
                return Process(label)
            report = {'cases': [], 'status': 'running'}
            with (patch.object(campaign, 'domain_is_empty'),
                  patch.object(campaign.subprocess, 'Popen', side_effect=start),
                  patch.object(campaign, 'finish_process', return_value=True),
                  patch.object(campaign, 'resource_sample', return_value={}),
                  patch.object(campaign.time, 'sleep')):
                with self.assertRaises(RuntimeError):
                    campaign.run_soak(report, output, 15., {})
            self.assertEqual(report['soak']['attempted_goal_count'], 1)
            self.assertEqual(report['soak']['completed_goal_count'], 0)
            self.assertEqual(report['case_count'], 1)
            self.assertFalse(report['cases'][0]['passed'])


if __name__ == '__main__':
    unittest.main()
