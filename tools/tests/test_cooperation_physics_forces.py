"""Original-scene force owner and R1/R2 integration checks, without ROS."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_checkpoint import capture, restore
from cooperation_scene import build_scene
from cooperation_sim import Physics


class PhysicsForceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        project = Path(__file__).resolve().parents[2]
        cls.manifest = build_scene(project.parent/'so101', project, cls.root/'scene')
        cls.manifest_path = cls.root/'scene/scene-manifest.json'
        cls.manifest_path.write_text(json.dumps(cls.manifest))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def plant(self):
        return Physics(self.manifest['world_xml'], manifest=self.manifest_path)

    def context(self, plant, **updates):
        return dict(world_session_id=plant.world_session_id, episode_id=plant.episode_id,
                    task_id='task-1', native_goal_uuid='ab'*16, stage='car_to_delivery', **updates)

    def offer(self, plant, *, duration=.005, identity='pulse-1'):
        context = self.context(plant)
        event = dict(**context, event_id=identity, body_name='grasp_target',
                     force_world_n=[0., 0., 2.], duration_source_s=duration)
        plant.offer_force_impulse(event, context=context)
        return context

    def test_default_owner_has_no_force_calls_and_legacy_checkpoint_still_restores(self):
        a, b = self.plant(), self.plant()
        with patch.object(a.physical_faults, 'before_step', side_effect=AssertionError('unexpected force')):
            for _ in range(3):
                a.step();b.step()
        self.assertTrue(a.np.array_equal(a.data.qpos, b.data.qpos))
        self.assertTrue(a.np.array_equal(a.data.qvel, b.data.qvel))
        value = capture(a)
        self.assertNotIn('physical_faults', value['application'])
        self.assertNotIn('physical_fault_context', value['application'])
        resumed = self.plant()
        self.assertTrue(restore(resumed, value)['restored'])
        self.assertEqual(resumed.physical_faults.events, {})
        self.assertIsNone(resumed.physical_fault_context)
        self.assertTrue(a.np.array_equal(a.data.qvel, resumed.data.qvel))

    def test_original_cargo_velocity_changes_by_native_force_with_owned_impulse_only(self):
        a, baseline = self.plant(), self.plant()
        body = a.cargo_body
        a.data.xfrc_applied[body, 0] = baseline.data.xfrc_applied[body, 0] = .3
        a.data.xfrc_applied[body, 2] = baseline.data.xfrc_applied[body, 2] = .1
        preserved = a.data.xfrc_applied.copy()
        self.offer(a)
        for _ in range(3):
            a.step();baseline.step()
        joint = int(a.model.body_jntadr[body]);vertical = int(a.model.jnt_dofadr[joint])+2
        self.assertGreater(float(a.data.qvel[vertical]-baseline.data.qvel[vertical]), 1e-5)
        self.assertAlmostEqual(a.physical_faults.status('pulse-1')['impulse_world_ns'][2], .01, places=12)
        self.assertAlmostEqual(float(a.data.time), .006, places=12)
        self.assertEqual(float(a.model.opt.timestep), .002)
        self.assertTrue(a.np.allclose(a.data.xfrc_applied, preserved, atol=1e-15, rtol=0.),
                        float(a.np.max(a.np.abs(a.data.xfrc_applied-preserved))))

    def test_interrupted_pending_r1_snapshot_continues_once_and_matches_native_trajectory(self):
        a = self.plant();a.data.xfrc_applied[a.cargo_body, 2] = .1
        context = self.offer(a, duration=.009)
        a.step();a.physical_faults.before_step(context)
        value = capture(a)
        resumed = self.plant();result = restore(resumed, value, level='R1')
        self.assertTrue(result['restored']);self.assertTrue(result['physical_faults_resumed'])
        self.assertEqual(resumed.physical_fault_context, context)
        self.assertTrue(a.np.array_equal(a.data.xfrc_applied, resumed.data.xfrc_applied))
        for _ in range(4):
            a.step();resumed.step()
        self.assertTrue(a.np.allclose(a.data.qpos, resumed.data.qpos, atol=1e-13, rtol=0.))
        self.assertTrue(a.np.allclose(a.data.qvel, resumed.data.qvel, atol=1e-13, rtol=0.))
        self.assertEqual(a.physical_faults.capture_state(), resumed.physical_faults.capture_state())
        self.assertAlmostEqual(resumed.physical_faults.status('pulse-1')['impulse_world_ns'][2], .018, places=12)
        self.assertAlmostEqual(float(resumed.data.xfrc_applied[resumed.cargo_body, 2]), .1, places=12)

    def test_r2_fence_removes_only_old_pulse_and_does_not_resume_it(self):
        a = self.plant();a.data.xfrc_applied[a.cargo_body, 2] = .1
        context = self.offer(a, duration=.009)
        a.step();a.physical_faults.before_step(context);value = capture(a)
        resumed, comparison = self.plant(), self.plant()
        result = restore(resumed, value, level='R2')
        self.assertTrue(result['restored']);self.assertFalse(result['physical_faults_resumed'])
        self.assertIsNone(resumed.physical_fault_context)
        self.assertNotEqual(resumed.world_session_id, a.world_session_id)
        self.assertEqual(resumed.physical_faults.status('pulse-1')['state'], 'dearmed')
        self.assertAlmostEqual(float(resumed.data.xfrc_applied[resumed.cargo_body, 2]), .1, places=12)
        self.assertTrue(a.np.array_equal(a.data.qpos, resumed.data.qpos))
        self.assertTrue(a.np.array_equal(a.data.qvel, resumed.data.qvel))
        self.assertTrue(restore(comparison, value, level='R1')['restored'])
        comparison.set_force_owner_context(None)
        resumed.step();comparison.step()
        self.assertTrue(a.np.allclose(comparison.data.qvel, resumed.data.qvel, atol=1e-13, rtol=0.))
        self.assertAlmostEqual(resumed.physical_faults.status('pulse-1')['impulse_world_ns'][2], .004, places=12)

    def test_invalid_checkpoint_force_is_rejected_before_target_state_mutation(self):
        a = self.plant();self.offer(a);value = capture(a)
        value['application']['physical_faults']['events']['pulse-1']['effective_duration_source_s'] = 1.
        b = self.plant();b.data.xfrc_applied[b.cargo_body, 0] = .3
        before_q, before_force = b.data.qpos.copy(), b.data.xfrc_applied.copy()
        result = restore(b, value)
        self.assertFalse(result['restored'])
        self.assertTrue(b.np.array_equal(before_q, b.data.qpos))
        self.assertTrue(b.np.array_equal(before_force, b.data.xfrc_applied))
        self.assertEqual(b.physical_faults.events, {})

    def test_owner_change_withdrawal_and_close_preserve_other_wrenches(self):
        a = self.plant();a.data.xfrc_applied[a.cargo_body, 2] = .1
        context = self.offer(a);baseline = a.data.xfrc_applied.copy()
        a.physical_faults.before_step(context)
        invalid = {**context, 'episode_id':'other'}
        with self.assertRaisesRegex(ValueError, 'another physical world'):
            a.set_force_owner_context(invalid)
        self.assertGreater(float(a.data.xfrc_applied[a.cargo_body, 2]), 2.)
        a.set_force_owner_context({**context, 'stage':'car_stopped'})
        self.assertTrue(a.np.allclose(a.data.xfrc_applied, baseline, atol=1e-15, rtol=0.))
        a.offer_force_impulse(dict(**context,event_id='pulse-2',body_name='grasp_target',
                                  force_world_n=[0.,0.,2.],duration_source_s=.005),context=context)
        a.physical_faults.before_step(context);a.set_force_owner_context(None)
        self.assertIsNone(a.physical_fault_context)
        self.assertTrue(a.np.allclose(a.data.xfrc_applied, baseline, atol=1e-15, rtol=0.))
        self.offer(a,identity='pulse-3');a.physical_faults.before_step(context);a.close()
        self.assertTrue(a.np.allclose(a.data.xfrc_applied, baseline, atol=1e-15, rtol=0.))
        self.assertIsNone(a.physical_fault_context)
        withdrawn = capture(a);restored = self.plant()
        self.assertTrue(restore(restored, withdrawn)['restored'])
        self.assertIsNone(restored.physical_fault_context)
        self.assertTrue(a.np.allclose(a.data.xfrc_applied, restored.data.xfrc_applied, atol=1e-15, rtol=0.))

    def test_native_step_failure_withdraws_unstepped_force(self):
        a = self.plant();a.data.xfrc_applied[a.cargo_body, 2] = .1
        self.offer(a);baseline = a.data.xfrc_applied.copy()
        def failed(*args):
            raise RuntimeError('injected native failure')
        a.mj = SimpleNamespace(mj_step=failed)
        with self.assertRaisesRegex(RuntimeError, 'injected native failure'):
            a.step()
        self.assertTrue(a.np.allclose(a.data.xfrc_applied, baseline, atol=1e-15, rtol=0.))
        self.assertEqual(a.physical_faults.status('pulse-1')['impulse_world_ns'], [0.,0.,0.])
        self.assertIsNone(a.physical_fault_context)

    def test_authorized_reset_withdraws_old_force_before_existing_native_reset(self):
        a = self.plant();context = self.offer(a);a.physical_faults.before_step(context)
        a.reset_ready = True
        with patch.object(a, 'reset_physical_quiet', return_value=True):
            episode, stamp = a.reset_episode(a.episode_id)
        self.assertNotEqual(episode, context['episode_id'])
        self.assertIsNone(a.physical_fault_context)
        self.assertEqual(a.physical_faults.status('pulse-1')['state'], 'dearmed')
        self.assertEqual(a.physical_faults.status('pulse-1')['impulse_world_ns'], [0.,0.,0.])
        self.assertEqual(float(a.data.xfrc_applied[a.cargo_body, 2]), 0.)
        self.assertEqual(stamp, 0.)


if __name__ == '__main__':
    unittest.main()
