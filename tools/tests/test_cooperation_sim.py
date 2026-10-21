"""Control boundaries and independent sensor evidence for the shared world."""
import importlib.util
import ast
import contextlib
import copy
import hashlib
import io
import json
import math
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sim = load('cooperation_sim', TOOLS/'cooperation_sim.py')


class StationObservationProducerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.scene = Path(self.folder.name)/'world.xml'
        self.scene.write_text('<mujoco/>')
        self.identity = {
            'scene_sha256': hashlib.sha256(self.scene.read_bytes()).hexdigest(),
            'manifest_sha256': 'a'*64, 'episode_id': str(uuid.uuid4()),
            'manifest': {'world_xml': str(self.scene), 'dock_pose': [-1.8,-1.84,0.],
                         'native_dock_pose': [-1.8,-1.84,math.pi]}}

    def beacon(self, config=None):
        identity = copy.deepcopy(self.identity)
        if config is not None:
            identity['manifest']['station_perception'] = config
        return sim.StationBeacon(identity, self.scene)

    def perturbed(self, **values):
        return {'mode': 'perturbed', 'max_covariance': [.01]*3,
                'seed': 73, 'noise_std': [.02,.03,.04],
                'bias': [.04,-.03,.02], **values}

    def test_default_observation_keeps_original_geometry_and_covariance(self):
        beacon = self.beacon()
        observation = beacon.sample((-1.1,-1.84,math.pi/2), .1)
        self.assertTrue(observation['detected'])
        for actual, expected in zip(observation['relative'], (0.,.7,math.pi/2)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual([observation['covariance'][i] for i in (0,7,35)], [.0001]*3)
        self.assertEqual(observation['episode_id'], self.identity['episode_id'])
        self.assertEqual(observation['sequence'], 1)
        self.assertEqual(observation['mode'], 'ideal')
        self.assertEqual(observation['publisher'], 'cooperation_physics')
        self.assertEqual(beacon.status()['publish_hz_source_time'], 50)

    def test_duplicate_sample_and_status_reads_never_advance_randomness(self):
        beacon = self.beacon(self.perturbed())
        observed = beacon.sample((-1.1,-1.84,0.), .1)
        rng_state = beacon.rng.getstate()
        for _ in range(5):
            self.assertEqual(beacon.sample((-1.1,-1.84,0.), .1), observed)
            beacon.status()
        self.assertEqual(beacon.rng.getstate(), rng_state)
        self.assertEqual(beacon.sequence, 1)
        with self.assertRaises(ValueError):
            beacon.sample((-1.1,-1.84,0.), .099)
        observed['relative'][0] = 100.
        self.assertNotEqual(beacon.status()['observation']['relative'][0], 100.)

    def test_perturbation_seed_is_repeatable_and_variance_reports_declared_noise(self):
        left, right = self.beacon(self.perturbed()), self.beacon(self.perturbed())
        samples = [left.sample((-1.1,-1.84,0.), i*.1) for i in range(1,4)]
        other = [right.sample((-1.1,-1.84,0.), i*.1) for i in range(1,4)]
        self.assertEqual(samples, other)
        self.assertNotEqual(samples[0]['relative'], samples[1]['relative'])
        for index, expected in zip((0,7,35), (.0005,.001,.0017)):
            self.assertAlmostEqual(samples[0]['covariance'][index], expected)
        epoch = str(uuid.uuid4())
        left.begin_episode(epoch, 10.)
        self.assertIsNone(left.status()['observation'])
        self.assertEqual(left.sequence, 0)
        repeated = left.sample((-1.1,-1.84,0.), 10.1)
        self.assertEqual(repeated['relative'], samples[0]['relative'])
        self.assertEqual(repeated['sequence'], 1)
        self.assertEqual(repeated['episode_id'], epoch)
        self.assertAlmostEqual(repeated['episode_elapsed_s'], .1)
        self.assertTrue(left.status()['seed_reset_per_episode'])

    def test_occlusion_and_dropout_do_not_retimestamp_the_last_detected_pose(self):
        beacon = self.beacon(self.perturbed(occlusion_windows=[[.2,.4]], dropout_probability=0.))
        self.assertTrue(beacon.sample((-1.1,-1.84,0.), .1)['detected'])
        for sequence, stamp in ((2,.2), (3,.399)):
            missing = beacon.sample((-1.1,-1.84,0.), stamp)
            self.assertFalse(missing['detected'])
            self.assertEqual(missing['reason'], 'occluded')
            self.assertIsNone(missing['relative'])
            self.assertIsNone(missing['covariance'])
            self.assertEqual(missing['stamp'], stamp)
            self.assertEqual(missing['sequence'], sequence)
        self.assertTrue(beacon.sample((-1.1,-1.84,0.), .4)['detected'])
        dropout = self.beacon(self.perturbed(dropout_probability=1.))
        self.assertEqual(dropout.sample((-1.1,-1.84,0.), .1)['reason'], 'dropout')
        self.assertEqual(dropout.sample((-4.,-1.84,0.), .2)['reason'], 'out_of_range')

    def test_vision_never_calls_truth_geometry_or_samples_randomness(self):
        beacon = self.beacon({'mode': 'vision', 'publisher': 'station_camera',
                             'min_confidence': .8, 'max_covariance': [.01]*3})
        def forbidden(*args):
            self.fail('vision called the truth-derived measurement')
        beacon.measure = forbidden
        rng_state = beacon.rng.getstate()
        self.assertIsNone(beacon.sample((-1.1,-1.84,0.), .1))
        self.assertIsNone(beacon.sample((-1.1,-1.84,0.), .2))
        self.assertEqual(beacon.rng.getstate(), rng_state)
        self.assertEqual(beacon.sequence, 0)
        self.assertIsNone(beacon.status()['observation'])
        self.assertEqual(beacon.status()['reason'], 'awaiting_external_producer')
        self.assertFalse(beacon.status()['idealized_truth_derived'])

    def test_perception_cannot_rename_the_compiled_station(self):
        with self.assertRaisesRegex(ValueError, 'identity does not match'):
            self.beacon({'station_id': 'other_station'})

    def test_standard_messages_have_exact_pairing_and_misses_have_diagnostics_only(self):
        from cooperation_perception import messages_to_observation
        beacon = self.beacon()
        observation = beacon.sample((-1.1,-1.84,0.), .123456789)
        pose, diagnostic = sim.station_messages(observation)
        self.assertEqual(pose.header, diagnostic.header)
        self.assertEqual(pose.header.stamp.nanosec, 123456789)
        parsed = messages_to_observation(pose, diagnostic)
        self.assertEqual(parsed['sequence'], 1)
        self.assertEqual(parsed['relative'], tuple(observation['relative']))
        self.assertTrue(parsed['detected'])
        missing = beacon.sample((-4.,-1.84,0.), .2)
        pose, diagnostic = sim.station_messages(missing)
        self.assertIsNone(pose)
        self.assertEqual(diagnostic.status[0].level, b'\x01')
        parsed = messages_to_observation(None, diagnostic)
        self.assertFalse(parsed['detected'])
        self.assertEqual(parsed['reason'], 'out_of_range')
        self.assertEqual(parsed['stamp'], .2)


class ReferencesTest(unittest.TestCase):
    def test_reset_mailbox_is_bounded_fresh_and_idempotent(self):
        mailbox = sim.ResetRequests()
        request = {'request_id': str(uuid.uuid4()), 'episode_id': str(uuid.uuid4()), 'issued_at': 10.}
        self.assertIsNone(mailbox.offer(request, now=10.))
        self.assertIsNone(mailbox.offer(request, now=10.1))
        self.assertEqual(len(mailbox.pending), 1)
        taken = mailbox.take()
        result = sim.reset_result(taken, episode_id=str(uuid.uuid4()), reset_stamp=25., message='new episode')
        mailbox.finish(taken, result)
        reply = mailbox.offer(request, now=100.)
        self.assertEqual(reply, result)  # Replay a receipt, never a second reset.
        reply['status'] = 'changed'
        self.assertEqual(mailbox.offer(request, now=100.), result)
        self.assertIsNone(mailbox.take())
        for stamp in (4.99, 10.01):
            stale = dict(request, request_id=str(uuid.uuid4()), issued_at=stamp)
            self.assertEqual(mailbox.offer(stale, now=10.)['status'], 'failed')
        for index in range(4):
            self.assertIsNone(mailbox.offer(dict(request, request_id=str(uuid.uuid4())), now=10.))
        overflow = mailbox.offer(dict(request, request_id=str(uuid.uuid4())), now=10.)
        self.assertEqual(overflow['status'], 'failed')
        self.assertEqual(len(mailbox.pending), 4)
        for index in range(100):
            item = dict(request, request_id=str(uuid.uuid4()))
            mailbox.finish(item, sim.reset_result(item, message='negative'))
        self.assertEqual(len(mailbox.results), 64)

    def test_reset_protocol_rejects_malformed_requests_without_queueing(self):
        mailbox = sim.ResetRequests()
        valid = {'request_id': str(uuid.uuid4()), 'episode_id': str(uuid.uuid4()), 'issued_at': 10.}
        for payload in (None, {}, dict(valid, extra=True), dict(valid, request_id='bad'),
                        dict(valid, episode_id=4), dict(valid, issued_at=True),
                        dict(valid, issued_at=math.nan)):
            with self.assertRaises(ValueError):
                mailbox.offer(payload, now=10.)
        self.assertEqual(len(mailbox.pending), 0)
        self.assertEqual(len(mailbox.results), 0)
        self.assertEqual(set(sim.reset_result(valid, message='denied')),
                         {'request_id','episode_id','status','new_episode_id','reset_stamp','message'})

    def test_new_episode_rejects_pre_boundary_wheel_commands(self):
        wheels = sim.WheelCommands()
        wheels.set_hold(False)
        wheels.accept(.2, 0., 1., source_stamp=10., sim_now=10.)
        wheels.begin_episode(10.)
        self.assertTrue(wheels.hold)
        wheels.set_hold(False)
        for stamp in (None, 9.99, 10.):
            with self.assertRaises(ValueError):
                wheels.accept(.2, 0., 2., source_stamp=stamp, sim_now=10.01)
            self.assertEqual(wheels.velocities(2.), (0., 0.))
        wheels.accept(.1, 0., 2., source_stamp=10.01, sim_now=10.01)
        self.assertNotEqual(wheels.velocities(2.1), (0., 0.))

    def test_arm_reference_requires_one_named_coordinator(self):
        publisher = SimpleNamespace(node_name='fishbot_so101_cooperation')
        sim.unique_arm_publisher([publisher], 'fishbot_so101_cooperation')
        for publishers in ([], [publisher, publisher], [SimpleNamespace(node_name='other')]):
            with self.assertRaises(ValueError):
                sim.unique_arm_publisher(publishers, 'fishbot_so101_cooperation')

    def test_default_hold_watchdog_and_release_require_fresh_motion(self):
        wheels = sim.WheelCommands()
        wheels.accept(.1, 0, 10.)
        self.assertEqual(wheels.velocities(10.1), (0., 0.))
        wheels.set_hold(False)
        self.assertEqual(wheels.velocities(10.1), (0., 0.))
        wheels.accept(.1, 0, 10.2)
        self.assertAlmostEqual(wheels.velocities(10.7)[0], .1/.032)
        self.assertEqual(wheels.velocities(10.701), (0., 0.))
        self.assertEqual(wheels.velocities(10.0), (0., 0.))
        wheels.set_hold(True)
        wheels.set_hold(False)
        self.assertEqual(wheels.velocities(10.3), (0., 0.))

    def test_command_limits_and_source_clock_validation(self):
        wheels = sim.WheelCommands()
        wheels.set_hold(False)
        wheels.accept(100, -100, 1.)
        self.assertEqual((wheels.linear, wheels.angular), (.25, -1.5))
        for stamp in (0., 9.49, 10.101, math.nan):
            with self.assertRaises(ValueError):
                wheels.accept(.1, 0., 1., source_stamp=stamp, sim_now=10.)
        wheels.accept(.1, .2, 2., source_stamp=9.9, sim_now=10.)
        self.assertNotEqual(wheels.velocities(2.1), (0., 0.))
        for value in (math.nan, math.inf):
            with self.assertRaises(ValueError):
                wheels.accept(value, 0., 2.)

    def test_arm_input_is_atomic_finite_and_model_bounded(self):
        limits = [(-1., 1.)]*6
        names = list(reversed(sim.ARM_JOINTS))
        self.assertEqual(sim.arm_reference(names, [.1,.2,.3,.4,.5,.6], limits),
                         (.6,.5,.4,.3,.2,.1))
        for bad_names, bad_values in [(names[:5], [0.]*5), (['gripper']*6, [0.]*6),
                                     (names, [0.]*5), (names, [0.]*5+[math.nan]),
                                     (names, [0.]*5+[1.01])]:
            with self.assertRaises(ValueError):
                sim.arm_reference(bad_names, bad_values, limits)

    def test_beacon_reuses_relative_geometry_and_rejects_stale_source_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder)/'world.xml'
            scene.write_text('<mujoco/>')
            identity = {'scene_sha256': hashlib.sha256(scene.read_bytes()).hexdigest(),
                        'manifest_sha256': 'fixture-manifest-sha',
                        'manifest': {'world_xml': str(scene), 'dock_pose': [-1.8,-1.84,0.],
                                     'native_dock_pose': [-1.8,-1.84,math.pi]}}
            beacon = sim.StationBeacon(identity, scene)
            self.assertIs(sim.StationBeacon.relative_beacon, sim.PowerModel.relative_beacon)
            self.assertEqual(beacon.measure((-2.8,-1.84,0.),0.), None)
            self.assertIsNone(beacon.measure((-2.801,-1.84,0.),1.))
            self.assertIsNotNone(beacon.measure((-2.8,-1.84,0.),1.))
            x,y,yaw = beacon.measure((-1.1,-1.84,math.pi/2),2.)
            self.assertAlmostEqual(x,0.)
            self.assertAlmostEqual(y,.7)
            self.assertAlmostEqual(yaw,math.pi/2)
            self.assertEqual(beacon.truth.stamp,2.)
            self.assertEqual(beacon.description['physical_robot_dock_pose'],[-1.8,-1.84,0.])
            self.assertEqual(beacon.description['world_dock'],[-1.8,-1.84,math.pi])
            self.assertTrue(beacon.description['idealized_truth_derived'])
            self.assertFalse(beacon.description['hardware_validated'])
            for pose in ((math.nan,0.,0.),(0.,math.inf,0.)):
                with self.assertRaises(ValueError):beacon.measure(pose,1.)
            for bad_manifest in ({'world_xml': str(scene.with_name('other.xml'))},
                                 {'dock_pose': [math.nan,0.,0.]},
                                 {'native_dock_pose': [-1.7,-1.84,math.pi]}):
                bad=copy.deepcopy(identity);bad['manifest'].update(bad_manifest)
                with self.assertRaises(ValueError):sim.StationBeacon(bad,scene)
            scene.write_text('<mujoco model="changed"/>')
            with self.assertRaises(ValueError):sim.StationBeacon(identity,scene)

    def test_encoder_pose_uses_wheel_displacement_only(self):
        odom = sim.EncoderOdometry(7., 8.)
        linear, angular = odom.update(8., 9., .1)
        self.assertAlmostEqual(odom.x, .032)
        self.assertEqual(odom.y, 0.)
        self.assertAlmostEqual(linear, .32)
        self.assertEqual(angular, 0.)
        odom.update(7., 10., .1)
        self.assertAlmostEqual(odom.yaw, .32)
        self.assertAlmostEqual(odom.x, .032)
        self.assertEqual(odom.y, 0.)

    def test_profile_wheel_geometry_changes_real_commands_and_encoder_scale(self):
        commands = sim.WheelCommands(radius=.098, separation=.37559)
        commands.set_hold(False)
        commands.accept(.12, .2, 1.)
        left, right = commands.velocities(1.)
        self.assertAlmostEqual(left, (.12-.2*.37559/2)/.098)
        self.assertAlmostEqual(right, (.12+.2*.37559/2)/.098)
        odom = sim.EncoderOdometry(radius=.098, separation=.37559)
        linear, angular = odom.update(left, right, 1.)
        self.assertAlmostEqual(linear, .12)
        self.assertAlmostEqual(angular, .2)
        self.assertEqual(commands.velocities(1.6), (0., 0.))

    def test_four_wheel_encoder_sides_use_both_independent_joint_readings(self):
        physics = sim.Physics.__new__(sim.Physics)
        physics.data = SimpleNamespace(qpos=[1., 3., 5., 9.])
        physics.left_wheel_q, physics.right_wheel_q = [0, 1], [2, 3]
        self.assertEqual(physics.wheel_encoder_positions(), (2., 7.))

    def test_encoder_transforms_axle_rotation_and_translation_to_foot(self):
        corrected = sim.EncoderOdometry(axle_offset=(-.02, 0.))
        old_point = sim.EncoderOdometry()
        turn_wheel = .20*(math.pi/2)/(2*.032)
        vx, omega = corrected.update(-turn_wheel, turn_wheel, 2.)
        old_point.update(-turn_wheel, turn_wheel, 2.)
        self.assertAlmostEqual(corrected.x, -.02)
        self.assertAlmostEqual(corrected.y, .02)
        self.assertEqual((old_point.x, old_point.y), (0., 0.))
        self.assertAlmostEqual(vx, 0.)
        self.assertAlmostEqual(omega, math.pi/4)
        self.assertAlmostEqual(corrected.lateral_velocity, .02*math.pi/4)
        mixed = sim.EncoderOdometry(axle_offset=(-.02, 0.))
        one_metre = 1/.032
        mixed.update(one_metre, one_metre, 1.)
        mixed.update(one_metre-turn_wheel, one_metre+turn_wheel, 2.)
        mixed.update(one_metre-turn_wheel+.5/.032, one_metre+turn_wheel+.5/.032, 1.)
        self.assertAlmostEqual(mixed.x, .98)
        self.assertAlmostEqual(mixed.y, .52)
        self.assertAlmostEqual(mixed.yaw, math.pi/2)
        self.assertAlmostEqual(mixed.lateral_velocity, 0.)
        lateral = sim.EncoderOdometry(axle_offset=(-.02,.01))
        vx, omega = lateral.update(-turn_wheel, turn_wheel, 2.)
        self.assertAlmostEqual(lateral.x, -.01)
        self.assertAlmostEqual(lateral.y, .03)
        self.assertAlmostEqual(vx, .01*omega)
        for bad in ((0.,),(math.nan,0.),(0.,math.inf)):
            with self.assertRaises(ValueError):sim.EncoderOdometry(axle_offset=bad)

    def test_loop_timing_counts_all_calls_and_bounds_slow_observations(self):
        timing = sim.LoopTiming()
        timing.observe('scan', 0., .001)
        timing.observe('spin_once', 0., .1)
        for index in range(100):
            timing.observe('publish', float(index), index+.2, float(index))
        value = timing.snapshot()
        self.assertEqual(value['stages']['mj_step']['total_s'], 0.)
        self.assertEqual(value['stages']['scan']['count'], 1)
        self.assertAlmostEqual(value['stages']['scan']['total_s'], .001)
        self.assertEqual(value['stages']['scan']['slow_count'], 0)
        self.assertEqual(value['stages']['spin_once']['slow_count'], 1)
        self.assertEqual(value['stages']['publish']['count'], 100)
        self.assertAlmostEqual(value['stages']['publish']['total_s'], 20.)
        self.assertAlmostEqual(value['stages']['publish']['max_s'], .2)
        self.assertEqual(len(value['slow_tail']), 32)
        self.assertEqual(value['slow_events_evicted'], 69)
        self.assertEqual(value['slow_tail'][0]['source_stamp'], 68.)
        json.dumps(value, allow_nan=False)
        value['stages']['scan']['count'] = 999
        value['stages']['scan']['total_s'] = 999.
        self.assertEqual(timing.snapshot()['stages']['scan']['count'], 1)
        self.assertAlmostEqual(timing.snapshot()['stages']['scan']['total_s'], .001)
        before = timing.snapshot()['stages']
        with self.assertRaises(ValueError):timing.observe('absent', 0., 1.)
        with self.assertRaises(ValueError):timing.observe('scan', 1., 0.)
        with self.assertRaises(ValueError):timing.observe('scan', math.nan, 1.)
        self.assertEqual(timing.snapshot()['stages'], before)
        def failed_call():raise RuntimeError('preserve original operation failure')
        with patch.object(sim.time, 'monotonic', side_effect=(20., 20.0125)):
            with self.assertRaisesRegex(RuntimeError, 'original operation failure'):
                timing.measure('record_flush', failed_call)
        self.assertEqual(timing.snapshot()['stages']['record_flush']['count'], 1)
        self.assertAlmostEqual(timing.snapshot()['stages']['record_flush']['total_s'], .0125)

    def test_docking_guard_uses_physical_plane_and_keeps_trip_until_disable(self):
        guard = sim.DockApproachGuard((10.,20.,math.pi/2))
        self.assertFalse(guard.update((10.,19.)))
        guard.set_enabled(True)
        self.assertFalse(guard.update((10.,20.5)))
        self.assertTrue(guard.update((13.,20.005)))
        guard.set_enabled(True)
        self.assertTrue(guard.update((10.,21.)))
        self.assertEqual(guard.state()['margin_m'], .01)
        self.assertEqual(guard.state()['dock_pose'], [10.,20.,math.pi/2])
        self.assertFalse(guard.state()['hardware_validated'])
        guard.set_enabled(False)
        self.assertFalse(guard.update((10.,19.)))
        self.assertFalse(guard.tripped)
        with self.assertRaises(ValueError):guard.set_enabled(1)
        with self.assertRaises(ValueError):guard.update((math.nan,0.))
        with self.assertRaises(ValueError):sim.DockApproachGuard((0.,0.,math.inf))

    def test_latest_sensor_qos_copies_standard_profile_without_mutating_it(self):
        try:
            from rclpy.qos import qos_profile_sensor_data, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
        except ImportError:
            self.skipTest('run with the existing ROS environment')
        profile = sim.latest_sensor_qos()
        self.assertIsNot(profile, qos_profile_sensor_data)
        self.assertEqual(profile.depth, 1)
        self.assertEqual(qos_profile_sensor_data.depth, 5)
        self.assertEqual(profile.reliability, ReliabilityPolicy.BEST_EFFORT)
        self.assertEqual(profile.history, HistoryPolicy.KEEP_LAST)
        self.assertEqual(profile.durability, DurabilityPolicy.VOLATILE)

    def test_cli_never_joins_physical_or_current_runtime_domain(self):
        for domain in (0, 107, 233):
            result = subprocess.run([sys.executable, str(TOOLS/'cooperation_sim.py'),
                                     '--scene', '/absent/world.xml', '--domain', str(domain)],
                                    capture_output=True, text=True, timeout=3.)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('isolated domain', result.stderr)


