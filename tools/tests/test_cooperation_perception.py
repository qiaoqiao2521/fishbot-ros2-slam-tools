"""Behavioral station-input boundaries, without ROS or simulator dependencies."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest


TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import cooperation_perception as contract
from cooperation_core import station_robot_pose


EPISODE = 'b6a22d12-bb0c-4cc4-a77b-c573bf14fe0c'
NEXT_EPISODE = 'a23e1d18-4b9d-4e8e-a5c0-fa7e31f1de9c'
IDENTITY = {'scene_sha256': 'a'*64, 'manifest_sha256': 'b'*64,
            'episode_id': EPISODE, 'reset_stamp': None}


def covariance(diagonal=(.0001, .0001, .0001)):
    result = [0.]*36
    for axis, variance in zip(contract.PLANE_AXES, diagonal):
        result[axis*6+axis] = variance
    return result


def header(stamp_ns=10_000_000_000, frame='base_footprint'):
    sec, nanosec = divmod(stamp_ns, 1_000_000_000)
    return NS(stamp=NS(sec=sec, nanosec=nanosec), frame_id=frame)


def pair(*, stamp_ns=10_000_000_000, sequence=1, detected=True, mode='ideal',
         publisher='cooperation_physics', relative=(.5, .1, .2), variance=None):
    metadata = {'schema': '1', 'publisher': publisher, 'mode': mode,
                'station_id': 'so101_station', 'scene_sha256': IDENTITY['scene_sha256'],
                'manifest_sha256': IDENTITY['manifest_sha256'], 'episode_id': EPISODE,
                'sequence': str(sequence), 'detected': str(detected).lower(),
                'confidence': '1' if detected else '0',
                'reason': 'detected' if detected else 'occluded',
                'idealized_truth_derived': str(mode != 'vision').lower()}
    status = NS(name=contract.DIAGNOSTIC_NAME, hardware_id='so101_station',
                level=0 if detected else 1,
                values=[NS(key=key, value=value) for key, value in metadata.items()])
    diagnostics = NS(header=header(stamp_ns), status=[status])
    x, y, yaw = relative
    pose = NS(header=header(stamp_ns), pose=NS(
        pose=NS(position=NS(x=x, y=y, z=0.),
                orientation=NS(w=math.cos(yaw/2), x=0., y=0., z=math.sin(yaw/2))),
        covariance=covariance() if variance is None else variance))
    return pose, diagnostics


def set_metadata(diagnostics, key, value):
    next(item for item in diagnostics.status[0].values if item.key == key).value = value


def observation(**kwargs):
    return contract.messages_to_observation(*pair(**kwargs))


def validate(obs=None, **kwargs):
    options = {'config': None, 'identity': IDENTITY,
               'now_stamp': 10.1, 'received_age': .1, 'last_accepted': None}
    options.update(kwargs)
    return contract.validate_observation(observation() if obs is None else obs, **options)


class ConfigurationTest(unittest.TestCase):
    def test_default_is_explicit_ideal_contract_and_idempotent(self):
        config = contract.normalize_config()
        self.assertEqual(config['mode'], 'ideal')
        self.assertEqual(config['max_covariance'], [.0001]*3)
        self.assertEqual(config['publisher'], 'cooperation_physics')
        self.assertEqual(contract.normalize_config(config), config)

    def test_vision_requires_declared_source_confidence_and_variance(self):
        complete = {'mode': 'vision', 'publisher': 'station_camera',
                    'min_confidence': .8, 'max_covariance': [.003, .002, .01]}
        for key in ('publisher', 'min_confidence', 'max_covariance'):
            missing = dict(complete)
            del missing[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                contract.normalize_config(missing)
        self.assertEqual(contract.normalize_config(complete)['publisher'], 'station_camera')
        with self.assertRaises(ValueError):
            contract.normalize_config(dict(complete, publisher='cooperation_physics'))

    def test_synthetic_mode_cannot_claim_external_vision_source(self):
        for mode in ('ideal', 'perturbed'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                contract.normalize_config({'mode': mode, 'publisher': 'station_camera',
                                           'max_covariance': [.0001]*3})

    def test_original_range_and_ideal_covariance_are_not_relaxed(self):
        for config in ({'range_limit_m': 1.01}, {'min_confidence': .9},
                       {'max_covariance': [.001]*3}, {'range_limit_m': 0.}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                contract.normalize_config(config)

    def test_perturbation_requires_variance_covering_its_declared_noise(self):
        base = {'mode': 'perturbed', 'noise_std': [.01, .02, .03]}
        with self.assertRaises(ValueError):
            contract.normalize_config(base)
        with self.assertRaises(ValueError):
            contract.normalize_config(dict(base, max_covariance=[.0001]*3))
        config = contract.normalize_config(dict(base, max_covariance=[.0002, .0005, .001]))
        self.assertEqual(config['noise_std'], [.01, .02, .03])
        self.assertEqual(config['occlusion_windows'], [])

    def test_occlusion_windows_are_bounded_ordered_episode_intervals(self):
        base = {'mode': 'perturbed', 'max_covariance': [.0001]*3}
        expected = [[0., .1], [.1, .2], [2., 3.]]
        self.assertEqual(contract.normalize_config(dict(base, occlusion_windows=expected))[
            'occlusion_windows'], expected)
        for windows in ([[[-.1, 1.]]], [[1., 1.]], [[2., 3.], [0., 1.]],
                        [[0., 2.], [1., 3.]], [[0., math.inf]], [[0., 1.]]*65):
            with self.subTest(windows=windows), self.assertRaises(ValueError):
                contract.normalize_config(dict(base, occlusion_windows=windows))

    def test_malformed_config_never_silently_changes_mode(self):
        for config in ([], {'mode': 'camera'}, {'schema': True}, {'frame_id': 'map'},
                       {'range_limit_m': math.nan}, {'unknown': 1},
                       {'mode': 'perturbed', 'max_covariance': [.0001]*3, 'seed': True},
                       {'mode': 'perturbed', 'max_covariance': [.0001]*3, 'dropout_probability': 2}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                contract.normalize_config(config)


class ParsingTest(unittest.TestCase):
    def test_standard_pose_and_diagnostics_keep_original_source_time(self):
        obs = observation(stamp_ns=10_123_456_789, sequence=23)
        self.assertEqual(obs['stamp_ns'], 10_123_456_789)
        self.assertAlmostEqual(obs['stamp'], 10.123456789)
        self.assertEqual(obs['sequence'], 23)
        self.assertAlmostEqual(obs['relative'][2], .2)
        self.assertEqual(obs['covariance'], tuple(covariance()))

    def test_missing_diagnostics_and_successful_pose_are_rejected(self):
        pose, diagnostics = pair()
        with self.assertRaises(ValueError):
            contract.messages_to_observation(pose, None)
        with self.assertRaises(ValueError):
            contract.messages_to_observation(None, diagnostics)

    def test_failed_detection_can_exist_without_pose(self):
        _, diagnostics = pair(detected=False)
        obs = contract.messages_to_observation(None, diagnostics)
        self.assertFalse(obs['detected'])
        self.assertIsNone(obs['relative'])
        self.assertIsNone(obs['covariance'])
        self.assertEqual(obs['reason'], 'occluded')

    def test_failed_detection_does_not_reuse_even_a_supplied_pose(self):
        obs = observation(detected=False)
        self.assertIsNone(obs['relative'])
        self.assertIsNone(obs['covariance'])

    def test_headers_must_match_exact_nanosecond_and_frame(self):
        for change in ('stamp', 'frame'):
            pose, diagnostics = pair()
            if change == 'stamp':
                pose.header.stamp.nanosec += 1
            else:
                pose.header.frame_id = 'camera'
            with self.subTest(change=change), self.assertRaises(ValueError):
                contract.messages_to_observation(pose, diagnostics)

    def test_duplicate_diagnostic_key_is_rejected(self):
        pose, diagnostics = pair()
        diagnostics.status[0].values.append(NS(key='detected', value='false'))
        with self.assertRaises(ValueError):
            contract.messages_to_observation(pose, diagnostics)

    def test_diagnostic_cardinality_identity_and_level_are_checked(self):
        for change in ('empty', 'duplicate', 'identity', 'level', 'unknown_level'):
            pose, diagnostics = pair()
            if change == 'empty':
                diagnostics.status = []
            elif change == 'duplicate':
                diagnostics.status *= 2
            elif change == 'identity':
                diagnostics.status[0].hardware_id = 'other_station'
            elif change == 'level':
                diagnostics.status[0].level = 1
            else:
                diagnostics.status[0].level = 3
            with self.subTest(change=change), self.assertRaises(ValueError):
                contract.messages_to_observation(pose, diagnostics)

    def test_ros_byte_diagnostic_levels_are_supported_without_coercion(self):
        for detected, level in ((True, b'\x00'), (False, b'\x01'), (False, b'\x02')):
            pose, diagnostics = pair(detected=detected)
            diagnostics.status[0].level = level
            self.assertEqual(contract.messages_to_observation(pose, diagnostics)['detected'], detected)
        for level in (b'', b'\x00\x00', b'\x03', True, '0'):
            pose, diagnostics = pair()
            diagnostics.status[0].level = level
            with self.subTest(level=level), self.assertRaises(ValueError):
                contract.messages_to_observation(pose, diagnostics)

    def test_malformed_metadata_is_rejected(self):
        for key, value in (('confidence', 'nan'), ('confidence', '2'), ('confidence', 'x'),
                           ('sequence', '-1'), ('sequence', '1.0'), ('sequence', '+1'),
                           ('episode_id', 'bad'), ('scene_sha256', 'A'*64),
                           ('manifest_sha256', 'missing'), ('detected', '1'),
                           ('idealized_truth_derived', 'True'), ('schema', '2')):
            pose, diagnostics = pair()
            set_metadata(diagnostics, key, value)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                contract.messages_to_observation(pose, diagnostics)

    def test_missing_metadata_does_not_supply_defaults(self):
        pose, diagnostics = pair()
        diagnostics.status[0].values.pop()
        with self.assertRaises(ValueError):
            contract.messages_to_observation(pose, diagnostics)

    def test_missing_status_values_is_rejected_as_missing_metadata(self):
        pose, diagnostics = pair()
        del diagnostics.status[0].values
        with self.assertRaisesRegex(ValueError, 'metadata'):
            contract.messages_to_observation(pose, diagnostics)

    def test_missing_reason_is_not_a_valid_loss_report(self):
        _, diagnostics = pair(detected=False)
        set_metadata(diagnostics, 'reason', '')
        with self.assertRaises(ValueError):
            contract.messages_to_observation(None, diagnostics)

    def test_pose_requires_finite_position_and_normalized_quaternion(self):
        for change in ('nan_position', 'inf_quaternion', 'zero_quaternion', 'unnormalized'):
            pose, diagnostics = pair()
            if change == 'nan_position':
                pose.pose.pose.position.x = math.nan
            elif change == 'inf_quaternion':
                pose.pose.pose.orientation.z = math.inf
            elif change == 'zero_quaternion':
                pose.pose.pose.orientation.w = pose.pose.pose.orientation.z = 0.
            else:
                pose.pose.pose.orientation.w = 2.
            with self.subTest(change=change), self.assertRaises(ValueError):
                contract.messages_to_observation(pose, diagnostics)

    def test_source_time_requires_valid_ros_stamp(self):
        for sec, nano in ((0, 0), (-1, 0), (1, -1), (1, 1_000_000_000), (True, 0)):
            pose, diagnostics = pair()
            diagnostics.header.stamp = NS(sec=sec, nanosec=nano)
            with self.subTest(sec=sec, nano=nano), self.assertRaises(ValueError):
                contract.messages_to_observation(pose, diagnostics)


class CovarianceTest(unittest.TestCase):
    def test_rank_deficient_positive_semidefinite_matrix_is_valid(self):
        values = covariance((.0001, .0001, .0001))
        values[1] = values[6] = .0001
        matrix = contract.covariance_matrix(values)
        self.assertEqual(matrix[0][1], .0001)

    def test_nonfinite_negative_nonsymmetric_and_indefinite_are_rejected(self):
        for change in ('nan', 'negative', 'asymmetric', 'indefinite', 'zero_cross', 'bad_length'):
            values = covariance()
            if change == 'nan':
                values[35] = math.nan
            elif change == 'negative':
                values[35] = -.0001
            elif change == 'asymmetric':
                values[1] = .00001
            elif change == 'indefinite':
                values[1] = values[6] = .0002
            elif change == 'zero_cross':
                values[2] = values[12] = 1e-13
            else:
                values.pop()
            with self.subTest(change=change), self.assertRaises(ValueError):
                contract.covariance_matrix(values)

    def test_large_unused_axis_cannot_hide_invalid_planar_block(self):
        values = covariance()
        values[14] = 1e30
        values[1] = values[6] = .0002
        with self.assertRaises(ValueError):
            contract.covariance_matrix(values)

    def test_indefinite_nonplanar_block_is_rejected(self):
        values = covariance()
        values[21] = values[28] = .0001  # roll and pitch variances
        values[22] = values[27] = .0002  # invalid roll/pitch correlation
        with self.assertRaises(ValueError):
            contract.messages_to_observation(*pair(variance=values))


class ValidationTest(unittest.TestCase):
    def test_valid_input_preserves_covariance_without_mutation(self):
        original = observation()
        saved = copy.deepcopy(original)
        result = validate(original)
        self.assertEqual(result['covariance'], tuple(covariance()))
        self.assertAlmostEqual(result['source_age'], .1)
        self.assertEqual(original, saved)

    def test_source_and_original_received_age_boundaries_are_preserved(self):
        validate(now_stamp=10.25, received_age=.5)
        validate(now_stamp=9.9, received_age=0.)
        for change in ({'now_stamp': 10.251}, {'now_stamp': 9.899},
                       {'received_age': .501}, {'received_age': -.001},
                       {'received_age': math.nan}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(**change)

    def test_reception_now_cannot_hide_old_source_stamp(self):
        with self.assertRaises(ValueError):
            validate(observation(stamp_ns=6_000_000_000), received_age=0.)

    def test_source_frame_mode_station_and_identity_must_match(self):
        for key, value in (('mode', 'vision'), ('publisher', 'station_camera'),
                           ('station_id', 'other_station'), ('frame_id', 'map'),
                           ('idealized_truth_derived', False), ('scene_sha256', 'c'*64),
                           ('manifest_sha256', 'c'*64), ('episode_id', NEXT_EPISODE)):
            obs = observation()
            obs[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(obs)

    def test_previous_episode_and_reset_floor_are_rejected(self):
        current = dict(IDENTITY, episode_id=NEXT_EPISODE, reset_stamp=10.)
        with self.assertRaises(ValueError):
            validate(identity=current)
        obs = observation()
        obs['episode_id'] = NEXT_EPISODE
        with self.assertRaises(ValueError):
            validate(obs, identity=current)
        obs = observation(stamp_ns=10_100_000_000)
        obs['episode_id'] = NEXT_EPISODE
        self.assertEqual(validate(obs, identity=current)['episode_id'], NEXT_EPISODE)

    def test_sequence_and_source_time_must_advance_together(self):
        accepted = validate()
        for stamp, sequence in ((10_000_000_000, 1), (10_100_000_000, 1),
                                (9_900_000_000, 2), (10_000_000_000, 2)):
            with self.subTest(stamp=stamp, sequence=sequence), self.assertRaises(ValueError):
                validate(observation(stamp_ns=stamp, sequence=sequence), last_accepted=accepted)
        self.assertEqual(validate(observation(stamp_ns=10_100_000_000, sequence=2),
                                  last_accepted=accepted)['sequence'], 2)

    def test_late_loss_cannot_override_a_newer_successful_detection(self):
        accepted = validate(observation(stamp_ns=10_100_000_000, sequence=2))
        for stamp, sequence in ((10_000_000_000, 1), (10_100_000_000, 3),
                                (10_150_000_000, 2)):
            loss = observation(stamp_ns=stamp, sequence=sequence, detected=False)
            with self.subTest(stamp=stamp, sequence=sequence), self.assertRaises(ValueError):
                validate(loss, last_accepted=accepted)
        loss = observation(stamp_ns=10_150_000_000, sequence=3, detected=False)
        self.assertFalse(validate(loss, last_accepted=accepted)['detected'])

    def test_capture_range_is_checked_after_pose_parse(self):
        with self.assertRaises(ValueError):
            validate(observation(relative=(1.001, 0., 0.)))
        validate(observation(relative=(1., 0., 0.)))

    def test_legal_loss_report_returns_no_pose_without_confidence_success(self):
        _, diagnostics = pair(detected=False)
        result = validate(contract.messages_to_observation(None, diagnostics))
        self.assertFalse(result['detected'])
        self.assertEqual(result['confidence'], 0.)
        self.assertIsNone(result['relative'])
        with self.assertRaises(ValueError):
            validate(dict(result, relative=(0., 0., 0.)))

    def test_authentic_loss_still_requires_freshness_and_scene_identity(self):
        obs = observation(detected=False)
        with self.assertRaises(ValueError):
            validate(obs, received_age=.6)
        with self.assertRaises(ValueError):
            validate(dict(obs, episode_id=NEXT_EPISODE))

    def test_vision_cannot_claim_truth_and_low_confidence_is_rejected(self):
        config = {'mode': 'vision', 'publisher': 'station_camera',
                  'min_confidence': .8, 'max_covariance': [.0002]*3}
        obs = observation(mode='vision', publisher='station_camera')
        self.assertFalse(validate(obs, config=config)['idealized_truth_derived'])
        for change in ({'idealized_truth_derived': True}, {'confidence': .79},
                       {'publisher': 'cooperation_physics'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(dict(obs, **change), config=config)

    def test_covariance_limit_rejects_without_clamping(self):
        with self.assertRaises(ValueError):
            validate(observation(variance=covariance((.0001, .000101, .0001))))
        config = {'mode': 'perturbed', 'max_covariance': [.0002, .0005, .001],
                  'noise_std': [.01, .02, .03]}
        result = validate(observation(mode='perturbed', variance=covariance((.0002, .0005, .001))),
                          config=config)
        self.assertEqual(result['covariance'], tuple(covariance((.0002, .0005, .001))))

    def test_stamp_integer_and_boolean_fields_are_not_coerced(self):
        for key, value in (('stamp_ns', True), ('sequence', True),
                           ('detected', 1), ('schema', True), ('stamp', math.inf)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(dict(observation(), **{key: value}))


class MapCovarianceTest(unittest.TestCase):
    def test_relative_yaw_uncertainty_increases_map_position_variance(self):
        mapped = contract.map_covariance((1., 0., 0.), (0., 0., 0.),
                                         covariance((.01, .02, .03)))
        self.assertAlmostEqual(mapped[0], .01)
        self.assertAlmostEqual(mapped[7], .05)
        self.assertAlmostEqual(mapped[35], .03)
        self.assertAlmostEqual(mapped[11], -.03)
        self.assertEqual(mapped[14], 0.)

    def test_map_propagation_matches_independent_numeric_derivative(self):
        relative, station = (.4, -.2, .8), (2., -3., 1.1)
        source = covariance((.0002, .0003, .0007))
        source[1] = source[6] = .00005
        source[5] = source[30] = -.00003
        source[11] = source[31] = .00004
        mapped = contract.map_covariance(relative, station, source)
        step = 1e-5
        jacobian = [[0.]*3 for _ in range(3)]
        for axis in range(3):
            before, after = list(relative), list(relative)
            before[axis] -= step
            after[axis] += step
            first, last = station_robot_pose(before, station), station_robot_pose(after, station)
            for row, name in enumerate(('x', 'y', 'yaw')):
                jacobian[row][axis] = (last[name]-first[name])/(2*step)
        plane = [[source[row*6+column] for column in contract.PLANE_AXES]
                 for row in contract.PLANE_AXES]
        for row, axis in enumerate(contract.PLANE_AXES):
            for column, other in enumerate(contract.PLANE_AXES):
                expected = sum(jacobian[row][i]*plane[i][j]*jacobian[column][j]
                               for i in range(3) for j in range(3))
                self.assertAlmostEqual(mapped[axis*6+other], expected, places=11)
        contract.covariance_matrix(mapped)

    def test_bad_relative_or_source_covariance_cannot_reach_amcl(self):
        with self.assertRaises(ValueError):
            contract.map_covariance((math.nan, 0., 0.), (0., 0., 0.), covariance())
        source = covariance()
        source[1] = source[6] = .1
        with self.assertRaises(ValueError):
            contract.map_covariance((0., 0., 0.), (0., 0., 0.), source)


if __name__ == '__main__':
    unittest.main()
