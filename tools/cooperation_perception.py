"""Pure station-observation contract, independent of ROS imports and truth.

The ROS adapters pair standard pose and diagnostic messages by their exact
source stamp. This module validates that pair without consulting physics.
Graph ownership remains the adapter's responsibility.
"""
import math
import re
import uuid


POSE_TOPIC = '/cooperation/station_pose'
DETECTION_TOPIC = '/cooperation/station_detection'
DIAGNOSTIC_NAME = 'station_detection'
PLANE_AXES = (0, 1, 5)
METADATA_FIELDS = frozenset({
    'schema', 'publisher', 'mode', 'station_id', 'scene_sha256',
    'manifest_sha256', 'episode_id', 'sequence', 'detected', 'confidence',
    'reason', 'idealized_truth_derived',
})
_COMMON_CONFIG = frozenset({
    'schema', 'mode', 'station_id', 'publisher', 'frame_id', 'range_limit_m',
    'min_confidence', 'max_covariance',
})
_PERTURBED_CONFIG = frozenset({
    'noise_std', 'bias', 'dropout_probability', 'seed', 'occlusion_windows',
})


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f'{label} must be a finite number')
    try:
        result = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError(f'{label} must be a finite number') from error
    if not math.isfinite(result):
        raise ValueError(f'{label} must be a finite number')
    return result


def _vector(value, length, label):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f'{label} requires {length} finite values')
    return tuple(_number(item, label) for item in value)


def _name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError(f'{label} must be an explicit ROS name')
    return value


def normalize_config(config=None):
    """Declare one observation mode; vision never adopts a truth publisher.

    Position/yaw covariance limits are variances, ordered x, y, yaw.
    Perturbations and visibility windows are episode-relative declarations.
    This function neither schedules faults nor installs a vision producer.
    """
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError('station perception config must be an object')
    mode = config.get('mode', 'ideal')
    if mode not in ('ideal', 'perturbed', 'vision'):
        raise ValueError('station perception mode must be ideal, perturbed or vision')
    allowed = _COMMON_CONFIG | (_PERTURBED_CONFIG if mode == 'perturbed' else frozenset())
    if set(config) - allowed:
        raise ValueError('unknown station perception config fields: ' + ', '.join(sorted(set(config)-allowed)))
    schema = config.get('schema', 1)
    if type(schema) is not int or schema != 1:
        raise ValueError('station perception schema must be 1')
    if mode == 'vision' and not {'publisher', 'min_confidence', 'max_covariance'} <= set(config):
        raise ValueError('vision requires explicit publisher, min_confidence and max_covariance')
    if mode == 'perturbed' and 'max_covariance' not in config:
        raise ValueError('perturbed mode requires declared max_covariance')
    publisher = _name(config.get('publisher', 'cooperation_physics'), 'publisher')
    if ((mode == 'vision' and publisher == 'cooperation_physics')
            or (mode != 'vision' and publisher != 'cooperation_physics')):
        raise ValueError('observation mode and publisher are inconsistent')
    station = _name(config.get('station_id', 'so101_station'), 'station_id')
    frame = config.get('frame_id', 'base_footprint')
    if frame != 'base_footprint':
        raise ValueError('station observations require base_footprint')
    distance = _number(config.get('range_limit_m', 1.), 'range_limit_m')
    if not 0 < distance <= 1.:
        raise ValueError('range_limit_m must remain within the original 1 m capture range')
    confidence = _number(config.get('min_confidence', 1.), 'min_confidence')
    if not 0 <= confidence <= 1:
        raise ValueError('min_confidence must be between 0 and 1')
    maximum = _vector(config.get('max_covariance', [.0001]*3), 3, 'max_covariance')
    if any(value <= 0 for value in maximum):
        raise ValueError('max_covariance entries must be positive variances')
    if mode == 'ideal' and (confidence != 1. or maximum != (.0001,)*3):
        raise ValueError('ideal mode preserves confidence 1 and covariance .0001')
    result = {'schema': 1, 'mode': mode, 'station_id': station, 'publisher': publisher,
              'frame_id': frame, 'range_limit_m': distance,
              'min_confidence': confidence, 'max_covariance': list(maximum)}
    if mode == 'perturbed':
        noise = _vector(config.get('noise_std', [0.]*3), 3, 'noise_std')
        bias = _vector(config.get('bias', [0.]*3), 3, 'bias')
        if any(value < 0 for value in noise):
            raise ValueError('noise_std must be nonnegative')
        if any(.0001 + value*value > limit+1e-12 for value, limit in zip(noise, maximum)):
            raise ValueError('max_covariance must cover ideal variance plus declared noise variance')
        dropout = _number(config.get('dropout_probability', 0.), 'dropout_probability')
        if not 0 <= dropout <= 1:
            raise ValueError('dropout_probability must be between 0 and 1')
        seed = config.get('seed', 0)
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError('seed must be an unsigned 32-bit integer')
        windows = config.get('occlusion_windows', [])
        if not isinstance(windows, list) or len(windows) > 64:
            raise ValueError('occlusion_windows requires at most 64 ordered intervals')
        normalized, end = [], 0.
        for interval in windows:
            start, stop = _vector(interval, 2, 'occlusion window')
            if not 0 <= start < stop or start < end:
                raise ValueError('occlusion windows must be nonnegative, ordered and disjoint')
            normalized.append([start, stop])
            end = stop
        result.update(noise_std=list(noise), bias=list(bias), dropout_probability=dropout,
                      seed=seed, occlusion_windows=normalized)
    return result


