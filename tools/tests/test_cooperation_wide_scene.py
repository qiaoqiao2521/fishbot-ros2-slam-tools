"""Native checks for the J100 workspace, separate from delivery acceptance."""
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
CONFIG = ROOT/'tools/config/factory_delivery'


class WideSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cooperation_prepare import prepare
        cls.temp = tempfile.TemporaryDirectory()
        cls.scenes = {}
        for name, arena in [('original', None), ('wide', CONFIG/'j100-wide-arena.xml')]:
            cls.scenes[name] = prepare(SimpleNamespace(
                so101_project=ROOT.parent/'so101', fishbot_project=ROOT,
                output=Path(cls.temp.name)/name, arena_xml=arena,
                scene_profile=CONFIG/'j100-wide-profile.json',
                factory_config=CONFIG/'j100-wide.json',
                continuous_delivery=CONFIG/'j100-wide-entities.json',
                spawn=(-.9, -1.68), omit_unused_native_rangefinders=True))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_selected_arena_reaches_world_arm_queries_and_collision_map(self):
        from PIL import Image
        import yaml
        m = self.scenes['wide']
        for key in ('world_xml', 'arm_contact_xml', 'rig_xml'):
            geom = ET.parse(m[key]).find(".//geom[@name='baffle_right']")
            xyz = list(map(float, geom.get('pos').split()))
            if key != 'world_xml':
                xyz = [a+b for a,b in zip(xyz, m['station_offset'])]
            self.assertAlmostEqual(xyz[1], 1.8)
        def pixel(scene, x, y):
            path = Path(scene['collision_map_yaml'])
            meta = yaml.safe_load(path.read_text())
            with Image.open(path.parent/meta['image']) as image:
                col = int((x-meta['origin'][0])/meta['resolution'])
                row = image.height-1-int((y-meta['origin'][1])/meta['resolution'])
                return image.getpixel((col,row))
        self.assertEqual(pixel(self.scenes['original'], 1.4, -1.4), 0)
        self.assertEqual(pixel(m, 1.4, -1.4), 254)
        self.assertEqual(pixel(m, 1.4, 1.8), 0)

    def test_vehicle_contact_and_interaction_geometry_are_not_resized(self):
        import mujoco
        old, new = self.scenes['original'], self.scenes['wide']
        for key in ('car_footprint_xy', 'vehicle_profile', 'dock_pose', 'tray_offset',
                    'contact_assumptions', 'arm_home_qpos6'):
            self.assertEqual(old[key], new[key], key)
        models = [mujoco.MjModel.from_xml_path(m['world_xml']) for m in (old,new)]
        for name in ('place_floor', 'tray_mount', 'wall_north', 'wall_south'):
            a,b = [m.geom(name).id for m in models]
            for field in ('geom_size','geom_friction','geom_solref','geom_solimp'):
                self.assertTrue((getattr(models[0],field)[a] == getattr(models[1],field)[b]).all())

    def test_order_goals_match_physical_stations_and_forward_lane_is_clear(self):
        from cooperation_geometry_check import SceneGeometry
        m = self.scenes['wide']; query = SceneGeometry(m)
        # Extra arms must be evaluated at their actual declared home pose.
        for arm in m['business_entities']['arms'].values():
            query.data.qpos[arm['qpos_indices']] = arm['home_qpos6']
        for station in m['factory_delivery']['destinations']:
            self.assertEqual(station['pose'], m['business_entities']['unload_stations'][station['id']]['delivery_pose'])
        minimum = .2
        for i in range(361):
            p = {'x': -.9+i*.01, 'y': -1.68, 'yaw': 0.}
            result = query.check_pose(p)
            self.assertTrue(result['passed'], (p,result))
            minimum = min(minimum, result['minimum_sampled_clearance_m'])
        self.assertGreater(minimum-.005, .025)  # Half-spacing bound, full geometry.
        # Reserve turning outside the handover stations, not inside them.
        for i in range(127):
            result = query.check_pose({'x':2.7,'y':-1.68,'yaw':i*2*math.pi/126})
            self.assertTrue(result['passed'], result)

    def test_stationary_world_has_no_forbidden_contacts(self):
        from cooperation_sim import Physics
        m = self.scenes['wide']
        plant = Physics(m['world_xml'], manifest=Path(m['world_xml']).parent/'scene-manifest.json')
        for _ in range(1000):
            plant.step()
        plant.refresh_snapshot(); state = plant.state()
        self.assertEqual(state['car_forbidden_contact_total'], 0)
        self.assertEqual(state['arm_forbidden_contact_total'], 0)
        self.assertEqual(plant.reset_count, 0)


if __name__ == '__main__':
    unittest.main()
