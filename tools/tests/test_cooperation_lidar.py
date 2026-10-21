"""Native ray geometry, standard message encoding and reset-fenced publication."""
import copy
import importlib.util
import math
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import cooperation_lidar as lidar


class ProfileTests(unittest.TestCase):
    def test_planar_mode_does_not_create_a_fake_cloud_profile(self):
        self.assertIsNone(lidar.configuration({}))
        self.assertIsNone(lidar.configuration({'scene_profile': {'sensors': 'planar'}}))
        with self.assertRaises(ValueError): lidar.configuration({'scene_profile': {'sensors': 'unknown'}})

    def test_real_16_line_directions_are_unit_vectors_and_have_vertical_extent(self):
        import numpy as np
        c = lidar.configuration({'scene_profile': {'sensors': 'lidar3d'}})
        rays = lidar.beam_directions(c)
        self.assertEqual(rays.shape, (5760, 3))
        np.testing.assert_allclose(np.linalg.norm(rays, axis=1), 1.)
        self.assertAlmostEqual(float(rays[:, 2].min()), math.sin(math.radians(-15)))
        self.assertAlmostEqual(float(rays[:, 2].max()), math.sin(math.radians(15)))
        self.assertFalse(c['plugin_3_12_loaded'])

    def test_compiled_self_filter_is_public_and_legacy_without_geometry_stays_explicit(self):
        c = lidar.configuration({'scene_profile': {'sensors': 'lidar3d'}})
        self.assertFalse(c['self_filter']['enabled'])
        manifest = {'scene_profile': {'sensors': 'lidar3d'},
                    'car_footprint_xy': [[-.25, -.2], [.25, -.2], [.25, .2], [-.25, .2]],
                    'transport_height_envelope': {'nominal_base_footprint_world_z_m': .002,
                        'max_obstacle_height_m': .252, 'unpadded_top_world_m': .242,
                        'existing_footprint_padding_m': .01,
                        'compiled_collision_components': [{'bottom_world_m': .002}]}}
        c = lidar.configuration(manifest)
        self.assertTrue(c['self_filter']['enabled'])
        self.assertAlmostEqual(c['self_filter']['z_max_m'], .24)
        self.assertEqual(c['self_filter']['padding_xy_m'], 0.)
        self.assertEqual(c['self_filter']['footprint_xy'], manifest['car_footprint_xy'])
        self.assertFalse(c['self_filter']['reraycast_removed_rays'])
        self.assertEqual(c['raw_topic'], '/sensors/lidar3d/points_raw')


