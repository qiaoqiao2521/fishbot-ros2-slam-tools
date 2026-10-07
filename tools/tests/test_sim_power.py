"""Battery/contact boundaries; no ROS initialization, processes, or hardware."""
from dataclasses import replace
import copy
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fishbot_sim_power import (PowerConfig, PowerModel, Truth, configure_docking,
                               truth_from_message, validate_environment)


def scene():
    return {'dock': {'id': 'home_dock', 'frame': 'map',
                     'pose': {'x': 0., 'y': 0., 'yaw': math.pi},
                     'staging_pose': {'x': .55, 'y': 0., 'yaw': math.pi},
                     'truth_to_dock_frame': {'x': 0., 'y': 0., 'yaw': 0.},
                     'contact': {'half_length': .12, 'half_width': .12,
                                 'yaw_tolerance_rad': .12, 'max_linear_mps': .015,
                                 'max_angular_rps': .03, 'dwell_s': 1.0}}}


def model(**options):
    cfg = PowerConfig.from_scene(scene())
    result = PowerModel(replace(cfg, **options))
    result.snapshot(0., 0.)
    return result


def sample(stamp, **overrides):
    values = dict(stamp=stamp, received=stamp, x=0., y=0., yaw=math.pi,
                  vx=0., vy=0., wz=0.)
    values.update(overrides)
    return Truth(**values)


def feed(power, stamp, **overrides):
    truth = sample(stamp, **overrides)
    return power.ingest(truth, stamp, truth.received)


def at_dock(power, start=1., count=16):
    for i in range(count):
        feed(power, start+i*.1)