def _stamp(header):
    try:
        sec, nano, frame = header.stamp.sec, header.stamp.nanosec, header.frame_id
    except AttributeError as error:
        raise ValueError('observation header is missing') from error
    if (type(sec) is not int or type(nano) is not int or sec < 0
            or not 0 <= nano < 1_000_000_000 or sec*1_000_000_000+nano <= 0):
        raise ValueError('source stamp requires positive ROS time')
    if not isinstance(frame, str) or not frame:
        raise ValueError('observation frame is missing')
    return sec*1_000_000_000+nano, frame


def _metadata(status):
    try:
        pairs = status.values
        result = {}
        for pair in pairs:
            key, value = pair.key, pair.value
            if not isinstance(key, str) or not isinstance(value, str) or key in result:
                raise ValueError('diagnostic metadata has invalid or duplicate keys')
            result[key] = value
    except (AttributeError, TypeError) as error:
        raise ValueError('detection metadata is missing') from error
    if set(result) != METADATA_FIELDS:
        raise ValueError('detection metadata fields do not match schema 1')
    if result['schema'] != '1':
        raise ValueError('detection metadata schema must be 1')
    if result['mode'] not in ('ideal', 'perturbed', 'vision'):
        raise ValueError('invalid detection mode')
    for key in ('publisher', 'station_id'):
        _name(result[key], key)
    for key in ('scene_sha256', 'manifest_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', result[key]):
            raise ValueError(f'{key} must be a lowercase SHA256')
    try:
        if str(uuid.UUID(result['episode_id'])) != result['episode_id']:
            raise ValueError('episode_id must be a canonical UUID')
    except (ValueError, AttributeError) as error:
        raise ValueError('episode_id must be a canonical UUID') from error
    if not re.fullmatch(r'0|[1-9][0-9]*', result['sequence']):
        raise ValueError('sequence must be an unsigned decimal integer')
    result['sequence'] = int(result['sequence'])
    for key in ('detected', 'idealized_truth_derived'):
        if result[key] not in ('true', 'false'):
            raise ValueError(f'{key} requires true or false')
        result[key] = result[key] == 'true'
    try:
        confidence = float(result['confidence'])
    except ValueError as error:
        raise ValueError('confidence must be finite') from error
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError('confidence must be between 0 and 1')
    result['confidence'] = confidence
    if len(result['reason']) > 256 or (not result['detected'] and not result['reason'].strip()):
        raise ValueError('failed detection must have a bounded reason')
    return result