@unittest.skipUnless(importlib.util.find_spec('mujoco'), 'use existing planning Python for native sensor tests')
class NativeCloudTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'world.xml'
        self.path.write_text('''<mujoco><worldbody>
          <geom name="floor" type="plane" size="5 5 .1"/>
          <geom name="wall" type="box" pos="2.1 0 1" size=".1 4 1"/>
          <geom name="low_object" type="box" pos="1 0 .05" size=".1 .1 .05"/>
          <body name="base_footprint"><freejoint name="base_free_joint"/>
            <geom name="self_chassis" type="box" size=".5 .5 .2" mass="2"/>
            <body name="laser_link" pos="0 0 .2"/>
          </body></worldbody></mujoco>''')
        self.c = lidar.configuration({'scene_profile': {'sensors': 'lidar3d'}})
        self.query = lidar.NativeCloudQuery(self.path, self.c)

    def snapshot(self):
        return {'qpos': self.query.data.qpos.copy(), 'qvel': self.query.data.qvel.copy(),
                'stamp': .12, 'episode_id': 'episode', 'sequence': 6,
                'scene_sha256': 'scene', 'manifest_sha256': 'manifest'}

    def test_native_cloud_sees_low_object_with_16_returns_and_excludes_self(self):
        import numpy as np
        frame = self.query.compute(self.snapshot())
        points = frame['points']
        self.assertEqual(frame['rows_with_returns'], 16)
        valid = np.isfinite(points).all(axis=1)
        self.assertGreater(int(valid.sum()), 1000)
        # A half-metre self chassis would otherwise occlude surrounding world.
        self.assertGreater(float(np.linalg.norm(points[valid], axis=1).min()), .7)
        low = ((points[:, 0] >= .899) & (points[:, 0] <= 1.101)
               & (np.abs(points[:, 1]) <= .101) & (points[:, 2] + .235 >= .001)
               & (points[:, 2] + .235 <= .101))
        self.assertGreater(int(low.sum()), 0)
        self.assertLess(frame['z_min'], -.1); self.assertGreater(frame['z_max'], .1)

    def test_query_preserves_source_state_and_uses_original_stamp_without_advancing_world(self):
        import numpy as np
        snapshot = self.snapshot(); original = copy.deepcopy(snapshot)
        frame = self.query.compute(snapshot)
        np.testing.assert_array_equal(snapshot['qpos'], original['qpos'])
        np.testing.assert_array_equal(snapshot['qvel'], original['qvel'])
        self.assertEqual(frame['snapshot']['stamp'], .12)
        self.assertEqual(self.query.data.time, .12)
        self.assertEqual(frame['native_version'], '3.3.7')

    def test_standard_pointcloud_roundtrip_keeps_xyz_layout_stamp_and_frame_identity(self):
        import numpy as np
        from sensor_msgs_py import point_cloud2
        frame = self.query.compute(self.snapshot())
        cloud, metadata = lidar.frame_messages(frame, self.c)
        self.assertEqual((cloud.width, cloud.height), (360, 16))
        self.assertEqual(cloud.row_step, cloud.width * cloud.point_step)
        self.assertEqual(len(cloud.data), cloud.row_step * cloud.height)
        self.assertEqual(cloud.header.frame_id, 'lidar3d_link')
        self.assertEqual(cloud.header.stamp.nanosec, 120000000)
        self.assertEqual(metadata.header, cloud.header)
        decoded = point_cloud2.read_points_numpy(cloud, field_names=('x', 'y', 'z'), skip_nans=False)
        np.testing.assert_allclose(decoded.reshape(-1, 3), frame['points'], equal_nan=True)
        evidence = {item.key: item.value for item in metadata.status[0].values}
        self.assertEqual(evidence['episode_id'], 'episode')
        self.assertEqual(evidence['sequence'], '6')


class WorkerFenceTests(unittest.TestCase):
    def test_reset_discards_inflight_old_episode_without_relabeling_its_stamp(self):
        import numpy as np
        entered, release = threading.Event(), threading.Event()
        class SlowQuery:
            def __init__(self, *unused): pass
            def compute(self, snapshot):
                entered.set(); release.wait(2.)
                return {'snapshot': snapshot, 'compute_duration_s': .001, 'valid_points': 1,
                        'rows_with_returns': 1, 'z_min': -.1, 'z_max': .1, 'native_version': '3.3.7'}
        physics = SimpleNamespace(scene='query-only', data=SimpleNamespace(qpos=np.zeros(7), qvel=np.zeros(6), time=.1),
            state_sequence=5, episode_id='old', identity={'scene_sha256': 'scene', 'manifest_sha256': 'manifest'})
        published = []
        with patch.object(lidar, 'NativeCloudQuery', SlowQuery), \
                patch.object(lidar, 'frame_messages', side_effect=lambda frame, c: (frame['snapshot'], {})), \
                patch.object(lidar, 'raw_frame_message', side_effect=lambda frame, c: frame['snapshot']):
            worker = lidar.CloudWorker(physics, {}, lambda *args: published.append(args),
                                       publish_raw=lambda value: published.append(('raw', value)))
            try:
                worker.offer(); self.assertTrue(entered.wait(1.))
                worker.slot.fence('new'); release.set()
            finally:
                worker.close()
        self.assertEqual(published, [])
        self.assertIsNone(worker.error)
        self.assertEqual(worker.raw_frames, 0)