class PowerBoundaries(unittest.TestCase):
    def test_requires_exact_domain_loopback_and_no_peers(self):
        good = {'ROS_DOMAIN_ID': '98', 'FISHBOT_MUJOCO_DOMAIN_ID': '98',
                'ROS_LOCALHOST_ONLY': '1', 'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_STATIC_PEERS': ''}
        validate_environment(good)
        for key in good:
            for bad in ('0', '93', 'SUBNET', '192.0.2.1', ' '):
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    validate_environment({**good, key: bad})
        for key in ('ROS_DOMAIN_ID', 'FISHBOT_MUJOCO_DOMAIN_ID', 'ROS_LOCALHOST_ONLY', 'ROS_AUTOMATIC_DISCOVERY_RANGE'):
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_environment({k: v for k, v in good.items() if k != key})

    def test_contact_dwell_then_positive_current_and_soc_gain(self):
        power = model()
        feed(power, 1.)
        initial = power.soc
        self.assertTrue(power.contact)
        self.assertFalse(power.charging)
        for i in range(1, 10):
            feed(power, 1.+i*.1)
        self.assertFalse(power.charging)
        self.assertLess(power.soc, initial)
        before = power.soc
        feed(power, 2.)
        self.assertTrue(power.charging)
        feed(power, 2.1)
        self.assertGreater(power.soc, before)
        self.assertEqual(power.current_a, 2.)
        self.assertAlmostEqual(power.charged_soc_total, .008)
        self.assertTrue(power.snapshot(2.1, 2.1)['truth_fresh'])

    def test_location_yaw_height_and_all_speed_components_prevent_contact(self):
        for bad in ({'x': .121}, {'y': .121}, {'yaw': math.pi+.121},
                    {'vx': .016}, {'vy': .016}, {'wz': .031}, {'z': .041},
                    {'vz': .016}, {'wx': .031}, {'wy': .031}):
            power = model()
            at_dock(power)
            self.assertTrue(power.charging)
            prior = power.soc
            feed(power, 2.6, **bad)
            with self.subTest(bad=bad):
                self.assertFalse(power.contact)
                self.assertFalse(power.charging)
                self.assertLessEqual(power.current_a, 0.)
                self.assertLessEqual(power.soc, prior)
                feed(power, 2.7)
                self.assertFalse(power.charging)  # Dwell must restart after loss of contact.

    def test_rotated_contact_region_and_wrapped_yaw(self):
        power = model(half_length=.2, half_width=.05)
        self.assertTrue(power.contact_metrics(sample(1., x=.19, yaw=-math.pi))['contact'])
        self.assertFalse(power.contact_metrics(sample(1., y=.06))['contact'])
        power = model(dock_pose=(0., 0., math.pi/2))
        self.assertTrue(power.contact_metrics(sample(1., y=.11, yaw=math.pi/2))['contact'])

    def test_no_charge_from_single_sample_or_repeated_publication(self):
        power = model()
        feed(power, 1.)
        initial = power.soc
        for _ in range(100):
            power.snapshot(1., 1.)
        self.assertEqual(power.soc, initial)
        self.assertFalse(power.charging)
        self.assertFalse(power.snapshot(1., 3.)['charging'])
        self.assertEqual(power.soc, initial)

    def test_truth_expiry_clears_charge_and_resume_never_backfills_gap(self):
        power = model()
        at_dock(power)
        before = power.soc
        state = power.snapshot(3.2, 3.2)
        self.assertFalse(state['charging'])
        self.assertFalse(state['truth_fresh'])
        self.assertEqual(state['current_a'], 0.)
        self.assertEqual(power.soc, before)
        feed(power, 10.)
        self.assertFalse(power.charging)
        self.assertEqual(power.soc, before)

    def test_paused_and_regressed_clock_cannot_charge(self):
        power = model()
        at_dock(power)
        before = power.soc
        self.assertFalse(power.snapshot(2.5, 3.1)['clock_fresh'])
        self.assertFalse(power.charging)
        self.assertEqual(power.soc, before)
        self.assertFalse(power.ingest(sample(1., received=3.2), 1., 3.2))
        # Simulation clock reset requires a new model; high stamps do not hide it.
        self.assertFalse(power.ingest(sample(4., received=3.3), 4., 3.3))
        self.assertFalse(power.snapshot(4., 3.3)['charging'])

    def test_duplicate_regressed_future_and_nonfinite_truth_revoke_charging(self):
        invalid = [sample(2.5, received=2.6), sample(2.4, received=2.6),
                   sample(20., received=2.6), sample(2.6, x=float('nan'))]
        for truth in invalid:
            power = model()
            at_dock(power)
            initial = power.soc
            with self.subTest(truth=truth):
                self.assertFalse(power.ingest(truth, 2.6, 2.6))
                self.assertFalse(power.charging)
                self.assertEqual(power.current_a, 0.)
                self.assertEqual(power.soc, initial)

    def test_source_and_receive_gaps_restart_dwell_without_soc_jump(self):
        for truth in (sample(3., received=2.6), sample(2.6, received=4.)):
            power = model()
            at_dock(power)
            initial = power.soc
            power.ingest(truth, truth.stamp, truth.received)
            with self.subTest(truth=truth):
                self.assertFalse(power.charging)
                self.assertEqual(power.soc, initial)

    def test_motion_and_sim_time_drive_discharge_low_soc_without_task_events(self):
        slow, fast = model(initial_soc=.281), model(initial_soc=.281)
        feed(slow, 1., x=1.)
        feed(fast, 1., x=1., vx=.2)
        for i in range(1, 6):
            feed(slow, 1.+i*.1, x=1.)
            feed(fast, 1.+i*.1, x=1., vx=.2)
        self.assertLess(fast.soc, slow.soc)
        self.assertTrue(fast.snapshot(1.5, 1.5)['low_battery'])
        self.assertFalse(slow.snapshot(1.5, 1.5)['low_battery'])
        self.assertAlmostEqual(fast.discharged_soc_total, .7*.5*45/(3600*2))
        self.assertAlmostEqual(fast.distance_m, .1)

    def test_fault_injection_never_charges_despite_valid_contact(self):
        power = model()
        power.charging_enabled = False
        before = power.soc
        at_dock(power, count=30)
        self.assertTrue(power.contact)
        self.assertFalse(power.charging)
        self.assertLess(power.soc, before)
        self.assertEqual(power.charged_soc_total, 0.)
        self.assertLessEqual(power.current_a, 0.)
        self.assertEqual(power.reason, 'charging_disabled')

    def test_soc_clamps_and_status_is_json_serializable(self):
        power = model(initial_soc=.999)
        at_dock(power, count=30)
        self.assertEqual(power.soc, 1.)
        json.dumps(power.snapshot(3.9, 3.9), allow_nan=False)
        power = model(initial_soc=0.)
        feed(power, 1., x=1.)
        feed(power, 1.1, x=1.)
        self.assertEqual(power.soc, 0.)

    def test_relative_beacon_uses_truth_transform_not_map_localization(self):
        power = model(truth_to_dock_frame=(1., 2., math.pi/2))
        feed(power, 1., yaw=0.)
        x, y, yaw = power.relative_beacon()
        self.assertAlmostEqual(x, -2.)
        self.assertAlmostEqual(y, 1.)
        self.assertAlmostEqual(yaw, math.pi/2)

    def test_config_requires_explicit_transform_and_consistent_staging(self):
        mutations = [lambda d: d.pop('truth_to_dock_frame'),
                     lambda d: d['staging_pose'].update(y=.1),
                     lambda d: d['staging_pose'].update(x=-.55),
                     lambda d: d['staging_pose'].update(yaw=0.),
                     lambda d: d.update(charge_model={'initial_soc': float('nan')}),
                     lambda d: d.update(charge_model={'charge_time_scal': 100}),
                     lambda d: d.update(charge_model={'low_soc': .9, 'resume_soc': .8}),
                     lambda d: d.update(charge_model={'charging_current_a': .5}),
                     lambda d: d.update(charge_model={'max_sample_gap_s': .5, 'truth_timeout_s': .1})]
        for mutation in mutations:
            data = scene()
            mutation(data['dock'])
            with self.subTest(data=data), self.assertRaises((KeyError, ValueError)):
                PowerConfig.from_scene(data)

    def test_docking_uses_battery_and_relative_detection_without_default_offsets(self):
        params = {'controller_server': {'ros__parameters': {'keep': 42}}}
        before = copy.deepcopy(params['controller_server'])
        self.assertIs(configure_docking(params, scene()), params)
        self.assertEqual(params['controller_server'], before)
        docking = params['docking_server']['ros__parameters']
        plugin = docking['home_charging_dock']
        self.assertTrue(plugin['use_battery_status'])
        self.assertEqual(docking['home_dock']['type'], 'home_charging_dock')
        self.assertEqual(docking['fixed_frame'], 'odom')
        self.assertEqual(docking['base_frame'], 'base_footprint')
        self.assertEqual(plugin['staging_x_offset'], -.55)
        for key in ('translation_x', 'translation_y', 'rotation_roll', 'rotation_pitch', 'rotation_yaw'):
            self.assertEqual(plugin['external_detection_'+key], 0.)
        self.assertLess(plugin['docking_threshold'], .12)

    def test_message_rejects_wrong_joint_quaternion_and_toppled_robot(self):
        body = NS(name='base_footprint', pose=NS(pose=NS(position=NS(x=0., y=0., z=.002),
                  orientation=NS(x=0., y=0., z=1., w=0.))),
                  twist=NS(twist=NS(linear=NS(x=0., y=0., z=0.), angular=NS(x=0., y=0., z=0.))))
        message = NS(header=NS(stamp=NS(sec=1, nanosec=100)), free_joints=[body])
        truth = truth_from_message(message, 10.)
        self.assertAlmostEqual(truth.stamp, 1.0000001)
        self.assertEqual(truth.z, .002)
        for bad in ('joint', 'quaternion', 'toppled'):
            altered = copy.deepcopy(message)
            if bad == 'joint':
                altered.free_joints[0].name = 'some_other_body'
            elif bad == 'quaternion':
                altered.free_joints[0].pose.pose.orientation.w = 1.
            else:
                altered.free_joints[0].pose.pose.orientation = NS(x=1., y=0., z=0., w=0.)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                truth_from_message(altered, 10.)


if __name__ == '__main__':
    unittest.main()
