"""Configuration composition checks; real sensor publication needs ROS acceptance."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('lidar3d', ROOT / 'tools/fishbot_lidar3d.py')
lidar3d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lidar3d)


class Lidar3dTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scene = self.root / 'scene.xml'
        self.scene.write_text('<mujoco><include file="robot.xml"/><worldbody>'
                              '<geom name="floor" type="plane" size="5 5 0.1"/>'
                              '</worldbody></mujoco>')
        (self.root / 'robot.xml').write_text(
            '<mujoco><compiler angle="radian"/><worldbody><body name="laser_link">'
            '<site name="old_ray"/></body></worldbody><sensor>'
            '<rangefinder name="laser" site="old_ray"/></sensor></mujoco>')

    def prepare(self, **kwargs):
        return lidar3d.prepare(self.scene, self.root / 'out', **kwargs)

    def test_preserves_2d_sensor_adds_official_16_line_sensor_and_correct_transform(self):
        before = self.scene.read_text()
        result = self.prepare()
        tree = ET.parse(result['scene']).getroot()
        self.assertIsNotNone(tree.find('.//rangefinder[@name="laser"]'))
        sensor = tree.find('.//sensor/plugin[@name="generic_lidar3d"]')
        self.assertEqual(sensor.get('objname'), 'fishbot_lidar3d_site')
        config = {e.get('key'): e.get('value') for e in tree.findall('.//instance/config')}
        self.assertEqual(config['resolution'], '360 16')
        self.assertEqual(config['update_rate'], '10.0')
        self.assertEqual(config['async'], '0')
        self.assertEqual(result['static_transform']['translation'], [0.0, 0.0, 0.035])
        self.assertEqual(result['static_transform']['parent_frame'], 'laser_link')
        self.assertEqual(result['static_transform']['child_frame'], 'lidar3d_link')
        self.assertEqual(self.scene.read_text(), before)

    def test_merges_original_plugins_and_both_costmaps_without_removing_localization_scan(self):
        result = self.prepare()
        plugins = yaml.safe_load(Path(result['plugins']).read_text())['/**']['ros__parameters']['mujoco_plugins']
        self.assertIn('rangefinder_lidar_plugin', plugins)
        wrapper = plugins['mujoco_3d_lidar_plugin']
        self.assertEqual(wrapper['generic_lidar3d']['frame_name'], 'lidar3d_link')
        self.assertEqual(wrapper['generic_lidar3d']['topic'], '/sensors/lidar3d/points')
        nav = yaml.safe_load(Path(result['nav2']).read_text())
        local = nav['local_costmap']['local_costmap']['ros__parameters']
        self.assertEqual(local['voxel_layer']['observation_sources'], 'scan lidar3d')
        self.assertEqual(local['voxel_layer']['scan']['data_type'], 'LaserScan')
        global_map = nav['global_costmap']['global_costmap']['ros__parameters']
        self.assertIn('obstacle_layer', global_map['plugins'])
        self.assertIn('lidar3d_voxel_layer', global_map['plugins'])
        self.assertEqual(global_map['lidar3d_voxel_layer']['lidar3d']['data_type'], 'PointCloud2')
        self.assertEqual(nav['amcl'], yaml.safe_load((lidar3d.PACKAGE / 'config/nav2.yaml').read_text())['amcl'])

    def test_metadata_is_optional_and_editable_profile_changes_only_generated_outputs(self):
        profile = self.root / 'profile.yaml'
        profile.write_text('fishbot_lidar3d_profile:\n  ros__parameters:\n'
                           '    lines: 32\n    rate_hz: 5.0\n    topic: /custom_points\n')
        with self.assertLogs('lidar3d', level='WARNING') as logs:
            result = self.prepare(profile_path=profile, metadata_path=self.root / 'missing.json')
        self.assertTrue(any('metadata' in line for line in logs.output))
        tree = ET.parse(result['scene']).getroot()
        config = {e.get('key'): e.get('value') for e in tree.findall('.//instance/config')}
        self.assertEqual(config['resolution'], '360 32')
        self.assertEqual(config['update_rate'], '5.0')
        self.assertEqual(result['topic'], '/custom_points')
        self.assertEqual(result['metadata'], {})

    def test_included_asset_paths_remain_anchored_to_original_file(self):
        (self.root / 'robot.xml').write_text('<mujoco><compiler meshdir="meshes"/>'
            '<asset><mesh name="part" file="part.stl"/></asset><worldbody>'
            '<body name="laser_link"/></worldbody></mujoco>')
        tree = ET.parse(self.prepare()['scene']).getroot()
        self.assertEqual(tree.find('.//mesh').get('file'), str(self.root / 'meshes/part.stl'))

    def test_contact_audit_is_opt_in_and_uses_existing_native_plugin(self):
        normal = self.prepare()
        plugins = yaml.safe_load(Path(normal['plugins']).read_text())['/**']['ros__parameters']['mujoco_plugins']
        self.assertNotIn('contact_audit', plugins)
        audited = self.prepare(audit_contacts=True)
        plugins = yaml.safe_load(Path(audited['plugins']).read_text())['/**']['ros__parameters']['mujoco_plugins']
        self.assertEqual(plugins['contact_audit'], {
            'type': 'fishbot_mujoco/ContactAudit', 'robot_body': 'base_footprint',
            'floor_geoms': ['floor'],
        })

    def test_selected_private_prefix_and_explicit_library_are_consistent(self):
        prefix = self.root / 'selected'
        library = prefix / 'lib/mujoco_3d_lidar/mujoco_plugin/libmujoco_3d_lidar.so'
        library.parent.mkdir(parents=True)
        library.touch()
        with patch.dict('os.environ', {'FISHBOT_LIDAR3D_PREFIX': str(prefix)}):
            self.assertEqual(self.prepare()['library'], str(library))
            explicit = self.root / 'explicit.so'
            explicit.touch()
            self.assertEqual(self.prepare(library_path=explicit)['library'], str(explicit))

    def test_current_arena_can_be_composed_and_reprepared_without_duplicate_sensor(self):
        result = lidar3d.prepare(lidar3d.PACKAGE / 'mjcf/arena.xml', self.root / 'arena')
        repeated = lidar3d.prepare(result['scene'], self.root / 'again')
        tree = ET.parse(repeated['scene']).getroot()
        self.assertEqual(len(tree.findall('.//sensor/plugin[@name="generic_lidar3d"]')), 1)
        self.assertEqual(len(tree.findall('.//site[@name="fishbot_lidar3d_site"]')), 1)


if __name__ == '__main__':
    unittest.main()
