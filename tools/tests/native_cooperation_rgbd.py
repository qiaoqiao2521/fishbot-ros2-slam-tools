"""Real MuJoCo depth and ROS message checks; no navigation or robot commands."""
import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest

import mujoco
import numpy as np
from rclpy.serialization import serialize_message, deserialize_message
from sensor_msgs.msg import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_camera import (CameraRenderer, calibration, depth_message,
                                frame_messages, render_depth, camera_mount)


XML = '''<mujoco><visual><global offwidth="128" offheight="96"/></visual>
<worldbody><camera name="cooperation_camera" pos="0 0 2" fovy="55"/>
<geom type="plane" size="5 5 .1"/>
<geom name="station_tag_occluder" type="box" pos="10 0 0" size=".1 .1 .1" rgba="1 1 1 0"/>
</worldbody></mujoco>'''


def config():
    result = calibration([-1.8, -1.8, 0.])
    result.update(width=64, height=48)
    focal = 24/np.tan(np.deg2rad(55)/2)
    result['k'] = [focal, 0., 31.5, 0., focal, 23.5, 0., 0., 1.]
    return result


def snapshot():
    return dict(stamp=2.9999999996, episode_id='rgbd-test', sequence=17,
                capture_steady_ns=1000, render_duration_s=.01, fault_started=False,
                scene_sha256='source', manifest_sha256='config', qpos=np.zeros(0))


class DepthMessages(unittest.TestCase):
    def test_ros_wire_units_invalid_values_and_shared_identity(self):
        c, s = config(), snapshot()
        depth = np.full((48, 64), 2., dtype=np.float64)
        depth[0, :4] = [np.nan, np.inf, -1., 0.]
        image, info, meta = frame_messages(np.zeros((48, 64, 3), np.uint8), s, c)
        message = deserialize_message(serialize_message(depth_message(depth, s, c)), Image)
        self.assertEqual(message.header, image.header)
        self.assertEqual(message.header, info.header)
        self.assertEqual(message.header, meta.header)
        self.assertEqual((message.header.stamp.sec, message.header.stamp.nanosec), (3, 0))
        self.assertEqual((message.encoding, message.step, message.is_bigendian), ('32FC1', 256, 0))
        values = np.frombuffer(message.data, dtype='<f4').reshape(48, 64)
        self.assertTrue(np.isnan(values[0, :4]).all())
        self.assertEqual(values[20, 30], 2.)
        fields = {item.key for item in meta.status[0].values}
        self.assertNotIn('qpos', fields)
        self.assertNotIn('tag_world_position', fields)

    def test_misaligned_depth_is_not_published_as_registered(self):
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            depth_message(np.ones((96, 128)), snapshot(), config())


class NativeDepth(unittest.TestCase):
    def test_prepare_j100_rgbd_preserves_ideal_mode_and_uses_actual_mount(self):
        import json
        from cooperation_prepare import prepare
        project = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root/'j100.json'
            profile.write_text(json.dumps({'vehicle': 'jackal_j100'}))
            output = root/'scene'
            manifest = prepare(types.SimpleNamespace(
                so101_project=project.parent/'so101', fishbot_project=project,
                output=output, scene_profile=profile, camera_rgbd=True))
            saved = json.loads((output/'scene-manifest.json').read_text())
            self.assertTrue(saved['station_camera']['rgbd_enabled'])
            self.assertEqual(saved['station_perception']['mode'], 'ideal')
            self.assertIn('ideal_station_perception', saved)
            camera = manifest['station_camera']
            self.assertAlmostEqual(camera['base_camera_translation'][2],
                                   manifest['vehicle_profile']['base_link_z_m']+.168)
            model = mujoco.MjModel.from_xml_path(manifest['world_xml'])
            data = mujoco.MjData(model)
            mujoco.mj_forward(model, data)
            with mujoco.Renderer(model, height=480, width=640) as renderer:
                renderer.enable_depth_rendering()
                values = render_depth(renderer, model, data, camera, mujoco.MjvOption())
            self.assertEqual(values.shape, (480, 640))
            self.assertGreater(np.count_nonzero(np.isfinite(values)), 100)

    def test_mount_comes_from_vehicle_model_and_excludes_world_pose(self):
        for height in (.092, .14):
            model = mujoco.MjModel.from_xml_string(f'''<mujoco><worldbody>
              <body name="base_footprint" pos="3 5 .002" euler="0 0 30">
                <body name="base_link" pos="0 0 {height}">
                  <camera name="cooperation_camera" pos="-.06 0 .168" xyaxes="0 1 0 0 0 1"/>
                </body></body></worldbody></mujoco>''')
            mount = camera_mount(model, config())
            np.testing.assert_allclose(mount['base_camera_translation'], [-.06, 0., height+.168], atol=1e-14)
            np.testing.assert_allclose(mount['base_camera_rotation'], config()['base_camera_rotation'], atol=1e-14)
            self.assertEqual(set(mount), {'base_camera_translation', 'base_camera_rotation',
                                         'base_camera_quaternion_xyzw'})

    def test_plane_returns_optical_z_not_range_and_background_is_invalid(self):
        for xml, expected in ((XML, 2.), (XML.replace('<geom type="plane" size="5 5 .1"/>', ''), np.nan)):
            model = mujoco.MjModel.from_xml_string(xml)
            data = mujoco.MjData(model)
            mujoco.mj_forward(model, data)
            with mujoco.Renderer(model, height=48, width=64) as renderer:
                renderer.enable_depth_rendering()
                values = render_depth(renderer, model, data, config(), mujoco.MjvOption())
            self.assertEqual(values.dtype, np.float32)
            np.testing.assert_allclose(values, expected, atol=2e-6)

    def test_native_worker_rgb_only_and_rgbd_use_the_same_snapshot(self):
        for rgbd in (False, True):
            with self.subTest(rgbd=rgbd), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scene = root/'scene.xml'
                scene.write_text(XML)
                texture = root/'tag.png'
                texture.write_bytes(b'fixture-only')
                c = config()
                c.update(tag_texture_file=str(texture),
                         tag_texture_sha256=hashlib.sha256(texture.read_bytes()).hexdigest())
                physics = types.SimpleNamespace(scene=scene, identity={'manifest': {'station_camera': c}},
                                                episode_id='rgbd-test')
                done, captured = threading.Event(), {}
                def rgb(pixels, source):
                    captured['rgb'] = pixels.copy(), dict(source)
                    if not rgbd:
                        done.set()
                def depth(values, source):
                    captured['depth'] = values.copy(), dict(source)
                    done.set()
                worker = CameraRenderer(physics, root/'frames', rgb, depth if rgbd else None)
                try:
                    s = snapshot()
                    s['occluded'] = False
                    worker.slot.offer(s)
                    self.assertTrue(done.wait(10), worker.error)
                finally:
                    worker.close()
                self.assertIsNone(worker.error)
                self.assertFalse(worker.thread.is_alive())
                self.assertEqual(captured['rgb'][0].shape, (48, 64, 3))
                self.assertEqual('depth' in captured, rgbd)
                if rgbd:
                    np.testing.assert_allclose(captured['depth'][0], 2., atol=2e-6)
                    for key in ('stamp', 'episode_id', 'sequence'):
                        self.assertEqual(captured['rgb'][1][key], captured['depth'][1][key])
                evidence = (root/'frames/camera.jsonl').read_text()
                self.assertNotIn('qpos', evidence)


if __name__ == '__main__':
    unittest.main()
