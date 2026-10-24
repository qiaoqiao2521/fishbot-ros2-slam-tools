"""Pure named-delivery predicates and finite inventory bookkeeping.

These helpers neither write a Physics frame nor infer task success. The owner
advances inventory only after its existing physical evidence gates pass.
"""
import copy
import math

from cooperation_core import Rejected, finite_number, finite_vector, quaternion, task_delivery_pose


_DELIVERY_KEYS = {'cargo_id', 'pickup_arm_id', 'unload_station_id'}
_PAD_NAMES = ('pad_gripper', 'pad_moving_jaw')


def _identity(value, label):
    if not isinstance(value, str) or not value.strip():
        raise Rejected(f'{label} must be a nonempty string')
    return value


def normalize_delivery(value):
    """Return the exact three named delivery fields, or reject this task."""
    if not isinstance(value, dict) or set(value) != _DELIVERY_KEYS:
        raise Rejected('delivery must contain cargo_id, pickup_arm_id and unload_station_id')
    return {key: _identity(value[key], key) for key in sorted(_DELIVERY_KEYS)}


def validate_delivery(manifest, binding, delivery_pose):
    """Resolve a configured destination and return binding plus unload_arm_id."""
    result = normalize_delivery(binding)
    try:
        entities = manifest['business_entities']
        if result['cargo_id'] not in entities['cargo'] or result['pickup_arm_id'] not in entities['arms']:
            raise Rejected('Unknown delivery cargo or pickup arm')
        station = entities['unload_stations'][result['unload_station_id']]
        if len(entities['cargo']) > 1 and not station.get('cargo_shelf_slots'):
            raise Rejected('Continuous delivery requires distinct configured shelf cells')
        placement_slot(manifest, result['unload_station_id'], result['cargo_id'])
        unload_arm = station['arm_id']
        if unload_arm not in entities['arms']:
            raise Rejected('Unknown unload arm')
        goal = task_delivery_pose({'delivery_pose': delivery_pose})
        configured = task_delivery_pose({'delivery_pose': station['delivery_pose']})
        angle = math.atan2(math.sin(goal['yaw']-configured['yaw']),
                           math.cos(goal['yaw']-configured['yaw']))
        if (abs(goal['x']-configured['x']) > 1e-9 or abs(goal['y']-configured['y']) > 1e-9
                or abs(angle) > 1e-9):
            raise Rejected('Delivery goal does not match the configured unload station')
        result['unload_arm_id'] = _identity(unload_arm, 'unload_arm_id')
    except (KeyError, TypeError) as error:
        raise Rejected('Unknown or incomplete delivery entity binding') from error
    return result


def _rotation(value):
    w, x, y, z = quaternion(value, 'quaternion_wxyz')
    return [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]


def _local(rotation, vector):
    return [sum(rotation[k][i]*vector[k] for k in range(3)) for i in range(3)]


def _contact(record):
    count = record['contact_count']
    force = finite_number(record['normal_force_n'], 'contact.normal_force_n')
    if type(count) is not int or count < 0 or force < 0:
        raise ValueError('Contact counts and normal forces must be nonnegative')
    return count, force


def placement_slot(manifest, station_id, cargo_id):
    """Resolve a physical shelf cell; legacy fixtures retain the whole shelf."""
    station = manifest['business_entities']['unload_stations'][station_id]
    slots = station.get('cargo_shelf_slots')
    slot = slots[cargo_id] if slots is not None else {
        'center_xy_m': station['shelf_xy_in_station_m'], 'half_size_xy_m': [.058, .058]}
    center = finite_vector(slot['center_xy_m'], 2, 'shelf slot center')
    half = finite_vector(slot['half_size_xy_m'], 2, 'shelf slot half size')
    shelf = finite_vector(station['shelf_xy_in_station_m'], 2, 'shelf center')
    if any(h <= 0 or abs(x-s)+h > .058+1e-12 for x,s,h in zip(center,shelf,half)):
        raise Rejected('Shelf slot must fit inside the original shelf')
    return {'center_xy_m': center, 'half_size_xy_m': half}