def covariance_matrix(covariance):
    """Validate all six axes, including zero-variance axes and cross terms."""
    if isinstance(covariance, (str, bytes)):
        raise ValueError('covariance requires 36 finite values')
    try:
        values = tuple(covariance)
    except TypeError as error:
        raise ValueError('covariance requires 36 finite values') from error
    values = _vector(values, 36, 'covariance')
    matrix = [list(values[row*6:row*6+6]) for row in range(6)]
    for row in range(6):
        if matrix[row][row] < 0:
            raise ValueError('covariance diagonal must be nonnegative')
        for column in range(row):
            tolerance = max(1e-12, max(abs(matrix[row][column]), abs(matrix[column][row]))*1e-10)
            if abs(matrix[row][column]-matrix[column][row]) > tolerance:
                raise ValueError('covariance must be symmetric')
    # Scale to a correlation matrix first. Large unused-axis variance must not
    # hide an indefinite planar block or correlations with a zero-variance axis.
    roots = [math.sqrt(matrix[index][index]) for index in range(6)]
    remaining = [[0.]*6 for _ in range(6)]
    for row in range(6):
        for column in range(6):
            if roots[row] == 0 or roots[column] == 0:
                if matrix[row][column] != 0:
                    raise ValueError('zero-variance axes cannot have covariance cross terms')
            else:
                remaining[row][column] = matrix[row][column]/roots[row]/roots[column]
                if not math.isfinite(remaining[row][column]):
                    raise ValueError('covariance must be positive semidefinite')
    # Pivoted LDL handles valid semidefinite matrices with unused axes.
    tolerance = 1e-10
    for index in range(6):
        pivot = max(range(index, 6), key=lambda row: remaining[row][row])
        remaining[index], remaining[pivot] = remaining[pivot], remaining[index]
        for row in remaining:
            row[index], row[pivot] = row[pivot], row[index]
        diagonal = remaining[index][index]
        if diagonal < -tolerance:
            raise ValueError('covariance must be positive semidefinite')
        if diagonal <= tolerance:
            if any(abs(remaining[row][column]) > tolerance
                   for row in range(index, 6) for column in range(index, 6)):
                raise ValueError('covariance must be positive semidefinite')
            break
        for row in range(index+1, 6):
            for column in range(index+1, 6):
                remaining[row][column] -= remaining[row][index]*remaining[index][column]/diagonal
    return matrix


def messages_to_observation(pose, diagnostics):
    """Parse one exact-stamp pair using message attributes, without ROS types.

    A missing pose is allowed only for an explicit failed detection. It never
    becomes a zero-valued station measurement.
    """
    if diagnostics is None:
        raise ValueError('detection diagnostics are missing')
    try:
        stamp_ns, frame = _stamp(diagnostics.header)
        if len(diagnostics.status) != 1:
            raise ValueError('requires one station detection diagnostic')
        status = diagnostics.status[0]
        metadata = _metadata(status)
        if status.name != DIAGNOSTIC_NAME or status.hardware_id != metadata['station_id']:
            raise ValueError('diagnostic station identity is inconsistent')
        level = status.level
        # Jazzy's generated ROS byte field is one-byte bytes, not uint8 int.
        if type(level) is bytes and len(level) == 1:
            level = level[0]
        if type(level) is not int or level not in (0, 1, 2):
            raise ValueError('diagnostic level must be OK, WARN or ERROR')
        if (level == 0) != metadata['detected']:
            raise ValueError('diagnostic level and detected flag disagree')
    except AttributeError as error:
        raise ValueError('station diagnostic is malformed') from error
    observation = {**metadata, 'schema': 1, 'frame_id': frame,
                   'stamp_ns': stamp_ns, 'stamp': stamp_ns*1e-9,
                   'relative': None, 'covariance': None}
    if pose is None:
        if metadata['detected']:
            raise ValueError('successful detection requires a paired pose')
        return observation
    try:
        pose_stamp, pose_frame = _stamp(pose.header)
        if (pose_stamp, pose_frame) != (stamp_ns, frame):
            raise ValueError('pose and detection must share their exact header stamp and frame')
        position, rotation = pose.pose.pose.position, pose.pose.pose.orientation
        xyz = tuple(_number(getattr(position, axis), 'station position') for axis in ('x', 'y', 'z'))
        w, x, y, z = tuple(_number(getattr(rotation, axis), 'station quaternion')
                           for axis in ('w', 'x', 'y', 'z'))
        norm = math.sqrt(w*w+x*x+y*y+z*z)
        if abs(norm-1.) > 1e-3:
            raise ValueError('station quaternion must be normalized')
        w, x, y, z = (item/norm for item in (w, x, y, z))
        yaw = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
        covariance = tuple(pose.pose.covariance)
        covariance_matrix(covariance)
    except (AttributeError, TypeError) as error:
        raise ValueError('station pose is malformed') from error
    if metadata['detected']:
        observation.update(relative=(xyz[0], xyz[1], yaw), covariance=covariance)
    return observation


