"""Geometry, open-seam leakage and actual native world-surface ray contracts."""
import importlib.util
import math
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

SOURCE = Path(__file__).resolve().parents[1] / 'fishbot_vacuum_seal.py'
spec = importlib.util.spec_from_file_location('fishbot_vacuum_seal', SOURCE)
seal = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = seal
spec.loader.exec_module(seal)
HAS_MUJOCO = importlib.util.find_spec('mujoco') is not None


class LeakContract(unittest.TestCase):
    def setUp(self):
        self.c = seal.load_config()

    def test_area_comes_from_inner_geometry_and_cannot_inherit_old_tire_area(self):
        self.assertAlmostEqual(seal.effective_area(self.c), math.pi * .035 ** 2)
        force = seal.evaluate_leak(self.c, [0.] * 64, 8000.)['pressure_force_n']
        self.assertLess(force, 31.)
        self.assertLess(4 * force * .8, 18.431 * 9.81)

    def test_gap_sweep_loses_pressure_capacity_continuously(self):
        gaps = [0., 1e-6, 5e-6, 25e-6, 100e-6, 1e-3, 2e-3]
        flows = [seal.evaluate_leak(self.c, [h] * 64, 4000.)['leak_flow_m3_s'] for h in gaps]
        self.assertTrue(all(a < b for a, b in zip(flows, flows[1:])))
        # Old 2mm contact margin cannot be mistaken for a sealed chamber.
        self.assertGreater(flows[-1], .0008)
        epsilon = [seal.evaluate_leak(self.c, [h] * 64, 4000.)['leak_flow_m3_s']
                   for h in (.001999999, .002, .002000001)]
        self.assertLess((max(epsilon) - min(epsilon)) / epsilon[1], 1e-4)

    def test_small_gap_has_cubic_limit_and_coarse_open_gap_is_inertially_bounded(self):
        c = dict(self.c, roughness_equivalent_gap_m=1e-9)
        q1 = seal.evaluate_leak(c, [1e-6] * 64, 100.)['leak_flow_m3_s']
        q2 = seal.evaluate_leak(c, [2e-6] * 64, 100.)['leak_flow_m3_s']
        self.assertAlmostEqual(q2 / q1, 8, delta=.02)
        opened = seal.evaluate_leak(c, [.002] * 64, 4000.)
        orifice = c['discharge_coefficient'] * opened['perimeter_m'] * (.002 + 1e-9) * math.sqrt(8000 / c['air_density_kg_m3'])
        self.assertLessEqual(opened['leak_flow_m3_s'], orifice)

    def test_one_local_open_seam_dominates_a_mostly_near_surface_ring(self):
        near = seal.evaluate_leak(self.c, [0.] * 64, 4000.)
        seam = seal.evaluate_leak(self.c, [.001] + [0.] * 63, 4000.)
        self.assertGreater(seam['leak_flow_m3_s'], 100 * near['leak_flow_m3_s'])
        self.assertEqual(seam['effective_area_m2'], near['effective_area_m2'])

    def test_zero_pressure_flow_is_zero_but_conductance_is_finite(self):
        result = seal.evaluate_leak(self.c, [.0001] * 64, 0.)
        self.assertEqual(result['leak_flow_m3_s'], 0.)
        self.assertTrue(math.isfinite(result['leak_conductance_m3_s_pa']))
        self.assertGreater(result['leak_conductance_m3_s_pa'], 0.)
        self.assertLessEqual(result['lip_flow_path_m'], 2 * self.c['lip_minor_radius_m'])

    def test_passive_closed_valve_pressure_decays_and_seam_accelerates_loss(self):
        # Isothermal constant-volume passive leak: no instant contact switch.
        def decay(gap):
            p = 4000.
            for _ in range(1000):
                conductance = seal.evaluate_leak(self.c, [gap] * 64, p)['leak_conductance_m3_s_pa']
                p *= math.exp(-101325 / .00025 * conductance * .0001)
            return p
        smooth, open_seam = decay(0.), decay(.001)
        self.assertGreater(smooth, 0.)
        self.assertLess(smooth, 4000.)
        self.assertLess(open_seam, smooth / 100)

    def test_xml_has_four_mass_bearing_closed_lips_without_tire_adhesion(self):
        doc = ET.fromstring('<mujoco><worldbody>' + seal.pad_bodies_xml(self.c)
                            + '</worldbody><actuator>' + seal.adhesion_actuators_xml(self.c) + '</actuator></mujoco>')
        self.assertEqual(len(doc.findall('.//body')), 4)
        self.assertEqual(len(doc.findall('.//geom[@type="capsule"]')), 64)
        self.assertAlmostEqual(sum(float(i.attrib['mass']) for i in doc.findall('.//inertial')), .12)
        self.assertTrue(all('vacuum_pad' in a.attrib['body'] for a in doc.findall('.//adhesion')))
        self.assertTrue(all(g.get('contype') == '1' and g.get('conaffinity') == '1'
                            for g in doc.findall('.//geom[@type="cylinder"]')))
        self.assertIsNone(doc.find('.//equality'))

    def test_chamber_volume_uses_actual_lip_void_and_port_is_at_plate_top(self):
        geometry = seal.chamber_geometry(self.c)
        self.assertAlmostEqual(geometry['cavity_depth_m'], .003)
        self.assertGreater(geometry['cavity_volume_m3'], seal.effective_area(self.c) * .003)
        self.assertLess(geometry['cavity_volume_m3'], math.pi * .04 ** 2 * .003)
        self.assertEqual(geometry['backplate_port_local_m'], [0., 0., .005])

    def test_rim_samples_lie_on_actual_capsule_chords_and_use_polygon_perimeter(self):
        points, width = seal._rim_points(self.c)
        self.assertEqual(len(points), 64)
        # Four midpoint samples on each edge are inside the smooth circle.
        self.assertTrue(all(math.hypot(p[0], p[1]) < .04 for p in points))
        self.assertAlmostEqual(width * len(points), 16 * 2 * .04 * math.sin(math.pi / 16))
        # The first four points must lie on the same actual first lip axis.
        a, b = (0.04, 0.), (.04 * math.cos(math.pi / 8), .04 * math.sin(math.pi / 8))
        for x, y, _ in points[:4]:
            self.assertAlmostEqual((b[0]-a[0])*(y-a[1]) - (b[1]-a[1])*(x-a[0]), 0.)


