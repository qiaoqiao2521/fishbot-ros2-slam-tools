"""RGB-only inventory selection and native metric RGB-D camera checks."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_workcell_vision import add_workcell_cameras, object_points, render_rgbd


def manifest():
    return {'business_entities': {'arms': {
        'load': {'root_body': 'load_base', 'station_position_m': [0., 0., 0.],
                 'station_yaw_rad': 0.},
        'unload': {'root_body': 'unload_base', 'station_position_m': [1., 2., .3],
                   'station_yaw_rad': np.pi/2}}, 'cargo': {
        'cargo_1': {'pickup_offset_m': [0., 0., 0.]},
        'cargo_2': {'pickup_offset_m': [0., .04, 0.]}}}}


class WorkcellConfigurationTests(unittest.TestCase):
    def test_camera_installation_uses_only_declared_fixed_station(self):
        root = ET.fromstring('<mujoco><worldbody/></mujoco>')
        configs = add_workcell_cameras(root, manifest())
        self.assertEqual(len(root.findall('./worldbody/camera')), 2)
        add_workcell_cameras(root, manifest())
        self.assertEqual(len(root.findall('./worldbody/camera')), 2)
        camera = root.find("./worldbody/camera[@name='workcell_unload_camera']")
        np.testing.assert_allclose(np.fromstring(camera.get('pos'), sep=' '),
                                   [1.5, 2.45, .9])
        for config in configs.values():
            rotation = np.array(config['T_station_camera'])[:3, :3]
            np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(rotation), 1.)
        self.assertEqual(configs['load']['slots_station_xy']['cargo_2'], [.24, -.09])
        self.assertEqual(configs['unload']['slots_station_xy']['cargo_2'], [.24, .04])


class ImageInventoryTests(unittest.TestCase):
    def setUp(self):
        self.rgb = np.zeros((80, 80, 3), dtype=np.uint8)
        self.depth = np.full((80, 80), .5, dtype=np.float32)
        self.rgb[32:38, 17:23] = [70, 145, 110]
        self.rgb[52:58, 17:23] = [70, 145, 110]
        self.config = {
            'width': 80, 'height': 80, 'k': [100., 0., 40., 0., 100., 40., 0., 0., 1.],
            'T_station_camera': [[1., 0., 0., 0.], [0., -1., 0., 0.],
                                 [0., 0., -1., .5], [0., 0., 0., 1.]],
            'slots_station_xy': {'cargo_1': [-.1, .025], 'cargo_2': [-.1, -.075]},
            'slot_half_extent_m': [.02, .02], 'minimum_points': 10,
            'colour_prior': {'green_min_u8': 35, 'green_to_red_min': 1.22,
                             'green_to_blue_min': 1.12}}

    def test_selection_distinguishes_two_slots_from_pixels_and_calibration(self):
        first = object_points(self.rgb, self.depth, dict(self.config, target_id='cargo_1'))
        second = object_points(self.rgb, self.depth, dict(self.config, target_id='cargo_2'))
        self.assertEqual(len(first['points_camera']), 36)
        self.assertEqual(len(second['points_camera']), 36)
        self.assertFalse(np.any(first['mask'] & second['mask']))
        self.assertAlmostEqual(float(first['points_camera'][:, 2].mean()), .5)
        self.assertGreater(float(second['points_camera'][:, 1].mean()),
                           float(first['points_camera'][:, 1].mean()))

    def test_missing_colour_or_invalid_depth_does_not_return_a_fabricated_cloud(self):
        for rgb, depth in [(np.zeros_like(self.rgb), self.depth),
                           (self.rgb, np.full_like(self.depth, np.nan)),
                           (self.rgb, np.zeros_like(self.depth))]:
            with self.subTest(depth_valid=np.all(np.isfinite(depth))):
                with self.assertRaisesRegex(ValueError, 'No visible declared-green cargo'):
                    object_points(rgb, depth, self.config)

    def test_outside_slot_green_object_does_not_replace_missing_target(self):
        self.rgb[32:38, 17:23] = 0
        with self.assertRaisesRegex(ValueError, 'inventory slot cargo_1'):
            object_points(self.rgb, self.depth, dict(self.config, target_id='cargo_1'))
        second = object_points(self.rgb, self.depth, dict(self.config, target_id='cargo_2'))
        self.assertEqual(second['point_count'], 36)


class NativeWorkcellRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import mujoco
        except ImportError:
            raise unittest.SkipTest('Native MuJoCo is available in the project planning environment')
        cls.mj = mujoco

    def scene(self, occluded=False):
        root = ET.fromstring('''<mujoco><visual><global offwidth="640" offheight="480"/></visual>
<worldbody><light pos=".4 -.4 1.5" dir="0 0 -1"/>
<geom type="plane" size="2 2 .1" rgba=".4 .4 .4 1"/>
<geom name="first" group="4" type="box" size=".012 .012 .012" pos=".24 -.13 .012" rgba=".28 .57 .43 1"/>
<geom name="second" group="4" type="box" size=".012 .012 .012" pos=".24 -.09 .012" rgba=".28 .57 .43 1"/>
</worldbody></mujoco>''')
        if occluded:
            ET.SubElement(root.find('worldbody'), 'geom', type='box',
                          size='.12 .15 .06', pos='.29 -.20 .16', rgba='.6 .6 .6 1')
        configs = add_workcell_cameras(root, manifest())
        model = self.mj.MjModel.from_xml_string(ET.tostring(root, encoding='unicode'))
        data = self.mj.MjData(model)
        self.mj.mj_forward(model, data)
        return model, data, configs['load']

    def test_native_visible_group_four_surface_has_metric_depth_and_fixed_extrinsics(self):
        model, data, camera = self.scene()
        rgb, depth = render_rgbd(model, data, camera)
        self.assertEqual(rgb.shape, (480, 640, 3))
        self.assertEqual(depth.shape, (480, 640))
        self.assertEqual(depth.dtype, np.float32)
        clouds = []
        for identity, nominal_y in [('cargo_1', -.13), ('cargo_2', -.09)]:
            observed = object_points(rgb, depth, dict(camera, target_id=identity))
            cloud = observed['points_camera']
            T = np.array(camera['T_station_camera'])
            station = cloud @ T[:3, :3].T + T[:3, 3]
            self.assertGreater(len(cloud), 50)
            self.assertLess(abs(float(np.median(station[:, 0])) - .24), .013)
            self.assertLess(abs(float(np.median(station[:, 1])) - nominal_y), .013)
            self.assertGreater(float(np.ptp(station[:, 2])), .008)
            self.assertLess(float(station[:, 2].max()), .026)
            self.assertGreater(float(station[:, 2].min()), -.002)
            clouds.append(observed['mask'])
        self.assertFalse(np.any(clouds[0] & clouds[1]))

    def test_real_rendered_occlusion_produces_observation_failure(self):
        model, data, camera = self.scene(occluded=True)
        rgb, depth = render_rgbd(model, data, camera)
        with self.assertRaisesRegex(ValueError, 'No visible declared-green cargo'):
            object_points(rgb, depth, camera)


if __name__ == '__main__':
    unittest.main()