@unittest.skipUnless(importlib.util.find_spec('mujoco'), 'use existing planning Python for native sensor tests')
class NativeSelfFilterTests(unittest.TestCase):
    def setUp(self):
        import mujoco
        self.mj = mujoco
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'world.xml'
        self.path.write_text('''<mujoco><worldbody>
          <geom name="floor" type="plane" size="5 5 .1"/>
          <geom name="wall" type="box" pos="2.1 0 1" size=".1 4 1"/>
          <geom name="low_outside" type="box" pos=".8 0 .05" size=".08 .08 .05"/>
          <body name="base_footprint"><freejoint name="base_free_joint"/>
            <geom name="chassis" type="box" pos="0 0 .04" size=".25 .2 .04" mass="2"/>
            <geom name="load_support" type="box" pos="-.2 0 .183" size=".025 .025 .001"/>
            <body name="laser_link" pos="0 0 .2"/>
          </body>
          <body name="grasp_target" pos="-.2 0 .192"><freejoint/>
            <geom name="cargo" type="box" size=".009 .009 .008" mass=".01"/>
          </body></worldbody></mujoco>''')
        self.c = lidar.configuration({'scene_profile': {'sensors': 'lidar3d'},
            'car_footprint_xy': [[-.25, -.2], [.25, -.2], [.25, .2], [-.25, .2]],
            'transport_height_envelope': {'nominal_base_footprint_world_z_m': 0.,
                'max_obstacle_height_m': .25, 'unpadded_top_world_m': .24,
                'existing_footprint_padding_m': .01,
                'compiled_collision_components': [{'bottom_world_m': 0.}]}})
        self.query = lidar.NativeCloudQuery(self.path, self.c)

    def snapshot(self):
        return {'qpos': self.query.data.qpos.copy(), 'qvel': self.query.data.qvel.copy(),
                'stamp': 8.42, 'episode_id': 'loaded-episode', 'sequence': 421,
                'scene_sha256': 'scene', 'manifest_sha256': 'manifest'}

    def test_first_cargo_returns_are_nan_without_recasting_and_outside_low_object_remains(self):
        import numpy as np
        snapshot = self.snapshot(); before = copy.deepcopy(snapshot)
        collision_masks = (self.query.model.geom_contype.copy(), self.query.model.geom_conaffinity.copy())
        frame = self.query.compute(snapshot)
        raw = np.isfinite(frame['raw_points']).all(axis=1)
        removed = raw & ~np.isfinite(frame['points']).all(axis=1)
        self.assertGreater(frame['self_filter_removed_points'], 0)
        self.assertEqual(int(removed.sum()), frame['self_filter_removed_points'])
        cargo_id = self.query.model.geom('cargo').id
        self.assertTrue(np.all(self.query.hit[removed] == cargo_id))
        # Low obstacles beside the robot stay in the filtered cloud.
        low = self.query.hit == self.query.model.geom('low_outside').id
        self.assertTrue(np.any(low)); self.assertTrue(np.isfinite(frame['points'][low]).all())
        self.assertEqual(frame['points'].shape, (5760, 3))
        self.assertEqual(frame['snapshot'], snapshot)
        np.testing.assert_array_equal(snapshot['qpos'], before['qpos'])
        np.testing.assert_array_equal(snapshot['qvel'], before['qvel'])
        np.testing.assert_array_equal(self.query.model.geom_contype, collision_masks[0])
        np.testing.assert_array_equal(self.query.model.geom_conaffinity, collision_masks[1])
        self.assertEqual(self.query.data.time, 8.42)

    def test_same_cargo_outside_full_footprint_is_retained_and_empty_vehicle_removes_nothing(self):
        import numpy as np
        snapshot = self.snapshot()
        snapshot['qpos'][7:10] = [0., .7, .192]
        frame = self.query.compute(snapshot)
        cargo = self.query.hit == self.query.model.geom('cargo').id
        self.assertTrue(np.any(cargo))
        self.assertTrue(np.isfinite(frame['points'][cargo]).all())
        self.assertEqual(frame['self_filter_removed_points'], 0)
        snapshot['qpos'][7:10] = [4., 4., .192]
        empty = self.query.compute(snapshot)
        self.assertEqual(empty['self_filter_removed_points'], 0)
        np.testing.assert_array_equal(empty['raw_points'], empty['points'])

    def test_raw_and_filtered_standard_messages_keep_identical_source_identity(self):
        import numpy as np
        from sensor_msgs_py import point_cloud2
        frame = self.query.compute(self.snapshot())
        filtered, metadata = lidar.frame_messages(frame, self.c)
        raw = lidar.raw_frame_message(frame, self.c)
        self.assertEqual(raw.header, filtered.header)
        self.assertEqual((raw.width, raw.height), (360, 16))
        self.assertEqual((filtered.width, filtered.height), (360, 16))
        self.assertEqual(raw.header.stamp.sec, 8); self.assertEqual(raw.header.stamp.nanosec, 420000000)
        self.assertEqual(len(raw.data), len(filtered.data))
        points = point_cloud2.read_points_numpy(raw, field_names=('x', 'y', 'z'), skip_nans=False)
        np.testing.assert_allclose(points.reshape(-1, 3), frame['raw_points'], equal_nan=True)
        fields = {item.key: item.value for item in metadata.status[0].values}
        self.assertEqual(fields['episode_id'], 'loaded-episode'); self.assertEqual(fields['sequence'], '421')
        self.assertEqual(fields['self_filter_enabled'], 'true')
        self.assertEqual(int(fields['self_filter_removed_points']), frame['self_filter_removed_points'])

    def test_points_one_millimeter_outside_body_xy_or_z_are_never_self_masked(self):
        import numpy as np
        points = np.array([[.251, 0., .1], [0., 0., .241], [.25, 0., .24]])
        np.testing.assert_array_equal(lidar.body_contains(
            points, self.query.body_halfspaces, self.c['self_filter']), [False, False, True])
        snapshot = self.snapshot()
        snapshot['qpos'][7:10] = [.26, 0., .192]
        frame = self.query.compute(snapshot)
        cargo = self.query.hit == self.query.model.geom('cargo').id
        self.assertTrue(np.any(cargo))
        self.assertAlmostEqual(float(frame['raw_points'][cargo, 0].min()), .251, places=6)
        self.assertTrue(np.isfinite(frame['points'][cargo]).all())
        self.assertEqual(frame['self_filter_removed_points'], 0)

    def test_mask_uses_source_base_transform_and_full_convex_shape(self):
        import numpy as np
        snapshot = self.snapshot(); yaw = .7
        rotation = np.array([[math.cos(yaw), -math.sin(yaw), 0.],
                             [math.sin(yaw), math.cos(yaw), 0.], [0., 0., 1.]])
        translation = np.array([1., -.4, 0.])
        snapshot['qpos'][:3] = translation
        snapshot['qpos'][3:7] = [math.cos(yaw/2), 0., 0., math.sin(yaw/2)]
        snapshot['qpos'][7:10] = translation + rotation @ np.array([-.2, 0., .192])
        snapshot['qpos'][10:14] = snapshot['qpos'][3:7]
        frame = self.query.compute(snapshot)
        removed = np.isfinite(frame['raw_points']).all(axis=1) & ~np.isfinite(frame['points']).all(axis=1)
        self.assertGreater(int(removed.sum()), 0)
        self.assertTrue(np.all(self.query.hit[removed] == self.query.model.geom('cargo').id))
        # A point inside a footprint's AABB but beyond a sloping convex edge
        # must remain visible. Do not approximate every vehicle as a rectangle.
        c = copy.deepcopy(self.c)
        c['self_filter']['footprint_xy'] = [[-.25, -.2], [.25, -.2], [.25, .2]]
        triangle = lidar.NativeCloudQuery(self.path, c)
        outside = triangle.compute(self.snapshot())
        cargo = triangle.hit == triangle.model.geom('cargo').id
        self.assertTrue(np.any(cargo)); self.assertTrue(np.isfinite(outside['points'][cargo]).all())


if __name__ == '__main__': unittest.main()
