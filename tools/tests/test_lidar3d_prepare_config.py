"""Optional scan config selects the real sensor before native Nav2 parameters."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
from cooperation_prepare import apply_lidar3d_config

class LidarPrepareConfigTests(unittest.TestCase):
    def test_mid360_config_changes_native_shape_and_ranges_without_changing_scene_schema(self):
        m={'scene_profile':{'schema':1,'vehicle':'jackal_j100','sensors':'lidar3d','task':'transport'}}
        original=dict(m['scene_profile'])
        self.assertTrue(apply_lidar3d_config(m,TOOLS/'config/cooperation_profiles/mid360-sensor.json'))
        self.assertEqual(m['scene_profile'],original)
        self.assertEqual((m['lidar3d']['horizontal_samples'],m['lidar3d']['lines']),(4000,1))
        self.assertEqual(m['lidar3d']['min_range_m'],.1)
        from cooperation_lidar import configuration
        self.assertEqual(configuration(m)['topic'],'/sensors/lidar3d/points')
    def test_late_compiled_envelope_enables_self_filter_instead_of_freezing_empty_defaults(self):
        from cooperation_lidar import configuration
        m={'scene_profile':{'sensors':'lidar3d'}}
        self.assertTrue(apply_lidar3d_config(m,TOOLS/'config/cooperation_profiles/mid360-sensor.json'))
        self.assertNotIn('self_filter',m['lidar3d'])
        self.assertFalse(configuration(m)['self_filter']['enabled'])
        m.update(car_footprint_xy=[[-.3,-.2],[.3,-.2],[.3,.2],[-.3,.2]],
            transport_height_envelope={'nominal_base_footprint_world_z_m':.002,
                'compiled_collision_components':[{'bottom_world_m':.002}],
                'unpadded_top_world_m':.302,'max_obstacle_height_m':.312})
        actual=configuration(m)
        self.assertTrue(actual['self_filter']['enabled'])
        self.assertEqual(actual['self_filter']['footprint_xy'],m['car_footprint_xy'])
        self.assertAlmostEqual(actual['self_filter']['z_min_m'],0.)
        self.assertAlmostEqual(actual['self_filter']['z_max_m'],.3)
        self.assertEqual((actual['horizontal_samples'],actual['lines']),(4000,1))

    def test_uniform_config_can_replace_a_mid360_draft(self):
        m={'scene_profile':{'sensors':'lidar3d'}}
        apply_lidar3d_config(m,TOOLS/'config/cooperation_profiles/mid360-sensor.json')
        apply_lidar3d_config(m,TOOLS/'config/cooperation_profiles/uniform16-sensor.json')
        self.assertEqual((m['lidar3d']['horizontal_samples'],m['lidar3d']['lines']),(360,16))
        self.assertEqual(m['lidar3d']['scan_pattern'],'uniform_16_line')
    def test_optional_bad_config_and_planar_selection_warn_without_replacing_current_sensor(self):
        m={'scene_profile':{'sensors':'planar'}}
        with self.assertWarns(RuntimeWarning):self.assertFalse(apply_lidar3d_config(m,TOOLS/'config/cooperation_profiles/mid360-sensor.json'))
        self.assertNotIn('lidar3d',m)
        m={'scene_profile':{'sensors':'lidar3d'},'lidar3d':{'original':True}}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';p.write_text('[]')
            with self.assertWarns(RuntimeWarning):self.assertFalse(apply_lidar3d_config(m,p))
        self.assertEqual(m['lidar3d'],{'original':True})
    def test_unspecified_config_retains_existing_behavior(self):
        m={'scene_profile':{'sensors':'lidar3d'}}
        self.assertFalse(apply_lidar3d_config(m))
        self.assertNotIn('lidar3d',m)

if __name__=='__main__':unittest.main()
