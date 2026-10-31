"""Mechanical adapter checks; no claim that these poses came from inference."""
from pathlib import Path
import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_model_grasp import fit_body_pose, prepare_model_approach, release_sweep, transfer_endpoint
from cooperation_arm import ArmPlanner


class ModelGraspAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = mujoco.MjModel.from_xml_path(str(Path(__file__).resolve().parents[3]/
            'so101/workspaces/so101_ws/src/so101_mujoco/models/so101.xml'))

    def test_native_mink_reproduces_reachable_body_pose(self):
        data = mujoco.MjData(self.model)
        data.qpos[:6] = [.2, -.3, .4, .3, .2, .5]
        mujoco.mj_forward(self.model, data)
        body = self.model.body('gripper').id
        target = np.eye(4)
        target[:3, :3] = data.xmat[body].reshape(3, 3)
        target[:3, 3] = data.xpos[body]
        q, position, rotation = fit_body_pose(self.model, np.array([.18, -.28, .38, .28, .18, .5]), target)
        self.assertIsNotNone(q)
        self.assertLessEqual(position, .001)
        self.assertLessEqual(rotation, .01)

    def test_unreachable_model_pose_is_not_returned_as_joint_goal(self):
        target = np.eye(4)
        target[:3, 3] = [5., 5., 5.]
        q, position, _ = fit_body_pose(self.model, np.array([0., 0., 0., 0., 0., .5]), target)
        self.assertIsNone(q)
        self.assertGreater(position, 1.)

    def test_empty_model_output_does_not_call_ideal_target(self):
        def forbidden():
            self.fail('ideal target must not be used by the model adapter')
        planner = types.SimpleNamespace(np=np, _q6=lambda q: np.asarray(q),
            modules={'joint_planner': None}, grasp_target=forbidden)
        with self.assertRaisesRegex(RuntimeError, 'No executable RGB-D model grasp'):
            prepare_model_approach(planner, [0.]*6, {'candidates': []})

    def test_transfer_admission_uses_declared_cell_or_original_route_override(self):
        station = {'arm_id': 'unload_b', 'shelf_xy_in_station_m': [.05, -.22],
            'cargo_shelf_slots': {'cargo_1': {'center_xy_m': [.02, -.22],
                                            'half_size_xy_m': [.028, .058]}}}
        planner = types.SimpleNamespace(entity_view=types.SimpleNamespace(
            arm_id='unload_b', cargo_id='cargo_1'),
            manifest={'business_entities': {'unload_stations': {'b': station}}})
        self.assertEqual(transfer_endpoint(planner), [.02, -.22, .023])
        station['placement_centers_m'] = [[.18, .14, .06], [.04, -.20, .025]]
        self.assertEqual(transfer_endpoint(planner), [.04, -.20, .025])
        planner.entity_view.arm_id = 'load'
        self.assertEqual(transfer_endpoint(planner), [.24, .14, .023])

    def test_release_sweep_rejects_blocked_middle_even_when_both_endpoints_fit(self):
        from cooperation_scene import source_modules
        source_modules(Path(__file__).resolve().parents[3]/'so101')
        planner = types.SimpleNamespace(np=np, open_checker=types.SimpleNamespace(
            evaluate=lambda q, **kwargs: {'valid': not .18 < q[5] < .32}))
        self.assertTrue(planner.open_checker.evaluate(np.r_[np.zeros(5), .015])['valid'])
        self.assertTrue(planner.open_checker.evaluate(np.r_[np.zeros(5), .5])['valid'])
        result = release_sweep(planner, np.zeros(5))
        self.assertFalse(result['valid'])

    def test_candidate_with_blocked_release_yields_to_next_original_rank(self):
        import json
        from unittest.mock import Mock
        from cooperation_scene import source_modules
        source_modules(Path(__file__).resolve().parents[3]/'so101')
        def evaluate(q, **kwargs):
            return {'valid': not (q[0] == 1. and .18 < q[5] < .32)}
        source = types.SimpleNamespace(
            validate_joint_path=lambda *a, **k: {'valid': True},
            plan_joint_path=lambda start, goal, *a, **k: {'status': 'solved', 'path': [start, goal]})
        planner = types.SimpleNamespace(np=np, rig=object(), _q6=np.asarray,
            entity_view=types.SimpleNamespace(arm_id='load'), car_pose=[],
            modules={'joint_planner': source, 'grasp_episode': types.SimpleNamespace(PINCH_POINT=np.zeros(3))},
            open_checker=types.SimpleNamespace(evaluate=evaluate, is_valid=lambda q: True, bounds=[]),
            closed_checker=types.SimpleNamespace(is_valid=lambda q: True),
            _segment=lambda *args, **kwargs: {'stage': args[0]},
            query_clearance={}, entity_contract=lambda: {})
        poses = [np.eye(4)]*2
        proposals = {'candidates': [{'index': i, 'score': .9-i*.1, 'origin': 'obb',
            'pose_station': pose.tolist()} for i, pose in enumerate(poses)]}
        goals = [np.zeros(5), np.zeros(5), np.array([1., 0., 0., 0., 0.]),
                 np.zeros(5), np.zeros(5), np.array([2., 0., 0., 0., 0.])]
        for direct_valid in (True, False):
            with self.subTest(direct_valid=direct_valid):
                source.validate_joint_path = Mock(side_effect=[{'valid': True}, {'valid': True},
                                                               {'valid': direct_valid}])
                source.plan_joint_path = Mock(side_effect=lambda start, goal, *a, **k:
                    {'status': 'solved', 'path': [np.asarray(start).tolist(), np.asarray(goal).tolist()]})
                with patch('cooperation_model_grasp.fit_body_pose', side_effect=[(q, 0., 0.) for q in goals]):
                    plan = prepare_model_approach(planner, np.zeros(6), proposals)
                result = plan['planning']['model_grasp']
                self.assertEqual(json.loads(json.dumps(plan['planning']))['status'], 'solved')
                self.assertEqual(result['attempts'][0]['reason'], 'transfer_release_collision')
                self.assertEqual(result['selected']['index'], 1)
                self.assertEqual(result['selected']['score'], proposals['candidates'][1]['score'])
                self.assertTrue(result['selected']['transfer_release_sweep']['valid'])
                if direct_valid:
                    source.plan_joint_path.assert_not_called()
                    self.assertEqual(plan['planning']['planner'], 'validated_direct_joint_edge')
                else:
                    source.plan_joint_path.assert_called_once()
                    self.assertFalse(plan['planning']['direct_approach']['valid'])

    def test_public_descriptor_uses_the_actual_mechanical_pinch_frame(self):
        import json
        descriptor = json.loads((Path(__file__).resolve().parents[1]/
            'config/perception/so101-graspgenx-tip-region.json').read_text())
        body_from_model = np.asarray(descriptor['T_body_model'])
        from cooperation_scene import source_modules
        PINCH_POINT = source_modules(Path(__file__).resolve().parents[3]/'so101')['grasp_episode'].PINCH_POINT
        model_pinch = np.linalg.inv(body_from_model) @ np.r_[PINCH_POINT, 1.]
        np.testing.assert_allclose(model_pinch, [0., 0., descriptor['params']['fingertip_depth'], 1.], atol=1e-12)

    def test_cancel_reaps_owned_model_group_even_after_query_parent_exits(self):
        import cooperation_arm
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper, child_pid = root/'query.py', root/'model.pid'
            worker = ('import os,signal,time;from pathlib import Path;'
                      'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                      f'Path({str(child_pid)!r}).write_text(str(os.getpid()));time.sleep(30)')
            helper.write_text('import subprocess,sys,time\n'
                f'subprocess.Popen([sys.executable,"-c",{worker!r}])\n'
                'time.sleep(30)\n')
            def cancel_after_model_started():
                if child_pid.exists():
                    raise RuntimeError('controlled original task cancellation')
            with patch.object(cooperation_arm, '__file__', str(helper)):
                with self.assertRaisesRegex(RuntimeError, 'original task cancellation'):
                    cooperation_arm._query('approach', {'manifest': {'pretrained_grasp': {'enabled': True}}},
                        check=cancel_after_model_started, timeout_s=5.)
            pid = int(child_pid.read_text())
            def running():
                try:
                    return Path(f'/proc/{pid}/stat').read_text().split()[2] != 'Z'
                except FileNotFoundError:
                    return False
            deadline = time.monotonic()+2.
            while running() and time.monotonic() < deadline:
                time.sleep(.02)
            try:
                self.assertFalse(running(), 'model descendant survived original task cancellation')
            finally:
                if running():
                    import signal
                    os.kill(pid, signal.SIGKILL)

    def test_model_release_clears_vertically_before_home_but_ideal_is_unchanged(self):
        from unittest.mock import Mock
        lowering = np.asarray([[0., 0., .2, 0., 0.], [0., 0., .1, 0., 0.]])
        centers = [[.24, .14, .06], [.24, .14, .023]]
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                source = types.SimpleNamespace(
                    validate_joint_path=Mock(return_value={'valid': True}),
                    plan_joint_path=Mock(side_effect=lambda start, goal, *args, **kwargs:
                        {'status':'solved', 'path':[list(start), list(goal)]}))
                planner = types.SimpleNamespace(np=np, manifest={'pretrained_grasp':{'enabled':enabled}},
                    modules={'joint_planner':source}, home=np.zeros(6),
                    open_checker=types.SimpleNamespace(bounds=[[-1.,1.]]*5,
                        is_valid=lambda q:True, margin_m=.001))
                result = ArmPlanner._placement_retreat(planner, lowering[-1], lowering, centers)
                np.testing.assert_allclose(source.plan_joint_path.call_args.args[0],
                    lowering[0] if enabled else lowering[-1])
                if enabled:
                    np.testing.assert_allclose(result['path'][:2], lowering[::-1])
                    self.assertEqual(result['release_detachment']['margin_m'], .001)
                else:
                    source.validate_joint_path.assert_not_called()
                    self.assertNotIn('release_detachment', result)

    def test_invalid_open_jaw_detachment_never_falls_back_to_home_motion(self):
        from unittest.mock import Mock
        source = types.SimpleNamespace(validate_joint_path=Mock(return_value={'valid':False}),
            plan_joint_path=Mock())
        planner = types.SimpleNamespace(np=np, manifest={'pretrained_grasp':{'enabled':True}},
            modules={'joint_planner':source}, home=np.zeros(6),
            open_checker=types.SimpleNamespace(is_valid=lambda q:False))
        with self.assertRaisesRegex(RuntimeError, 'Open-jaw vertical detachment rejected'):
            ArmPlanner._placement_retreat(planner, np.zeros(5), [np.zeros(5)]*2,
                [[.24, .14, .06], [.24, .14, .023]])
        source.plan_joint_path.assert_not_called()


if __name__ == '__main__':
    unittest.main()