def validate_observation(obs, config, identity, now_stamp, received_age, last_accepted=None):
    """Validate identity, freshness and monotonicity, returning a copied record.

    Invalid input raises ValueError. A fresh, authentic failed detection returns
    detected=False. Consumers decide whether to wait, cancel or clean up.
    """
    config = normalize_config(config)
    if not isinstance(obs, dict) or not isinstance(identity, dict):
        raise ValueError('observation and identity must be objects')
    expected = {'schema': 1, 'mode': config['mode'], 'publisher': config['publisher'],
                'station_id': config['station_id'], 'frame_id': config['frame_id'],
                'idealized_truth_derived': config['mode'] != 'vision'}
    for key, value in expected.items():
        if type(obs.get(key)) is not type(value) or obs.get(key) != value:
            raise ValueError(f'observation {key} does not match the declared source')
    for key in ('scene_sha256', 'manifest_sha256', 'episode_id'):
        if not isinstance(identity.get(key), str) or obs.get(key) != identity[key]:
            raise ValueError(f'observation {key} does not match the current scene episode')
    stamp = _number(obs.get('stamp'), 'source stamp')
    stamp_ns = obs.get('stamp_ns')
    if (type(stamp_ns) is not int or stamp_ns <= 0
            or abs(stamp-stamp_ns*1e-9) > 1e-12):
        raise ValueError('source stamp and stamp_ns disagree')
    now = _number(now_stamp, 'current source time')
    age = _number(received_age, 'original received age')
    if not 0 <= age <= .5:
        raise ValueError('station observation original reception is stale')
    if not -.1 <= now-stamp <= .25:
        raise ValueError('station observation source time is stale or in the future')
    reset = identity.get('reset_stamp')
    if reset is not None and stamp <= _number(reset, 'episode reset stamp'):
        raise ValueError('station observation predates the current episode reset')
    sequence = obs.get('sequence')
    if type(sequence) is not int or sequence < 0:
        raise ValueError('observation sequence must be nonnegative')
    detected = obs.get('detected')
    if type(detected) is not bool:
        raise ValueError('observation detected flag must be boolean')
    confidence = _number(obs.get('confidence'), 'confidence')
    if not 0 <= confidence <= 1:
        raise ValueError('confidence must be between 0 and 1')
    if not isinstance(obs.get('reason'), str) or len(obs['reason']) > 256:
        raise ValueError('detection reason is malformed')
    if last_accepted is not None:
        if not isinstance(last_accepted, dict):
            raise ValueError('last accepted observation must be an object')
        if last_accepted.get('episode_id') == identity['episode_id']:
            previous_sequence, previous_stamp = last_accepted.get('sequence'), last_accepted.get('stamp_ns')
            if (type(previous_sequence) is not int or type(previous_stamp) is not int
                    or sequence <= previous_sequence or stamp_ns <= previous_stamp):
                raise ValueError('station sequence and source time must advance together')
    if not detected:
        if not obs['reason'].strip() or obs.get('relative') is not None or obs.get('covariance') is not None:
            raise ValueError('failed detection must contain a reason without a usable pose')
        return dict(obs, source_age=now-stamp, received_age=age)
    if confidence < config['min_confidence']:
        raise ValueError('station detection confidence is below the declared minimum')
    relative = _vector(obs.get('relative'), 3, 'relative station pose')
    if math.hypot(*relative[:2]) > config['range_limit_m']:
        raise ValueError('station observation is outside the declared capture range')
    matrix = covariance_matrix(obs.get('covariance'))
    for axis, maximum in zip(PLANE_AXES, config['max_covariance']):
        if matrix[axis][axis] > maximum+1e-12:
            raise ValueError('station covariance exceeds the declared variance limit')
    return dict(obs, relative=relative, covariance=tuple(obs['covariance']),
                source_age=now-stamp, received_age=age)


def map_covariance(relative, station, covariance):
    """Propagate planar relative covariance through station_robot_pose.

    The station map pose is a fixed declared landmark, not an observation.
    Unused z/roll/pitch terms remain zero, as in the existing planar AMCL feed.
    """
    x, y, heading = _vector(relative, 3, 'relative station pose')
    _, _, station_heading = _vector(station, 3, 'station map pose')
    full = covariance_matrix(covariance)
    plane = [[full[row][column] for column in PLANE_AXES] for row in PLANE_AXES]
    yaw = station_heading-heading
    cosine, sine = math.cos(yaw), math.sin(yaw)
    jacobian = [[-cosine, sine, -sine*x-cosine*y],
                [-sine, -cosine, cosine*x-sine*y], [0., 0., -1.]]
    result = [0.]*36
    for row, target_row in enumerate(PLANE_AXES):
        for column, target_column in enumerate(PLANE_AXES):
            result[target_row*6+target_column] = sum(
                jacobian[row][i]*plane[i][j]*jacobian[column][j]
                for i in range(3) for j in range(3))
    covariance_matrix(result)
    return tuple(result)