def observe(raw, manifest, cargo_id, arm_id):
    """Project selected measured entities into an independent predicate view.

    This is deliberately not a full Physics frame: qpos and source identity
    remain exclusively in raw. Missing selections or malformed measurements
    raise ValueError; an absent pad contact contributes zero force.
    """
    try:
        description = manifest['business_entities']
        if cargo_id not in description['cargo'] or arm_id not in description['arms']:
            raise ValueError('Unknown selected cargo or arm')
        measured = raw['business_entities']
        arm, cargo = measured['arms'][arm_id], measured['cargo'][cargo_id]
        q = finite_vector(arm['qpos6'], 6, 'selected arm qpos6')
        velocity = finite_vector(arm['qvel6'], 6, 'selected arm qvel6')
        position = finite_vector(cargo['position'], 3, 'selected cargo position')
        orientation = quaternion(cargo['quaternion_wxyz'], 'selected cargo quaternion')
        cargo_velocity = finite_vector(cargo['velocity_world_angular_linear'], 6, 'selected cargo velocity')
        tray = copy.deepcopy(raw['tray'])
        tray_position = finite_vector(tray['position'], 3, 'tray position')
        rotation = _rotation(tray['quaternion_wxyz'])
        tray_velocity = finite_vector(tray['velocity_world_angular_linear'], 6, 'tray velocity')
        offset = [a-b for a, b in zip(position, tray_position)]
        omega = tray_velocity[:3]
        rotational = [omega[1]*offset[2]-omega[2]*offset[1],
                      omega[2]*offset[0]-omega[0]*offset[2],
                      omega[0]*offset[1]-omega[1]*offset[0]]
        relative = [cargo_velocity[i+3]-tray_velocity[i+3]-rotational[i] for i in range(3)]
        contacts = copy.deepcopy(cargo['contacts'])
        if not all(isinstance(contacts[key], dict) for key in ('supports', 'pads', 'other_cargo')):
            raise ValueError('Selected cargo contacts must contain support, pad and cargo maps')
        for support in contacts['supports'].values():
            _contact(support)
        for pads in contacts['pads'].values():
            if not isinstance(pads, dict):
                raise ValueError('Arm pad contacts must be a map')
            for record in pads.values():
                _contact(record)
        forces = dict.fromkeys(_PAD_NAMES, 0.)
        names = description['arms'][arm_id]['pad_geoms']
        for name in names:
            canonical = name.rsplit('__', 1)[-1]
            if canonical in forces and name in contacts['pads'].get(arm_id, {}):
                forces[canonical] += _contact(contacts['pads'][arm_id][name])[1]
        count, force = _contact(contacts['supports'].get('tray', {'contact_count': 0, 'normal_force_n': 0.}))
        if type(raw['car_hold']) is not bool:
            raise ValueError('car_hold must be a boolean')
        return {'stamp': finite_number(raw['stamp'], 'stamp'), 'car_hold': raw['car_hold'],
                'car': copy.deepcopy(raw['car']), 'tray': tray,
                'q6': q, 'qvel6': velocity, 'cargo_id': cargo_id, 'arm_id': arm_id,
                'cargo': {'position': position, 'quaternion_wxyz': orientation,
                          'velocity_world_angular_linear': cargo_velocity,
                          'position_relative_tray': _local(rotation, offset),
                          'velocity_relative_tray': _local(rotation, relative)},
                'finger_normal_forces_n': forces, 'cargo_tray_floor_contact': count > 0,
                'cargo_tray_floor_contacts': count, 'cargo_tray_floor_normal_force_n': force,
                'entity_contacts': contacts}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Missing or malformed selected business measurement') from error


