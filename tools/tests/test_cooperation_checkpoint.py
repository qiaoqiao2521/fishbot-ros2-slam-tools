"""Native state, editable files and incompatible-branch regressions; no ROS."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_checkpoint import (CheckpointIO, capture, read_checkpoint,
                                    prepare_ros_branch, restore, signature, write_checkpoint)
from cooperation_scene import build_scene
from cooperation_sim import Physics, ResetRequests


class CheckpointMailboxTests(unittest.TestCase):
    def test_repeated_request_while_io_pending_has_only_one_capture(self):
        import uuid
        from cooperation_checkpoint import request,receipt
        queue=ResetRequests(parse=request,result=receipt)
        value={'request_id':str(uuid.uuid4()),'episode_id':str(uuid.uuid4()),'issued_at':10.}
        self.assertIsNone(queue.offer(value,now=10.))
        original=queue.take(keep_pending=True)
        self.assertIsNone(queue.offer(value,now=10.1))
        self.assertIsNone(queue.take())
        result=queue.finish(original,receipt(original,snapshot_id=str(uuid.uuid4())))
        self.assertEqual(queue.offer(value,now=20.),result)
        self.assertEqual(queue.pending_ids,set())


class CheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        project = Path(__file__).resolve().parents[2]
        cls.manifest = build_scene(project.parent/'so101', project, cls.root/'scene')
        cls.path = cls.root/'scene/scene-manifest.json'
        cls.path.write_text(json.dumps(cls.manifest))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def plant(self):
        return Physics(self.manifest['world_xml'], manifest=self.path)

    def test_real_file_is_editable_and_large_definition_is_written_once(self):
        a = self.plant()
        for _ in range(10):a.step()
        a.refresh_snapshot();signature(a)
        value = capture(a)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'first.json'
            first = write_checkpoint(path, value)
            second = write_checkpoint(Path(folder)/'second.json', capture(a))
            self.assertGreater(first['new_model_bytes'], first['bytes'])
            self.assertEqual(second['new_model_bytes'], 0)
            edited = json.loads(path.read_text());edited['notes'] = '人工补注，不锁文件'
            path.write_text(json.dumps(edited))
            b = self.plant()
            result = restore(b, read_checkpoint(path))
            self.assertTrue(result['restored'])
            self.assertTrue(a.np.array_equal(a.data.qpos, b.data.qpos))
            self.assertTrue(a.np.array_equal(a.data.qacc_warmstart, b.data.qacc_warmstart))

    def test_changed_mass_or_topology_is_rejected_before_data_changes(self):
        a = self.plant();value = capture(a)
        for field in ('body_mass', 'jnt_type'):
            with self.subTest(field=field):
                b = self.plant()
                getattr(b.model, field)[1] += 1
                before = b.data.qpos.copy()
                result = restore(b, value)
                self.assertFalse(result['restored'])
                self.assertTrue(b.np.array_equal(before, b.data.qpos))

    def test_active_world_cannot_be_rewound_and_bad_rng_is_not_partially_applied(self):
        value = capture(self.plant())
        b = self.plant();b.step();before = b.data.qpos.copy()
        self.assertFalse(restore(b, value)['restored'])
        self.assertTrue(b.np.array_equal(before, b.data.qpos))
        altered = copy.deepcopy(value);altered['application']['beacon']['rng'] = [0]
        c = self.plant();before = c.data.qpos.copy()
        self.assertFalse(restore(c, altered)['restored'])
        self.assertTrue(c.np.array_equal(before, c.data.qpos))

    def test_r2_preserves_physics_but_fences_old_motion_and_uses_new_identity(self):
        a = self.plant()
        a.wheels.set_hold(False);a.wheels.accept(.02, .01, time.monotonic())
        value = capture(a)
        b = self.plant();result = restore(b, value, level='R2')
        self.assertTrue(result['restored'])
        self.assertNotEqual(a.episode_id, b.episode_id)
        self.assertFalse(result['old_motion_commands_restored'])
        self.assertFalse(result['external_components_restored'])
        self.assertTrue(b.wheels.hold)
        self.assertIsNone(b.wheels.last_received)
        self.assertTrue(a.np.array_equal(a.data.qpos, b.data.qpos))
        self.assertIn('Nav2 actions/controllers and DDS queues', result['unrestored_external_components'])

    def test_failed_io_does_not_stop_the_following_independent_write(self):
        value = capture(self.plant())
        io = CheckpointIO()
        try:
            def failed():raise OSError('injected write failure')
            with self.assertRaises(OSError):io.submit(failed).result(timeout=5)
            with tempfile.TemporaryDirectory() as folder:
                result = io.submit(write_checkpoint, Path(folder)/'valid.json', value).result(timeout=20)
                self.assertGreater(result['bytes'], 0)
        finally:io.close()

    def test_branch_uses_parent_tf_and_declares_missing_filter_history(self):
        import yaml
        pose={'x':.23,'y':-.71,'yaw':.12}
        value=capture(self.plant(),context={'localized_pose':pose,
            'localization_source':'parent map->base_footprint TF','localization_covariance':None})
        with tempfile.TemporaryDirectory() as folder:
            nav2=Path(folder)/'parent-nav2.yaml'
            nav2.write_text(yaml.safe_dump({'amcl':{'ros__parameters':{
                'set_initial_pose':True,'initial_pose':{'x':0.,'y':0.,'z':0.,'yaw':0.},
                'initial_cov_xx':.0004,'initial_cov_yy':.0004,'initial_cov_aa':.001}}}))
            value['source']['manifest']['nav2_yaml']=str(nav2)
            checkpoint=Path(folder)/'state.json';write_checkpoint(checkpoint,value)
            branch=prepare_ros_branch(checkpoint,Path(folder)/'branch')
            params=yaml.safe_load(Path(branch['nav2_yaml']).read_text())
            self.assertEqual(params['amcl']['ros__parameters']['initial_pose'],{**pose,'z':0.})
            self.assertFalse(branch['capture_before_delivery'])
            self.assertIsNone(branch['checkpoint_parent']['parent_localization_covariance'])
            self.assertFalse(branch['checkpoint_parent']['external_components_restored'])
            self.assertEqual(branch['world_xml'],self.manifest['world_xml'])
            value['context'].pop('localized_pose')
            write_checkpoint(Path(folder)/'missing-tf.json',value)
            with self.assertRaisesRegex(ValueError,'truth is not a fallback'):
                prepare_ros_branch(Path(folder)/'missing-tf.json',Path(folder)/'bad')
            self.assertFalse((Path(folder)/'bad').exists())


if __name__ == '__main__':
    unittest.main()
