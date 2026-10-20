from copy import deepcopy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fishbot_vacuum_hardware as hardware


class VacuumHardwareTests(unittest.TestCase):
    def test_nonzero_mass_collision_and_tensor_include_real_pump(self):
        c = hardware.load_hardware()
        parts = hardware.hardware_parts(c)
        pump = next(p for p in parts if p['name'] == 'vacuum_pump')
        self.assertEqual(pump['mass_kg'], .6)
        self.assertEqual(pump['dimensions_m'], [.106, .043, .074])
        self.assertTrue(all(p['mass_kg'] > 0 and min(p['inertia_diagonal']) > 0 for p in parts))
        root = ET.fromstring('<body>'+hardware.hardware_xml(c)+'</body>')
        self.assertEqual(len(root.findall('body')), len(parts))
        self.assertTrue(all(g.get('contype') == '1' and g.get('conaffinity') == '1' for g in root.findall('.//geom')))

    def test_added_mass_changes_combined_com_and_inertia(self):
        c = hardware.load_hardware()
        result = hardware.mass_properties(c, 18.431, [.012, .002, .067], [.4, .5, .6, 0, 0, 0])
        self.assertGreater(result['added_mass_kg'], 1.2)
        self.assertLess(result['added_mass_kg'], 1.5)
        self.assertAlmostEqual(result['total_mass_kg'], 18.431+result['added_mass_kg'])
        self.assertGreater(result['center_of_mass_m'][2], .067)
        self.assertGreater(result['fullinertia'][0], .4)
        self.assertGreater(result['fullinertia'][1], .5)
        # A translated installation changes the total COM exactly, rather than
        # being a massless visual that leaves the original dynamics unchanged.
        shifted = deepcopy(c)
        shifted['pump']['position_m'][0] += .1
        delta = hardware.mass_properties(shifted, 18.431, [.012, .002, .067], [.4, .5, .6, 0, 0, 0])
        self.assertAlmostEqual(delta['center_of_mass_m'][0]-result['center_of_mass_m'][0], .6*.1/result['total_mass_kg'])

    def test_single_pump_total_flow_and_power_do_not_scale_fourfold(self):
        c = hardware.load_hardware()
        network = hardware.SharedVacuumNetwork(c, [.02]*4)
        result = network.step(.0002, 1, [True]*4)
        self.assertLessEqual(result['pump_flow_m3_s'], 6.5/60000)
        self.assertEqual(result['pump_electrical_power_upper_bound_w'], 15.6)
        self.assertEqual(result['isolation_valve_open'], [False]*4)
        self.assertTrue(all(v == 0 for v in result['pressure_pa']))
        for _ in range(40):
            result = network.step(.0002, 1, [True]*4)
        self.assertEqual(result['isolation_valve_open'], [True]*4)
        self.assertEqual(result['valve_electrical_power_w'], 4)
        self.assertEqual(result['electrical_power_w'], 19.6)
        self.assertEqual(len(set(result['pressure_pa'])), 1)

    def test_more_connected_volume_slows_single_pump_pressure_rise(self):
        c = hardware.load_hardware()
        c['pneumatics']['sealed_leak_conductance_each_m3_s_pa'] = 0
        one = hardware.SharedVacuumNetwork(c, [.02])
        four = hardware.SharedVacuumNetwork(c, [.02]*4)
        for _ in range(100):
            one_result = one.step(.0002, 1, [True])
            four_result = four.step(.0002, 1, [True]*4)
        self.assertLess(one_result['pressure_pa'][0], c['pneumatics']['operating_vacuum_limit_pa'])
        self.assertGreater(one_result['pressure_pa'][0], four_result['pressure_pa'][0])

    def test_loss_of_seal_affects_shared_pressure_before_delayed_isolation(self):
        c = hardware.load_hardware()
        network = hardware.SharedVacuumNetwork(c, [.02]*4)
        for _ in range(6000):
            good = network.step(.0002, 1, [True]*4)
        start = good['pressure_pa'][0]
        first = network.step(.0002, 1, [False, True, True, True])
        self.assertTrue(first['isolation_valve_open'][0])
        self.assertLess(first['pressure_pa'][1], start)
        self.assertGreater(first['requested_adhesion_n'][0], 0)
        for _ in range(30):
            result = network.step(.0002, 1, [False, True, True, True])
        self.assertFalse(result['isolation_valve_open'][0])
        self.assertTrue(result['vent_valve_open'][0])
        self.assertLess(result['pressure_pa'][0], result['pressure_pa'][1])

    def test_operating_cap_is_separate_from_pump_ultimate_and_custom_leak(self):
        c = hardware.load_hardware()
        network = hardware.SharedVacuumNetwork(c, [.02]*4)
        for _ in range(2000):
            result = network.step(.002, 1, [True]*4, leak_conductance=[0]*4)
        self.assertEqual(result['pressure_pa'], [8000.0]*4)
        self.assertTrue(result['relief_active'])
        self.assertGreater(result['regulator_duty'], 0)
        self.assertLess(result['regulator_duty'], .1)
        self.assertEqual(hardware.pump_flow_m3_s(c, c['pneumatics']['ambient_pressure_pa']-10000), 0)
        leakier = hardware.SharedVacuumNetwork(c, [.02]*4)
        for _ in range(2000):
            leaked = leakier.step(.002, 1, [True]*4, leak_conductance=[1e-7]*4)
        self.assertLess(max(leaked['pressure_pa']), 500)

    def test_explicit_gap_leak_is_not_replaced_before_actual_vent_opens(self):
        c = hardware.load_hardware()
        network = hardware.SharedVacuumNetwork(c, [.02]*4)
        network.pressure_pa[:] = [7000]*4
        result = network.step(.0002, 0, [False, True, True, True],
                              leak_conductance=[1e-12]*4)
        self.assertFalse(result['vent_valve_open'][0])
        self.assertGreater(result['pressure_pa'][0], 6999)
        self.assertGreater(result['requested_adhesion_n'][0], 139)
        for _ in range(20):
            result = network.step(.0002, 0, [False, True, True, True],
                                  leak_conductance=[1e-12]*4)
        self.assertTrue(result['vent_valve_open'][0])
        self.assertLess(result['pressure_pa'][0], 6500)

    def test_zero_leak_initial_flat_curve_still_builds_pressure(self):
        c = hardware.load_hardware()
        c['pneumatics']['manifold_leak_conductance_m3_s_pa'] = 0
        c['pneumatics']['sealed_leak_conductance_each_m3_s_pa'] = 0
        network = hardware.SharedVacuumNetwork(c, [.02]*4)
        result = network.step(.0002, 1, [True]*4)
        self.assertGreater(result['manifold_pressure_pa'], 0)

    def test_gas_volumes_and_hose_endpoints_follow_actual_seal_geometry(self):
        import fishbot_vacuum_seal as seal
        c = hardware.load_hardware()
        geometry = seal.chamber_geometry(seal.load_config())
        self.assertAlmostEqual(c['gas_geometry']['skirt']['cavity_volume_m3'], geometry['cavity_volume_m3'])
        self.assertGreater(geometry['cavity_volume_m3'], 13e-6)
        self.assertLess(geometry['cavity_volume_m3'], 15e-6)
        for i, volume in enumerate(c['pneumatics']['chamber_volumes_m3']):
            self.assertAlmostEqual(volume, geometry['cavity_volume_m3']+c['gas_geometry']['branch_hose_volumes_m3'][i])
            self.assertLess(volume, 25e-6)
            self.assertAlmostEqual(c['installation']['hose']['routes_m'][i][-1][2], -.0565)
        self.assertNotEqual(c['pneumatics']['chamber_volumes_m3'][0], c['pneumatics']['chamber_volumes_m3'][2])

    def test_standard_pump_and_ambient_leak_volume_flow_are_not_mixed(self):
        c = hardware.load_hardware()
        network = hardware.SharedVacuumNetwork(c, [.02]*4)
        result = network.step(.0002, 1, [True]*4)
        ratio = c['pneumatics']['ambient_temperature_k']/c['pneumatics']['reference_temperature_k']
        self.assertAlmostEqual(result['stp_to_ambient_volume_ratio'], ratio)
        self.assertAlmostEqual(result['pump_flow_ambient_m3_s'], result['pump_flow_m3_s']*ratio)


if __name__ == '__main__':
    unittest.main()