def shelf_settled(view, manifest, station_id, *, before_retreat=False):
    """Require the full rotated original box, shelf support and released rest."""
    try:
        entities = manifest['business_entities']
        station = entities['unload_stations'][station_id]
        arm = entities['arms'][station['arm_id']]
        origin = finite_vector(arm['station_position_m'], 3, 'station position')
        yaw = finite_number(arm['station_yaw_rad'], 'station yaw')
        c, s = math.cos(yaw), math.sin(yaw)
        axes = [[c, -s, 0.], [s, c, 0.], [0., 0., 1.]]
        local = _local(axes, [a-b for a, b in zip(
            finite_vector(view['cargo']['position'], 3, 'cargo position'), origin)])
        shelf = finite_vector(station['shelf_xy_in_station_m'], 2, 'shelf center')
        slot = placement_slot(manifest, station_id, view['cargo_id'])
        rotation = _rotation(view['cargo']['quaternion_wxyz'])
        extent = [sum(abs(sum(axes[k][i]*rotation[k][j] for k in range(3)))*half
                      for j, half in enumerate((.009, .009, .008))) for i in range(2)]
        count, force = _contact(view['entity_contacts']['supports'].get(
            station_id, {'contact_count': 0, 'normal_force_n': 0.}))
        pad_forces = [_contact(record)[1] for arm_id, pads in view['entity_contacts']['pads'].items()
                      for name, record in pads.items()
                      if not (before_retreat and arm_id == view['arm_id']
                              and name.rsplit('__', 1)[-1] == 'pad_gripper')]
        velocity = finite_vector(view['cargo']['velocity_world_angular_linear'], 6, 'cargo velocity')
        return (all(abs(local[i]-shelf[i])+extent[i] <= .058 for i in range(2))
                and all(abs(local[i]-slot['center_xy_m'][i])+extent[i]
                        <= slot['half_size_xy_m'][i] for i in range(2))
                and count > 0 and force > 0 and all(force < .02 for force in pad_forces)
                and math.sqrt(sum(v*v for v in velocity[3:])) < .002
                and (not before_retreat or finite_vector(view['q6'],6,'release q6')[5] > .45))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def all_quiet(raw):
    """Check every optional named entity; legacy frames retain their own gate."""
    if 'business_entities' not in raw:
        return True
    try:
        entities = raw['business_entities']
        return (all(math.sqrt(sum(v*v for v in finite_vector(arm['qvel6'], 6, 'arm velocity'))) < .05
                    for arm in entities['arms'].values())
                and all(math.sqrt(sum(v*v for v in finite_vector(
                    cargo['velocity_world_angular_linear'], 6, 'cargo velocity')[3:])) < .03
                    for cargo in entities['cargo'].values()))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def new_inventory(manifest, world_id, episode_id):
    """Create available stock once for this world/episode, without physical inference."""
    cargo = manifest['business_entities']['cargo']
    for field in ('body', 'free_joint', 'geom'):
        names = [record[field] for record in cargo.values() if field in record]
        if len(names) != len(set(names)):
            raise Rejected('Cargo IDs must not alias the same physical entity')
    return {'world_id': _identity(world_id, 'world_id'),
            'episode_id': _identity(episode_id, 'episode_id'),
            'cargo': {cargo_id: {'state': 'available', 'task_id': None, 'binding': None, 'evidence': None}
                      for cargo_id in cargo}}


def reserve(inventory, binding, task_id):
    """Reserve one cargo in place; return a detached record and keep retries idempotent."""
    if not isinstance(binding, dict) or set(binding) not in (_DELIVERY_KEYS, _DELIVERY_KEYS | {'unload_arm_id'}):
        raise Rejected('Invalid inventory delivery binding')
    normalized = normalize_delivery({key: binding[key] for key in _DELIVERY_KEYS})
    if 'unload_arm_id' in binding:
        normalized['unload_arm_id'] = _identity(binding['unload_arm_id'], 'unload_arm_id')
    _identity(task_id, 'task_id')
    cargo_id = normalized['cargo_id']
    record = inventory['cargo'].get(cargo_id)
    if record is None:
        raise Rejected('Unknown inventory cargo')
    if any(other != cargo_id and item['task_id'] == task_id for other, item in inventory['cargo'].items()):
        raise Rejected('Task already refers to another cargo', 409)
    if record['state'] != 'available':
        if (record['state'] in ('reserved', 'on_tray') and record['task_id'] == task_id
                and record['binding'] == normalized):
            return copy.deepcopy(record)
        raise Rejected('Cargo is unavailable or already delivered', 409)
    record.update(state='reserved', task_id=task_id, binding=normalized, evidence=None)
    return copy.deepcopy(record)


def advance(inventory, cargo_id, task_id, state, evidence=None):
    """Apply one owner-approved transition; never infer delivery or restore stock."""
    _identity(cargo_id, 'cargo_id')
    _identity(task_id, 'task_id')
    record = inventory['cargo'].get(cargo_id)
    if record is None:
        raise Rejected('Unknown inventory cargo')
    if record['task_id'] != task_id:
        raise Rejected('Cargo belongs to another task', 409)
    if state not in ('reserved', 'on_tray', 'delivered', 'unknown'):
        raise Rejected('Unknown inventory transition')
    if record['state'] == state:
        return copy.deepcopy(record)
    if (record['state'], state) not in (('reserved', 'on_tray'), ('on_tray', 'delivered'),
                                       ('reserved', 'unknown'), ('on_tray', 'unknown')):
        raise Rejected('Invalid inventory transition', 409)
    saved_evidence = copy.deepcopy(evidence)
    record.update(state=state, evidence=saved_evidence)
    return copy.deepcopy(record)
