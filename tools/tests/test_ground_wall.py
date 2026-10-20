from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fishbot_ground_wall as plant


class GroundWallControlTests(unittest.TestCase):
    def test_independent_chambers_preserve_existing_pump_totals(self):
        import json
        original = json.loads((plant.ROOT/'config/suction_reference.json').read_text())
        c = plant.load_config()
        chamber = plant.chamber_config(c)
        for key in ('chamber_volume_m3','pump_free_flow_m3_s',
                    'leak_conductance_m3_s_pa','pump_idle_power_w'):
            self.assertAlmostEqual(chamber[key]*4,original[key])
        self.assertAlmostEqual(chamber['effective_area_m2']*4,.08)
        self.assertEqual(c['source']['revision'],'78e3677412f1fed881f6436cdaf404f04f28ee4f')

    def test_front_secured_then_release_only_rear_floor_seals(self):
        floor = dict(floor=2,wall=0)
        dual = dict(floor=2,wall=1)
        wall = dict(floor=0,wall=1)
        self.assertEqual(plant.rear_vent_mask([dual,wall,floor,floor]),[False]*4)
        self.assertEqual(plant.rear_vent_mask([wall,wall,floor,wall]),[False,False,True,False])
        self.assertEqual(plant.rear_vent_mask([wall]*4),[False]*4)

    def test_encoder_parking_keeps_bounded_joint_feedback(self):
        brake = plant.WheelBrake(.1,.3,20,12)
        self.assertEqual(brake.update([0]*4,True,1,16,1),[1]*4)
        self.assertEqual(brake.update([3.2]*4,True,5,16,1),[0]*4)
        self.assertEqual(brake.reason,'wheel_encoder_distance')
        result = brake.update([-100,100,3.1,3.3],True,5.1,16,1)
        self.assertEqual(result[:2],[12,-12])
        self.assertAlmostEqual(result[2],2.0)
        self.assertAlmostEqual(result[3],-2.0)

    def test_stalled_approach_times_out_to_wheel_brake(self):
        brake = plant.WheelBrake(.1,.3,20,12)
        brake.update([10]*4,False,10,16,1)
        self.assertIsNone(brake.wall_angles)
        self.assertEqual(brake.update([10]*4,False,16,16,1),[0]*4)
        self.assertEqual(brake.reason,'drive_timeout')

    def test_native_plant_retains_colliding_source_chassis_and_four_hinges(self):
        c = plant.load_config()
        tree = ET.fromstring(plant.model_xml(c))
        chassis = tree.find('.//geom[@name="chassis"]')
        self.assertEqual(chassis.get('size'),'0.21 0.155 0.092')
        self.assertNotEqual(chassis.get('contype'),'0')
        self.assertEqual(len(tree.findall('.//freejoint')),1)
        self.assertEqual(len(tree.findall('.//joint[@type="hinge"]')),4)
        self.assertEqual(len(tree.findall('.//actuator/adhesion')),4)
        drives = tree.findall('.//actuator/velocity')
        self.assertEqual(len(drives),4)
        self.assertTrue(all(x.get('forcerange')=='-12.0 12.0' for x in drives))
        self.assertIsNone(tree.find('equality'))
        self.assertIsNone(tree.find('.//mocap'))


if __name__ == '__main__':
    unittest.main()