@unittest.skipUnless(HAS_MUJOCO, 'native MuJoCo available in suction-python environment')
class NativeGapContract(unittest.TestCase):
    def setUp(self):
        import mujoco
        self.mj = mujoco
        self.c = seal.load_config()

    def sample(self, *, z=.002, euler='0 0 0', surface='plane'):
        c = dict(self.c, module_centers_m=[[0, 0, z]])
        floor = ('<geom name="floor" type="plane" size="1 1 .1" group="1"/>'
                 if surface == 'plane' else
                 '<geom name="edge" type="box" pos="-.05 0 -.01" size=".05 .2 .01" group="1"/>')
        model = self.mj.MjModel.from_xml_string(
            '<mujoco><compiler angle="degree"/><worldbody>' + floor
            + f'<body name="holder" euler="{euler}">' + seal.pad_bodies_xml(c)
            + '</body></worldbody></mujoco>')
        data = self.mj.MjData(model)
        self.mj.mj_forward(model, data)
        return seal.sample_gaps(model, data, model.body('vacuum_pad0').id, c)

    def test_actual_flat_ring_has_zero_macro_gap_and_correct_upward_world_normal(self):
        sample = self.sample()
        self.assertEqual(sample['status'], 'sampled')
        self.assertLess(max(sample['gaps_m']), 1e-9)
        self.assertEqual(sample['missing_samples'], 0)
        self.assertEqual(sample['surface_normals'][0], [0., 0., 1.])

    def test_native_normal_gap_is_measured_not_obtained_from_contact_count(self):
        sample = self.sample(z=.003)
        self.assertTrue(all(abs(h - .001) < 1e-9 for h in sample['gaps_m']))
        near = seal.evaluate_leak(self.c, self.sample(), 4000.)
        raised = seal.evaluate_leak(self.c, sample, 4000.)
        self.assertGreater(raised['leak_flow_m3_s'], 1000 * near['leak_flow_m3_s'])

    def test_native_tilt_opens_one_side_and_reports_finite_compression_limit(self):
        tilted = self.sample(euler='0 5 0')
        self.assertGreater(max(tilted['gaps_m']), .003)
        self.assertGreater(tilted['maximum_compression_m'], .001)
        self.assertNotEqual(tilted['status'], 'sampled')
        self.assertGreater(seal.evaluate_leak(self.c, tilted, 4000.)['leak_flow_m3_s'],
                           seal.evaluate_leak(self.c, self.sample(), 4000.)['leak_flow_m3_s'])

    def test_native_edge_missing_surface_cannot_fake_a_closed_ring(self):
        sample = self.sample(surface='edge')
        self.assertEqual(sample['status'], 'open_surface')
        self.assertGreater(sample['missing_samples'], 20)
        self.assertGreater(seal.evaluate_leak(self.c, sample, 4000.)['leak_flow_m3_s'], .0008)

    def test_native_floor_wall_corner_has_mixed_normals_and_open_perimeter(self):
        c = dict(self.c, module_centers_m=[[0, 0, 0]])
        model = self.mj.MjModel.from_xml_string(
            '<mujoco><compiler angle="degree"/><worldbody>'
            '<geom name="floor" type="plane" size="1 1 .1" group="1"/>'
            '<geom name="wall" type="box" pos=".1 0 1" size=".1 1 1" group="1"/>'
            '<body name="holder" pos="-.028 0 .028" euler="0 -45 0">'
            + seal.pad_bodies_xml(c) + '</body></worldbody></mujoco>')
        data = self.mj.MjData(model)
        self.mj.mj_forward(model, data)
        sampled = seal.sample_gaps(model, data, model.body('vacuum_pad0').id, c)
        self.assertEqual(sampled['status'], 'mixed_surface_normals')
        self.assertAlmostEqual(sampled['normal_spread_rad'], math.pi / 2)
        self.assertGreater(max(sampled['gaps_m']), .02)
        self.assertGreater(seal.evaluate_leak(c, sampled, 4000.)['leak_flow_m3_s'], .0008)

    def test_native_lip_contact_keeps_declared_friction_and_softness_against_world(self):
        c = dict(self.c, module_centers_m=[[0, 0, 0]])
        model = self.mj.MjModel.from_xml_string(
            '<mujoco><worldbody><geom name="floor" type="plane" size="1 1 .1" '
            'group="1" friction=".8 .005 .0001" solref=".005 1"/>'
            '<body name="holder" pos="0 0 .0019"><freejoint/>'
            + seal.pad_bodies_xml(c) + '</body></worldbody></mujoco>')
        data = self.mj.MjData(model)
        self.mj.mj_forward(model, data)
        contacts = [contact for contact in data.contact
                    if any('_lip' in model.geom(int(g)).name
                           for g in (contact.geom1, contact.geom2))]
        self.assertGreater(len(contacts), 0)
        for contact in contacts:
            self.assertAlmostEqual(contact.friction[0], c['lip_friction'])
            self.assertAlmostEqual(contact.friction[1], c['lip_friction'])
            self.assertAlmostEqual(contact.solref[0], c['lip_contact_time_constant_s'])
            self.assertAlmostEqual(contact.solref[1], c['lip_contact_damping_ratio'])


if __name__ == '__main__':
    unittest.main()
