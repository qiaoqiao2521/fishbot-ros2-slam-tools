"""Pressure contracts plus genuine native contact contrasts when requested."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

SOURCE = Path(__file__).resolve().parents[1] / 'fishbot_suction.py'
spec = importlib.util.spec_from_file_location('fishbot_suction', SOURCE)
suction = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = suction
spec.loader.exec_module(suction)


class PressureContract(unittest.TestCase):
    def setUp(self):
        self.c = suction.load_config(suction.DEFAULT_CONFIG)

    def test_pressure_builds_to_pump_leak_equilibrium(self):
        chamber = suction.Chamber(self.c)
        for _ in range(2000):
            v = chamber.step(.001, 1, True)
        expected = self.c['pump_free_flow_m3_s'] / (
            self.c['pump_free_flow_m3_s'] / self.c['max_pressure_pa']
            + self.c['leak_conductance_m3_s_pa'])
        self.assertAlmostEqual(v['pressure_pa'], expected, places=4)
        self.assertAlmostEqual(v['requested_adhesion_n'], expected * self.c['effective_area_m2'])
        self.assertGreater(v['electrical_power_w'], v['pneumatic_power_w'])

    def test_failure_vents_without_negative_pressure_or_free_power(self):
        chamber = suction.Chamber(self.c, 7000)
        for _ in range(500):
            v = chamber.step(.001, 0, True, 20)
        self.assertLess(v['pressure_pa'], 1)
        self.assertEqual(v['electrical_power_w'], 0)
        self.assertGreaterEqual(v['pressure_pa'], 0)

    def test_broken_seal_cannot_generate_adhesion(self):
        chamber = suction.Chamber(self.c, 7000)
        v = chamber.step(.01, 1, False)
        self.assertEqual(v['requested_adhesion_n'], 0)
        self.assertLess(v['pressure_pa'], 7000)

    def test_exact_step_is_independent_of_partition(self):
        one, many = suction.Chamber(self.c), suction.Chamber(self.c)
        one.step(.1, 1, True)
        for _ in range(100):
            many.step(.001, 1, True)
        self.assertAlmostEqual(one.pressure_pa, many.pressure_pa, places=8)

    def test_model_has_freejoint_and_native_adhesion_without_weld(self):
        for wall in (False, True):
            xml = ET.fromstring(suction.model_xml(self.c, wall))
            self.assertIsNotNone(xml.find('.//freejoint'))
            self.assertIsNotNone(xml.find('.//adhesion'))
            self.assertIsNone(xml.find('.//equality'))
            self.assertIsNone(xml.find('.//position'))

    def test_partial_config_is_editable_and_reuses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'params.json'
            path.write_text('{"friction":0.3,"criteria":{"max_tilt_rad":0.1}}')
            c = suction.load_config(path)
            self.assertEqual(c['friction'], .3)
            self.assertEqual(c['criteria']['max_tilt_rad'], .1)
            self.assertEqual(c['criteria']['wall_loss_min_drop_m'], .2)


if __name__ == '__main__':
    unittest.main()