class ExitFinalizationTests(unittest.TestCase):
    """Execute the production finally block with local sinks, without ROS."""
    def setUp(self):
        tree = ast.parse((TOOLS/'cooperation_sim.py').read_text())
        runtime = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run_ros')
        final = next(node for node in reversed(runtime.body) if isinstance(node, ast.Try) and node.finalbody)
        wrapper = ast.parse('def shutdown_probe(operation):\n try:\n  operation()\n finally:\n  pass\n')
        wrapper.body[0].body[0].finalbody = copy.deepcopy(final.finalbody)
        self.code = compile(ast.fix_missing_locations(wrapper), '<current-simulation-finally>', 'exec')
        self.stderr = io.StringIO()

    def probe(self, errors=None, *, timing_enabled=True):
        errors = errors or {}
        events = []
        def stage(name):
            events.append(name)
            if name in errors:
                raise errors[name]
        def resource(name):
            return SimpleNamespace(close=lambda: stage(name+'.close'))
        class Control:
            def __setitem__(unused, key, value):
                events.append(('wheel_ctrl', key, value))
        class Writer(io.StringIO):
            saved = None
            def write(self, value):
                if 'timing_record.write' in errors:
                    raise errors['timing_record.write']
                return super().write(value)
            def flush(self):
                stage('timing_record.flush')
                return super().flush()
            def close(self):
                self.saved = self.getvalue()
                super().close()
                stage('timing_record.close')
        writer = Writer() if timing_enabled else None
        record = resource('record')
        record.snapshot = lambda: {'kind': 'controlled_test', 'closed': True}
        node = SimpleNamespace(camera=resource('camera'), lidar=resource('lidar'),
                               destroy_node=lambda: stage('node.destroy_node'),
                               runtime_observation={'rmw': 'controlled_test_not_ROS'})
        scope = {'sys': sys, 'json': json,
                 'physics': SimpleNamespace(wheels=SimpleNamespace(set_hold=lambda value: events.append(('hold', value))),
                                            data=SimpleNamespace(ctrl=Control()), wheel_a='wheels'),
                 'frames': resource('frames'), 'record': record, 'node': node,
                 'timing_record': writer, 'timing': sim.LoopTiming(),
                 # A context which is already stopped supports this idempotent API.
                 # There deliberately is no shutdown() fallback in the fixture.
                 'rclpy': SimpleNamespace(try_shutdown=lambda: stage('rclpy.try_shutdown'))}
        exec(self.code, scope)
        def invoke(operation=lambda: None):
            with contextlib.redirect_stderr(self.stderr):
                scope['shutdown_probe'](operation)
        return invoke, writer, events

    def assert_closed(self, writer, events):
        self.assertEqual(events[:2], [('hold', True), ('wheel_ctrl', 'wheels', 0.)])
        for stage in ('frames.close', 'camera.close', 'lidar.close', 'record.close',
                      'node.destroy_node', 'rclpy.try_shutdown',
                      'timing_record.flush', 'timing_record.close'):
            self.assertEqual(events.count(stage), 1, stage)
        self.assertTrue(writer.closed)

    def test_close_error_or_second_interrupt_keeps_other_closes_and_timing(self):
        for error in (RuntimeError('render close failed'), KeyboardInterrupt('second signal')):
            with self.subTest(error=type(error).__name__):
                invoke, writer, events = self.probe({'frames.close': error})
                with self.assertRaises(type(error)) as caught:
                    invoke()
                self.assertIs(caught.exception, error)
                self.assert_closed(writer, events)
                value = json.loads(writer.saved)
                self.assertEqual(value['rmw'], 'controlled_test_not_ROS')
                self.assertEqual(value['finalization_errors'], [{'stage': 'frames.close',
                    'type': type(error).__name__, 'message': str(error)}])

    def test_multiple_close_and_teardown_errors_preserve_first_failure(self):
        first = ValueError('first close')
        errors = {'frames.close': first, 'lidar.close': RuntimeError('later close'),
                  'node.destroy_node': KeyboardInterrupt('later signal')}
        invoke, writer, events = self.probe(errors)
        with self.assertRaises(ValueError) as caught:
            invoke()
        self.assertIs(caught.exception, first)
        self.assert_closed(writer, events)
        self.assertEqual([item['stage'] for item in json.loads(writer.saved)['finalization_errors']],
                         list(errors))

    def test_write_or_flush_failure_still_closes_writer_and_remains_error(self):
        for stage in ('timing_record.write', 'timing_record.flush'):
            with self.subTest(stage=stage):
                error = OSError('diagnostic output failed')
                invoke, writer, events = self.probe({stage: error})
                with self.assertRaises(OSError) as caught:
                    invoke()
                self.assertIs(caught.exception, error)
                self.assertTrue(writer.closed)
                self.assertEqual(events.count('timing_record.close'), 1)
                self.assertIn('rclpy.try_shutdown', events)
                self.assertIn('timing_record.write_flush: OSError', self.stderr.getvalue())

    def test_writer_close_failure_does_not_replace_earlier_close_failure(self):
        first = RuntimeError('frame close failed')
        invoke, writer, events = self.probe({'frames.close': first,
                                            'timing_record.close': OSError('writer close failed')})
        with self.assertRaises(RuntimeError) as caught:
            invoke()
        self.assertIs(caught.exception, first)
        self.assert_closed(writer, events)
        self.assertIn('timing_record.close: OSError', self.stderr.getvalue())

    def test_cleanup_failure_does_not_replace_original_main_loop_error(self):
        original = LookupError('physics operation failed')
        invoke, writer, events = self.probe({'frames.close': KeyboardInterrupt('second signal')})
        def operation():
            raise original
        with self.assertRaises(LookupError) as caught:
            invoke(operation)
        self.assertIs(caught.exception, original)
        self.assert_closed(writer, events)
        self.assertEqual(json.loads(writer.saved)['finalization_errors'][0]['type'], 'KeyboardInterrupt')

    def test_already_stopped_ros_context_uses_idempotent_shutdown(self):
        invoke, writer, events = self.probe()
        invoke()
        self.assert_closed(writer, events)
        self.assertEqual(json.loads(writer.saved)['finalization_errors'], [])

    def test_optional_timing_sink_does_not_prevent_resource_teardown(self):
        invoke, writer, events = self.probe(timing_enabled=False)
        invoke()
        self.assertIsNone(writer)
        self.assertEqual(events[-2:], ['node.destroy_node', 'rclpy.try_shutdown'])


class SharedWorldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import mujoco  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('run with the existing SO101 planning environment')
        cls.temporary = tempfile.TemporaryDirectory()
        scene = load('cooperation_scene', TOOLS/'cooperation_scene.py')
        cls.manifest = scene.build_scene(TOOLS.parent.parent/'so101', TOOLS.parent, Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'temporary'):
            cls.temporary.cleanup()

    def physics(self):
        return sim.Physics(self.manifest['world_xml'])

    def test_explicit_runtime_manifest_binds_physics_to_derived_policy_without_editing_prepared(self):
        world = Path(self.manifest['world_xml'])
        prepared = world.with_name('scene-manifest.json')
        original = prepared.read_bytes()
        derived = {**self.manifest, 'factory_policy': {'selected_egress_pose': None}}
        with tempfile.TemporaryDirectory() as directory:
            alternate = Path(directory)/'derived-manifest.json'
            alternate.write_text(json.dumps(derived))
            physics = sim.Physics(world, manifest=alternate)
            self.assertEqual(physics.identity['manifest'],derived)
            self.assertEqual(physics.identity['manifest_sha256'],
                             hashlib.sha256(alternate.read_bytes()).hexdigest())
            self.assertEqual(physics.identity['scene_sha256'],sim.source_identity(world)['scene_sha256'])
            self.assertNotEqual(physics.identity['manifest_sha256'],sim.source_identity(world)['manifest_sha256'])
            from cooperation_core import validate_physics
            raw = physics.state()
            validate_physics(raw,physics.identity['scene_sha256'],physics.identity['manifest_sha256'])
            with self.assertRaisesRegex(ValueError,'manifest SHA不匹配'):
                validate_physics(raw,physics.identity['scene_sha256'],sim.source_identity(world)['manifest_sha256'])
            self.assertEqual(prepared.read_bytes(),original)
            self.assertEqual(sim.parser().parse_args(['--scene',str(world),'--domain','141',
                             '--manifest',str(alternate)]).manifest,alternate)

    def test_episode_reset_restores_model_preserves_clock_and_encoder_and_rejects_old_references(self):
        import numpy as np
        physics = self.physics()
        old_episode = physics.episode_id
        physics.wheels.set_hold(False)
        for index in range(500):
            physics.wheels.accept(.1, 0., time.monotonic())
            physics.step()
        physics.wheels.set_hold(True)
        for index in range(1000):physics.step()
        self.assertTrue(physics.reset_ready)
        self.assertGreater(abs(physics.odom.x), .05)
        physics.observe_station()
        self.assertEqual(physics.station_beacon.sequence, 1)
        before = physics.state()
        # Explicit terminal-fixture mutation in this private model: a carried
        # object at delivery. It is never a live-world movement command.
        cargo_joint = physics.model.joint('target_free').id
        cargo_q = int(physics.model.jnt_qposadr[cargo_joint])
        physics.data.qpos[cargo_q:cargo_q+3] = physics.data.xpos[physics.tray_body]+[0.,0.,.011]
        physics.data.qvel[:] = 0.
        for index in range(1000):physics.step()
        self.assertTrue(physics.reset_ready)
        odom = (physics.odom.x, physics.odom.y, physics.odom.yaw,
                physics.odom.axle_x, physics.odom.axle_y)
        clock = float(physics.data.time);steps = physics.steps;sequence = physics.state_sequence
        new_episode, stamp = physics.reset_episode(old_episode)
        self.assertNotEqual(new_episode, old_episode)
        self.assertEqual(stamp, clock)
        self.assertEqual(physics.data.time, clock)
        self.assertEqual(physics.steps, steps)
        self.assertEqual(physics.state_sequence, sequence)
        np.testing.assert_array_equal(physics.data.qpos, physics.initial_qpos)
        np.testing.assert_array_equal(physics.data.qvel, np.zeros(physics.model.nv))
        np.testing.assert_array_equal(physics.data.ctrl[physics.wheel_a], [0.,0.])
        self.assertEqual((physics.odom.x,physics.odom.y,physics.odom.yaw,
                          physics.odom.axle_x,physics.odom.axle_y),odom)
        self.assertEqual((physics.odom.left,physics.odom.right),tuple(physics.data.qpos[physics.wheel_q]))
        raw = physics.state()
        self.assertEqual(raw['episode_id'], raw['source']['episode_id'])
        self.assertEqual(raw['episode_id'], new_episode)
        self.assertEqual(raw['source']['scene_sha256'],before['source']['scene_sha256'])
        self.assertEqual(raw['episode_reset']['count'],1)
        self.assertIsNone(raw['dock_beacon']['observation'])
        self.assertEqual(raw['dock_beacon']['sequence'], 0)
        self.assertEqual(raw['dock_beacon']['episode_id'], new_episode)
        self.assertEqual(raw['dock_beacon']['episode_start'], clock)
        self.assertTrue(raw['car_hold'])
        self.assertFalse(raw['docking_guard']['enabled'])
        self.assertFalse(raw['episode_reset']['ready'])
        for source in (None,stamp-.01,stamp):
            with self.assertRaises(ValueError):
                physics.set_arm_reference(sim.ARM_JOINTS,physics.initial_reference,source_stamp=source)
        physics.step()
        physics.set_arm_reference(sim.ARM_JOINTS,physics.initial_reference,
                                  source_stamp=float(physics.data.time))
        self.assertGreater(physics.data.time,clock)
        self.assertLess(abs(physics.odom.x-odom[0]),1e-5)  # No wheel-baseline jump.

    def test_episode_reset_refuses_active_native_motion_and_unheld_or_guarded_world(self):
        import numpy as np
        physics = self.physics()
        for index in range(1000):physics.step()
        self.assertTrue(physics.reset_ready)
        before=physics.data.qpos.copy();episode=physics.episode_id
        for change,restore in [(lambda: setattr(physics,'native_actions_busy',True),
                                lambda: setattr(physics,'native_actions_busy',False)),
                               (lambda: physics.wheels.set_hold(False),lambda: physics.wheels.set_hold(True)),
                               (lambda: physics.docking_guard.set_enabled(True),
                                lambda: physics.docking_guard.set_enabled(False))]:
            change()
            with self.assertRaises(ValueError):physics.reset_episode(episode)
            np.testing.assert_array_equal(physics.data.qpos,before)
            self.assertEqual(physics.episode_id,episode)
            restore()
        with self.assertRaises(ValueError):physics.reset_episode(str(uuid.uuid4()))
        physics.data.qvel[physics.arm_v[0]]=.1
        with self.assertRaises(ValueError):physics.reset_episode(episode)
        self.assertFalse(physics.reset_ready)
        self.assertEqual(physics.episode_id,episode)
        physics.data.qvel[:]=0.
        for index in range(300):physics.step()
        self.assertFalse(physics.reset_ready)  # A new .7s dwell is mandatory.
        for index in range(500):physics.step()
        self.assertTrue(physics.reset_ready)

    def test_render_commit_fences_old_episode_and_boundary_clears_pending(self):
        import numpy as np
        physics=self.physics()
        for index in range(1000):physics.step()
        with tempfile.TemporaryDirectory() as directory:
            writer=sim.FrameWriter.__new__(sim.FrameWriter)
            writer.physics,writer.directory=physics,Path(directory)
            writer.lock=threading.Lock();writer.pending=None
            writer.offer();old=writer.pending
            pixels=np.zeros((8,8,3),dtype=np.uint8)
            self.assertTrue(writer.commit(pixels,old))
            old_metadata=json.loads((writer.directory/'latest.json').read_text())
            self.assertEqual(old_metadata['episode_id'],physics.episode_id)
            self.assertEqual(old_metadata['image_file'],physics.episode_id+'.jpg')
            old_image=(writer.directory/old_metadata['image_file']).read_bytes()
            new_episode,_=writer.reset_episode(physics.episode_id)
            self.assertIsNone(writer.pending)
            self.assertFalse(writer.commit(pixels,old))
            self.assertEqual(json.loads((writer.directory/'latest.json').read_text()),old_metadata)
            writer.offer()
            self.assertTrue(writer.commit(pixels,writer.pending))
            new_metadata=json.loads((writer.directory/'latest.json').read_text())
            self.assertEqual(new_metadata['episode_id'],new_episode)
            self.assertEqual(new_metadata['image_file'],new_episode+'.jpg')
            self.assertEqual((writer.directory/old_metadata['image_file']).read_bytes(),old_image)
            self.assertTrue((writer.directory/new_metadata['image_file']).is_file())

    def test_actual_adapter_qos_and_latest_only_reception_after_reader_pause(self):
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
            from rclpy.utilities import get_rmw_implementation_identifier
            from std_msgs.msg import String
        except ImportError:
            self.skipTest('run with the existing ROS environment')
        with tempfile.TemporaryDirectory() as folder:
            timing_path, state_path = Path(folder)/'timing.json', Path(folder)/'state.jsonl'
            child = subprocess.Popen([sys.executable, str(TOOLS/'cooperation_sim.py'),
                '--scene', self.manifest['world_xml'], '--domain', '116', '--duration', '4',
                '--state-log', str(state_path), '--state-log-hz', '50', '--timing-log', str(timing_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            context = Context()
            rclpy.init(args=[], context=context, domain_id=116)
            node = rclpy.create_node('cooperation_qos_test', context=context)
            executor = SingleThreadedExecutor(context=context)
            executor.add_node(node)
            received = []
            node.create_subscription(String, '/cooperation/physics_state',
                lambda message: received.append(json.loads(message.data)), sim.latest_sensor_qos())
            try:
                # Cold MuJoCo mesh compilation precedes ROS publication.
                # Bound startup separately from the four-second live sample.
                until = time.monotonic()+15
                while not received and time.monotonic()<until and child.poll() is None:
                    executor.spin_once(timeout_sec=.02)
                if not received:
                    if child.poll() is None:
                        child.send_signal(signal.SIGINT)
                        child.wait(timeout=5)
                    self.fail(f'actual adapter produced no observed state; exit={child.returncode}; stderr={child.stderr.read()}')
                for topic in ('/clock', '/cooperation/physics_state'):
                    until = time.monotonic()+1.5
                    publishers = []
                    while not publishers and time.monotonic()<until:
                        publishers = [p for p in node.get_publishers_info_by_topic(topic)
                                      if p.node_name == 'cooperation_physics']
                        if not publishers:executor.spin_once(timeout_sec=.02)
                    self.assertEqual(len(publishers), 1)
                    profile = publishers[0].qos_profile
                    # Fast DDS endpoint discovery reports depth=0/history UNKNOWN.
                    # Assert available graph fields and the actual adapter's
                    # Publisher.qos_profile metadata; test replacement below.
                    if profile.depth > 0:self.assertEqual(profile.depth, 1)
                    self.assertEqual(profile.reliability, ReliabilityPolicy.BEST_EFFORT)
                    if profile.history not in (HistoryPolicy.UNKNOWN, HistoryPolicy.SYSTEM_DEFAULT):
                        self.assertEqual(profile.history, HistoryPolicy.KEEP_LAST)
                    self.assertEqual(profile.durability, DurabilityPolicy.VOLATILE)
                before = received[-1]
                # Keep the reader paused until the actual flushed producer
                # has progressed. Wall time does not imply a real-time factor.
                logged = None
                until = time.monotonic()+2
                while time.monotonic()<until:
                    if state_path.exists():
                        with state_path.open('rb') as source:
                            source.seek(0, 2)
                            offset = max(0, source.tell()-131072)
                            source.seek(offset)
                            tail = source.read(131072)
                        complete = tail.rsplit(b'\n', 1)[0].split(b'\n') if b'\n' in tail else []
                        if offset:complete = complete[1:]
                        if complete and complete[-1]:
                            logged = json.loads(complete[-1])
                    if (logged is not None and logged['stamp']-before['stamp'] > .12
                            and logged['sequence']-before['sequence'] > 6):
                        break
                    if child.poll() is not None:break
                    time.sleep(.02)
                self.assertIsNotNone(logged, 'producer supplied no flushed progress evidence')
                self.assertGreater(logged['stamp']-before['stamp'], .12,
                                   'producer failed to advance while the DDS reader was paused')
                self.assertGreater(logged['sequence']-before['sequence'], 6)
                count = len(received)
                until = time.monotonic()+1
                while len(received)==count and time.monotonic()<until:
                    executor.spin_once(timeout_sec=.02)
                self.assertGreater(len(received), count)
                after = received[count]
                self.assertGreater(after['sequence']-before['sequence'], 2)
                self.assertGreater(after['stamp']-before['stamp'], .08)
                self.assertEqual(after['source']['manifest']['world_xml'], self.manifest['world_xml'])
                self.assertEqual(child.wait(timeout=7), 0, child.stderr.read())
                value = json.loads(timing_path.read_text())
                self.assertEqual(value['ephemeral_qos']['/clock']['depth'], 1)
                self.assertEqual(value['ephemeral_qos']['/cooperation/physics_state']['reliability'], 'BEST_EFFORT')
                self.assertEqual(value['ephemeral_qos']['/cooperation/physics_state']['depth'], 1)
                self.assertEqual(value['ephemeral_qos']['/clock']['history'], 'KEEP_LAST')
                self.assertEqual(value['ephemeral_qos']['/cooperation/physics_state']['history'], 'KEEP_LAST')
                self.assertEqual(value['rmw'], get_rmw_implementation_identifier())
                self.assertLessEqual(len(value['slow_tail']), 32)
                for stage in ('spin_once','mj_step','publish','clock_publish','truth_publish',
                              'state_publish','record_write','scan'):
                    self.assertGreater(value['stages'][stage]['count'], 0)
                    self.assertTrue(math.isfinite(value['stages'][stage]['max_s']))
                self.assertTrue(value['record_write_includes_handler_flush'])
                self.assertEqual(value['stages']['record_flush']['count'], 0,
                                 'stdlib emit performs flush inside record_write, not in a second measured call')
            finally:
                if child.poll() is None:
                    child.send_signal(signal.SIGINT)
                    child.wait(timeout=5)
                if child.stderr:child.stderr.close()
                executor.shutdown(timeout_sec=2)
                node.destroy_node()
                rclpy.shutdown(context=context)

    def test_safe_reset_servo_hold_free_cargo_and_named_layout(self):
        physics = self.physics()
        self.assertEqual((physics.model.nq, physics.model.nv, physics.model.nu), (22,20,8))
        self.assertEqual(physics.reference, tuple(self.manifest['initial_arm_q6']))
        state = physics.state()
        self.assertEqual(state['q6'], self.manifest['initial_arm_q6'])
        self.assertEqual(len(state['qpos22']), 22)
        self.assertEqual(len(state['qvel20']), 20)
        self.assertEqual(state['ctrl'],physics.data.ctrl.tolist())
        self.assertEqual(state['time_s'],physics.data.time)
        self.assertTrue(state['car_hold'])
        for _ in range(250):
            physics.step()
        state = physics.state()
        self.assertTrue(state['finite'])
        self.assertEqual(state['arm_forbidden_contact_total'], 0)
        self.assertEqual(state['car_forbidden_contact_total'], 0)
        self.assertTrue(all(abs(q-r)<.025 for q,r in zip(state['q6'], physics.reference)))
        # The free object settles through gravity, rather than following an arm body.
        self.assertGreater(physics.model.body('grasp_target').mass[0], 0.)
        self.assertEqual(physics.model.body_parentid[physics.cargo_body], 0)
        self.assertEqual(physics.data.ctrl[physics.wheel_a].tolist(), [0.,0.])

    def test_rays_exclude_entire_car_and_observe_physical_arena(self):
        physics = self.physics()
        for _ in range(20):
            physics.step()
        values = physics.scan()
        self.assertEqual(len(values), 360)
        self.assertTrue(any(math.isfinite(x) for x in values))
        self.assertTrue(all(x >= .12 or math.isinf(x) for x in values))
        car_geoms = [g for g in range(physics.model.ngeom)
                     if physics.model.geom_bodyid[g] in physics.car_bodies]
        self.assertTrue(all(physics.model.geom_group[g] == 5 for g in car_geoms))
        self.assertEqual(physics.model.body('laser_link').pos.tolist(), [-.065,0.,.075])
        bench_group = int(physics.model.geom_group[physics.model.geom('pick_bench').id])
        self.assertEqual(int(physics.ray_groups[bench_group]), 1)
        # The batched native ray API agrees with individual physical rays.
        origin = physics.data.xpos[physics.laser_body].copy()
        rotation = physics.data.xmat[physics.laser_body].reshape(3,3)
        for beam in (0, 45, 90, 135, 180, 225, 270, 315):
            hit = physics.np.zeros(1, dtype=physics.np.int32)
            theta = beam*math.pi/180
            direction = rotation @ physics.np.array([math.cos(theta), math.sin(theta), 0.])
            distance = physics.mj.mj_ray(physics.model, physics.data, origin, direction,
                                       physics.ray_groups, 1, -1, hit)
            expected = distance if .12 <= distance <= 3.5 else math.inf
            self.assertAlmostEqual(values[beam], expected)

    def test_slip_truth_and_encoder_odom_are_distinct(self):
        physics = self.physics()
        physics.wheels.set_hold(False)
        initial = physics.data.xpos[physics.car_body].copy()
        for _ in range(500):
            physics.wheels.accept(.1, 0., time.monotonic())
            physics.step()
        displacement = physics.np.linalg.norm(physics.data.xpos[physics.car_body][:2]-initial[:2])
        self.assertGreater(displacement, .05)
        self.assertGreater(physics.odom.x, .05)
        self.assertGreater(abs(physics.odom.x-displacement), 1e-5)
        self.assertEqual(physics.state()['arm_forbidden_contact_total'], 0)
        # Holding produces zero servo commands even with a live incoming command.
        physics.wheels.set_hold(True)
        physics.wheels.accept(.2, .2, time.monotonic())
        physics.step()
        self.assertEqual(physics.data.ctrl[physics.wheel_a].tolist(), [0.,0.])

    def test_moving_snapshot_refresh_aligns_free_body_poses_without_integrating(self):
        physics = self.physics()
        physics.wheels.set_hold(False)
        witnessed_step_lag = False
        snapshots = 0
        for step in range(500):
            physics.wheels.accept(.1, .2, time.monotonic())
            physics.step()
            if (step+1) % 10:
                continue
            car_joint = physics.model.joint('base_free_joint')
            cargo_joint = physics.model.joint('target_free')
            car_q = physics.data.qpos[int(car_joint.qposadr[0]):int(car_joint.qposadr[0])+3]
            witnessed_step_lag |= bool(physics.np.linalg.norm(car_q-physics.data.xpos[physics.car_body]) > 1e-6)
            primary = [physics.data.qpos.copy(), physics.data.qvel.copy(), physics.data.ctrl.copy()]
            stamp, steps = float(physics.data.time), physics.steps
            counters = (physics.total_forbidden_contacts, physics.total_forbidden_steps,
                        physics.total_car_forbidden_contacts, physics.total_car_forbidden_steps)
            physics.refresh_snapshot()
            self.assertTrue(all(physics.np.array_equal(before, after) for before, after in zip(
                primary, (physics.data.qpos, physics.data.qvel, physics.data.ctrl))))
            self.assertEqual(float(physics.data.time), stamp)
            self.assertEqual(physics.steps, steps)
            self.assertEqual(counters, (physics.total_forbidden_contacts, physics.total_forbidden_steps,
                                       physics.total_car_forbidden_contacts, physics.total_car_forbidden_steps))
            for joint, body in ((car_joint, physics.car_body), (cargo_joint, physics.cargo_body)):
                address = int(joint.qposadr[0])
                self.assertTrue(physics.np.allclose(physics.data.xpos[body], physics.data.qpos[address:address+3],
                                                   rtol=0., atol=1e-12))
                self.assertTrue(physics.np.allclose(physics.data.xquat[body], physics.data.qpos[address+3:address+7],
                                                   rtol=0., atol=1e-12))
            snapshots += 1
        self.assertTrue(witnessed_step_lag)
        self.assertEqual(snapshots, 50)

    def test_clone_velocities_match_body_origin_jacobians_and_position_derivatives(self):
        physics = self.physics()
        clone = copy.copy(physics)
        clone.data = physics.mj.MjData(physics.model)
        clone.data.qpos[:] = physics.data.qpos
        clone.data.ctrl[:] = physics.data.ctrl
        joint = physics.model.joint('base_free_joint')
        q, v = int(joint.qposadr[0]), int(joint.dofadr[0])
        clone.data.qpos[q:q+3] = [-1.1, -1.8, .002]
        clone.data.qpos[q+3:q+7] = [math.cos(.15), 0., 0., math.sin(.15)]
        # Only this isolated MjData gets translation and angular velocity.
        clone.data.qvel[v:v+6] = [.08, -.03, .01, .11, -.04, .5]
        physics.mj.mj_forward(physics.model, clone.data)
        before = [clone.data.qpos.copy(), clone.data.qvel.copy(), clone.data.ctrl.copy()]
        future = physics.mj.MjData(physics.model)
        future.qpos[:] = clone.data.qpos
        future.qvel[:] = clone.data.qvel
        epsilon = 1e-7
        physics.mj.mj_integratePos(physics.model, future.qpos, future.qvel, epsilon)
        physics.mj.mj_forward(physics.model, future)
        for body in (physics.car_body, physics.tray_body):
            linear_jac = physics.np.zeros((3, physics.model.nv))
            angular_jac = physics.np.zeros((3, physics.model.nv))
            physics.mj.mj_jacBody(physics.model, clone.data, linear_jac, angular_jac, body)
            measured = physics.np.array(clone.body_velocity(body))
            physics.np.testing.assert_allclose(measured[:3], angular_jac @ clone.data.qvel, atol=1e-12)
            physics.np.testing.assert_allclose(measured[3:], linear_jac @ clone.data.qvel, atol=1e-12)
            derivative = (future.xpos[body]-clone.data.xpos[body])/epsilon
            physics.np.testing.assert_allclose(measured[3:], derivative, atol=1e-7, rtol=0.)
        physics.np.testing.assert_allclose(clone.body_velocity(physics.car_body)[3:], [.08,-.03,.01], atol=1e-12)
        com_velocity = physics.np.zeros(6)
        physics.mj.mj_objectVelocity(physics.model, clone.data, physics.mj.mjtObj.mjOBJ_BODY,
                                    physics.car_body, com_velocity, 0)
        self.assertGreater(physics.np.linalg.norm(com_velocity[3:]-clone.body_velocity(physics.car_body)[3:]), .1)
        self.assertTrue(all(physics.np.array_equal(a, b) for a, b in zip(
            before, (clone.data.qpos, clone.data.qvel, clone.data.ctrl))))
        self.assertTrue(physics.np.array_equal(physics.data.qvel, physics.np.zeros(physics.model.nv)))

    def test_compiled_axle_geometry_and_actual_rotation_move_the_foot_origin(self):
        physics = self.physics()
        offset = physics.np.array(physics.encoder_axle_offset)
        self.assertAlmostEqual(offset[0], -.02)
        self.assertAlmostEqual(offset[1], 0.)
        for _ in range(250):physics.step()
        physics.refresh_snapshot()
        initial_foot = physics.data.xpos[physics.car_body].copy()
        rotation = physics.data.xmat[physics.car_body].reshape(3,3).copy()
        initial_axle = initial_foot+rotation@offset
        old_odom = sim.EncoderOdometry(*(float(physics.data.qpos[i]) for i in physics.wheel_q))
        wheel_centres = [physics.data.xpos[int(physics.model.jnt_bodyid[joint])]
                         for joint in physics.wheel_joint_ids]
        physics.np.testing.assert_allclose(initial_axle, (wheel_centres[0]+wheel_centres[1])/2, atol=1e-12)
        physics.wheels.set_hold(False)
        for _ in range(1000):
            physics.wheels.accept(0., .5, time.monotonic())
            physics.step()
            old_odom.update(*(float(physics.data.qpos[i]) for i in physics.wheel_q), .002)
        physics.refresh_snapshot()
        observed = rotation.T @ (physics.data.xpos[physics.car_body]-initial_foot)
        axle_final = physics.data.xpos[physics.car_body]+physics.data.xmat[physics.car_body].reshape(3,3)@offset
        self.assertGreater(physics.np.linalg.norm(observed[:2]), .005)
        self.assertLess(physics.np.linalg.norm((axle_final-initial_axle)[:2]), .006)
        old_point_error = physics.np.linalg.norm(physics.np.array([old_odom.x,old_odom.y])-observed[:2])
        corrected_error = physics.np.linalg.norm(physics.np.array([physics.odom.x,physics.odom.y])-observed[:2])
        self.assertLess(corrected_error, old_point_error*.6)
        # Remaining encoder slip is not corrected from the measured world pose.
        self.assertGreater(corrected_error, 1e-5)
        self.assertEqual(physics.state()['encoder_odometry_geometry']['axle_offset_in_foot'], offset.tolist())
        self.__class__.rotation_evidence = {
            'compiled_axle_offset_in_foot': offset.tolist(), 'physics_steps_rotation': 1000,
            'wheel_requested_v_m_s': 0., 'wheel_requested_omega_rad_s': .5,
            'true_origin_displacement_in_initial_foot': observed.tolist(),
            'true_axle_drift_world_xy_m': float(physics.np.linalg.norm((axle_final-initial_axle)[:2])),
            'old_encoder_point_pose_xy': [old_odom.x,old_odom.y],
            'corrected_encoder_foot_pose_xy': [physics.odom.x,physics.odom.y],
            'old_point_error_m': float(old_point_error), 'corrected_point_error_m': float(corrected_error),
            'wheel_encoder_yaw': physics.odom.yaw,
            'corrected_body_lateral_velocity_m_s': physics.odom.lateral_velocity,
            'source': physics.identity}

    def test_actual_incoming_velocity_guard_brakes_before_plane_and_disable_restores_motion(self):
        scene = load('cooperation_scene_guard', TOOLS/'cooperation_scene.py')
        with tempfile.TemporaryDirectory() as folder:
            dock = self.manifest['dock_pose']
            manifest = scene.build_scene(TOOLS.parent.parent/'so101', TOOLS.parent, Path(folder),
                                         spawn=(dock[0]+.25,dock[1]))
            physics = sim.Physics(manifest['world_xml'])
            for _ in range(250):physics.step()
            arm_ctrl = physics.data.ctrl[physics.arm_a].copy()
            physics.docking_guard.set_enabled(True)
            physics.wheels.set_hold(False)
            car_v = int(physics.model.jnt_dofadr[physics.model.joint('base_free_joint').id])
            incoming_speed = minimum_along = 0.
            trip_stamp = trip_speed = None
            minimum_along = math.inf
            for step in range(2500):
                physics.wheels.accept(-.15,0.,time.monotonic())
                physics.step()
                minimum_along = min(minimum_along,physics.docking_guard.along_m)
                incoming_speed = max(incoming_speed,abs(float(physics.data.qvel[car_v])))
                if physics.docking_guard.tripped:
                    trip_stamp = float(physics.data.time)
                    trip_speed = float(physics.data.qvel[car_v])
                    break
            self.assertIsNotNone(trip_stamp)
            self.assertGreater(incoming_speed, .1)
            self.assertFalse(physics.wheels.hold)
            self.assertTrue(physics.np.array_equal(physics.data.ctrl[physics.wheel_a],[0.,0.]))
            for _ in range(500):
                physics.wheels.accept(-.15,0.,time.monotonic())
                physics.step()
                minimum_along = min(minimum_along,physics.docking_guard.along_m)
                self.assertTrue(physics.np.array_equal(physics.data.ctrl[physics.wheel_a],[0.,0.]))
                self.assertTrue(physics.np.array_equal(physics.data.ctrl[physics.arm_a],arm_ctrl))
            self.assertGreaterEqual(minimum_along, 0.)
            self.assertTrue(physics.docking_guard.tripped)
            self.assertTrue(physics.state()['docking_guard']['enabled'])
            self.assertTrue(physics.state()['docking_guard']['tripped'])
            self.assertFalse(physics.wheels.hold)
            stopped_along = physics.docking_guard.along_m
            # Match the bridge's explicit hold, disable, then new command sequence.
            physics.wheels.set_hold(True)
            physics.step()
            physics.docking_guard.set_enabled(False)
            physics.wheels.set_hold(False)
            for _ in range(300):
                physics.wheels.accept(.1,0.,time.monotonic())
                physics.step()
            self.assertFalse(physics.docking_guard.tripped)
            self.assertGreater(physics.docking_guard.along_m-stopped_along,.03)
            self.assertEqual(physics.state()['car_forbidden_contact_total'],0)
            self.assertEqual(physics.state()['arm_forbidden_contact_total'],0)
            self.__class__.guard_evidence = {'incoming_max_speed_m_s':incoming_speed,
                'trip_source_stamp':trip_stamp,'trip_speed_m_s':trip_speed,
                'minimum_actual_along_m':minimum_along,'settled_along_m':stopped_along,
                'disable_then_nav_outward_displacement_m':physics.docking_guard.along_m-stopped_along,
                'wheel_ctrl_latched_zero_despite_fresh_incoming_commands':True,
                'wheels_hold_unchanged_on_trip':True,'physics_qpos_qvel_not_assigned_by_guard':True}

    def test_beacon_measurement_preserves_physics_and_uses_manifest_pose(self):
        physics = self.physics()
        for _ in range(100):physics.step()
        physics.refresh_snapshot()
        primary = [physics.data.qpos.copy(), physics.data.qvel.copy(), physics.data.ctrl.copy()]
        stamp, steps = float(physics.data.time), physics.steps
        self.assertIsNone(physics.beacon())  # Initial car is over one metre away.
        state = physics.state()
        self.assertFalse(state['dock_beacon']['in_range'])
        self.assertEqual(state['dock_beacon']['source_stamp'],stamp)
        self.assertEqual(state['dock_beacon']['physical_robot_dock_pose'],self.manifest['dock_pose'])
        self.assertTrue(all(physics.np.array_equal(before, after) for before, after in zip(
            primary, (physics.data.qpos,physics.data.qvel,physics.data.ctrl))))
        self.assertEqual(float(physics.data.time),stamp)
        self.assertEqual(physics.steps,steps)

    def test_in_range_beacon_reads_current_free_body_without_moving_it(self):
        scene = load('cooperation_beacon_scene', TOOLS/'cooperation_scene.py')
        with tempfile.TemporaryDirectory() as temporary:
            manifest = scene.build_scene(TOOLS.parent.parent/'so101', TOOLS.parent,
                                         Path(temporary), spawn=(-1.1,-1.84))
            physics = sim.Physics(manifest['world_xml'])
            for _ in range(50):physics.step()
            physics.refresh_snapshot()
            primary = [physics.data.qpos.copy(),physics.data.qvel.copy(),physics.data.ctrl.copy()]
            result = physics.beacon()
            self.assertIsNotNone(result)
            x,y,_ = result
            self.assertAlmostEqual(math.hypot(x,y), math.hypot(
                manifest['dock_pose'][0]-physics.data.xpos[physics.car_body][0],
                manifest['dock_pose'][1]-physics.data.xpos[physics.car_body][1]),places=12)
            self.assertEqual(physics.station_beacon.truth.stamp,float(physics.data.time))
            self.assertTrue(physics.state()['dock_beacon']['in_range'])
            self.assertTrue(all(physics.np.array_equal(a,b) for a,b in zip(primary,
                (physics.data.qpos,physics.data.qvel,physics.data.ctrl))))

    def test_physical_state_reads_do_not_resample_declared_station_noise(self):
        scene = load('cooperation_station_noise_scene', TOOLS/'cooperation_scene.py')
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = scene.build_scene(TOOLS.parent.parent/'so101', TOOLS.parent,
                                         directory, spawn=(-1.1,-1.84))
            manifest['station_perception'] = {
                'mode': 'perturbed', 'max_covariance': [.01]*3,
                'noise_std': [.02,.03,.04], 'seed': 37}
            (directory/'scene-manifest.json').write_text(json.dumps(manifest))
            physics = sim.Physics(manifest['world_xml'])
            for _ in range(50):physics.step()
            physics.refresh_snapshot()
            snapshot = [physics.data.qpos.copy(),physics.data.qvel.copy(),physics.data.ctrl.copy()]
            sample = physics.observe_station()
            rng_state = physics.station_beacon.rng.getstate()
            for _ in range(5):
                self.assertEqual(physics.state()['dock_beacon']['observation'], sample)
            self.assertEqual(physics.station_beacon.rng.getstate(), rng_state)
            self.assertEqual(physics.station_beacon.sequence, 1)
            for before, after in zip(snapshot, (physics.data.qpos,physics.data.qvel,physics.data.ctrl)):
                physics.np.testing.assert_array_equal(before, after)
            # Advancing physics does not itself generate a detector sample.
            physics.step()
            self.assertEqual(physics.state()['dock_beacon']['observation'], sample)
            self.assertEqual(physics.station_beacon.sequence, 1)
            next_sample = physics.observe_station()
            self.assertEqual(next_sample['sequence'], 2)
            self.assertGreater(next_sample['stamp'], sample['stamp'])

    def test_actual_publish_samples_station_on_every_state_cycle_without_scan(self):
        """Exercise the production method without ROS initialization or DDS."""
        from builtin_interfaces.msg import Time
        from geometry_msgs.msg import PoseStamped, TransformStamped
        from nav_msgs.msg import Odometry
        from rosgraph_msgs.msg import Clock
        from sensor_msgs.msg import Imu, JointState, LaserScan
        from std_msgs.msg import String
        physics = self.physics()
        dock = self.manifest['dock_pose']
        physics.data.qpos[physics.car_free_q:physics.car_free_q+2] = [dock[0]+.7, dock[1]]
        # Compile the actual closure method. Only its DDS sinks are substituted.
        tree = ast.parse((TOOLS/'cooperation_sim.py').read_text())
        runtime = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run_ros')
        adapter = next(node for node in runtime.body if isinstance(node, ast.ClassDef) and node.name == 'Adapter')
        methods = [next(node for node in adapter.body if isinstance(node, ast.FunctionDef) and node.name == 'publish'),
                   next(node for node in runtime.body if isinstance(node, ast.FunctionDef) and node.name == 'fill_pose'),
                   next(node for node in runtime.body if isinstance(node, ast.FunctionDef) and node.name == 'stamp')]
        timing = sim.LoopTiming(lambda: float(physics.data.time))
        scope = {'physics': physics, 'timing': timing, 'record': None, 'frames': None,
                 'Time': Time, 'TransformStamped': TransformStamped, 'PoseStamped': PoseStamped,
                 'Odometry': Odometry, 'Clock': Clock, 'Imu': Imu, 'JointState': JointState,
                 'LaserScan': LaserScan, 'String': String, 'math': math, 'json': json,
                 'ARM_JOINTS': sim.ARM_JOINTS, 'WHEEL_JOINTS': sim.WHEEL_JOINTS,
                 'station_messages': sim.station_messages, 'time': time}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(TOOLS/'cooperation_sim.py'), 'exec'), scope)
        sinks = {name: [] for name in ('clock','scan','imu','joint','odom','truth','cargo','state',
                                       'station_pose','station_detection')}
        node = SimpleNamespace(last_rejected=None, runtime_observation={}, tf=SimpleNamespace(sendTransform=lambda message: None))
        for name, messages in sinks.items():
            setattr(node, name+'_pub', SimpleNamespace(publish=messages.append))
        measurements = []
        camera_offers = []
        node.camera = SimpleNamespace(error=None, rendered=0,
                                      offer=lambda: camera_offers.append(float(physics.data.time)))
        original = physics.station_beacon.measure
        def observed_measure(car_pose, source_stamp):
            measurements.append(source_stamp)
            return original(car_pose, source_stamp)
        physics.station_beacon.measure = observed_measure
        for include_scan in (False, True, False):
            for _ in range(10):physics.step()
            scope['publish'](node, include_scan)
        self.assertEqual(len(measurements), 3)
        self.assertEqual(physics.station_beacon.sequence, 3)
        self.assertEqual(len(sinks['scan']), 1)
        self.assertEqual(len(sinks['station_pose']), 3)
        self.assertEqual(len(sinks['station_detection']), 3)
        self.assertEqual(camera_offers, measurements)
        self.assertEqual(timing.stats['camera_offer']['count'], 3)
        for sequence, (pose, detection, state) in enumerate(zip(
                sinks['station_pose'], sinks['station_detection'], sinks['state']), start=1):
            cached = json.loads(state.data)['dock_beacon']['observation']
            self.assertEqual(pose.header, detection.header)
            self.assertEqual(cached['sequence'], sequence)
            self.assertAlmostEqual(cached['stamp'], measurements[sequence-1])
            self.assertEqual(detection.header.stamp.sec*1_000_000_000+detection.header.stamp.nanosec,
                             round(measurements[sequence-1]*1_000_000_000))
        # The actual vision branch offers a new camera source snapshot without
        # synthesizing a station observation, even with scan disabled.
        physics.station_beacon.perception_config = {'mode': 'vision'}
        for _ in range(10):physics.step()
        scope['publish'](node, False)
        self.assertEqual(len(camera_offers), 4)
        self.assertEqual(timing.stats['camera_offer']['count'], 4)
        self.assertEqual(len(sinks['station_pose']), 3)


if __name__ == '__main__':
    unittest.main()
