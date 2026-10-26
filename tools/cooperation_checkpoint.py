"""R1 native state checkpoints and R2 initialization for the existing Physics.

Only the physics owner calls capture/restore at a step boundary. The IO executor
handles copies, never MjData. JSON is editable; compatibility uses actual model
dimensions, names and topology, not a content hash or a plan revision lock.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import dataclasses
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
import uuid

SCHEMA = 'fishbot.physics-checkpoint.v1'
REQUEST_TOPIC = '/cooperation/checkpoint_request'
RESULT_TOPIC = '/cooperation/checkpoint_result'
STRUCTURE = ('body_parentid', 'body_jntadr', 'body_jntnum', 'jnt_type',
             'jnt_qposadr', 'jnt_dofadr', 'geom_type', 'geom_bodyid',
             'geom_dataid', 'mesh_vert', 'mesh_face', 'hfield_data',
             'body_mass', 'body_inertia', 'body_ipos', 'body_iquat',
             'dof_armature', 'geom_condim', 'geom_solmix', 'jnt_range',
             'jnt_axis', 'jnt_pos', 'actuator_trnid', 'actuator_gear',
             'actuator_dynprm', 'qpos0', 'qpos_spring')
MUTABLE = ('geom_friction', 'geom_solref', 'geom_solimp', 'geom_priority',
           'geom_contype', 'geom_conaffinity', 'geom_rgba', 'geom_pos',
           'geom_quat', 'geom_size', 'geom_margin', 'geom_gap',
           'body_pos', 'body_quat', 'dof_damping', 'dof_frictionloss',
           'actuator_gainprm', 'actuator_biasprm', 'actuator_ctrlrange',
           'actuator_forcerange')
OPTIONS = ('timestep', 'gravity', 'wind', 'density', 'viscosity', 'magnetic',
           'disableflags', 'enableflags', 'integrator', 'solver',
           'iterations', 'tolerance', 'noslip_iterations', 'noslip_tolerance')
APP_FIELDS = ('reference', 'steps', 'scan_sequence', 'state_sequence',
              'odom_linear', 'odom_angular', 'total_forbidden_steps',
              'total_forbidden_contacts', 'total_car_forbidden_steps',
              'total_car_forbidden_contacts', 'max_normal_forces',
              'episode_id', 'reset_count', 'reset_stamp', 'reset_ready',
              'native_actions_busy')
EXTERNAL = ['AMCL particles and filter history', 'EKF history',
            'Nav2 actions/controllers and DDS queues', 'wall timers',
            'render/pending sensor worker frames', 'OMPL query process RNG']


def prepare_ros_branch(checkpoint_path, output):
    """Prepare a fresh ROS branch from the parent's recorded localization.

    The physical checkpoint stays separate from AMCL initialization. No truth
    pose is converted into a localization measurement by this adapter.
    """
    import yaml
    checkpoint_path, output = Path(checkpoint_path).resolve(), Path(output).resolve()
    value = read_checkpoint(checkpoint_path)
    pose = value.get('context', {}).get('localized_pose')
    if not isinstance(pose, dict) or any(type(pose.get(k)) not in (int,float)
            or not math.isfinite(pose[k]) for k in ('x','y','yaw')):
        raise ValueError('R2 case needs the parent recorded map->base TF; truth is not a fallback')
    manifest = copy.deepcopy(value['source']['manifest'])
    try:
        parameters = yaml.safe_load(Path(manifest['nav2_yaml']).read_text())
        amcl = parameters['amcl']['ros__parameters']
    except (KeyError,OSError,TypeError,yaml.YAMLError) as error:
        raise ValueError('R2 case has no readable parent AMCL configuration: '+str(error)) from error
    amcl['set_initial_pose'] = True
    amcl['initial_pose'] = {**pose, 'z':0.}
    warmup = {'nomotion_updates':3}
    diagonal = [amcl.get(k) for k in ('initial_cov_xx','initial_cov_yy','initial_cov_aa')]
    if all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in diagonal):
        covariance = [0.]*36
        for index, number in zip((0,7,35),diagonal):covariance[index]=float(number)
        warmup['initial_pose'] = {'mean':copy.deepcopy(pose),'covariance':covariance,
                                 'mean_source':'parent_map_to_base_TF',
                                 'covariance_source':'branch_configuration_not_restored_filter'}
    else:
        warmup['initialization_missing_reason'] = 'branch covariance is unknown; startup mean only'
        logging.warning(warmup['initialization_missing_reason'])
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    params_path = output/'branch-nav2.yaml'
    params_path.write_text(yaml.safe_dump(parameters,sort_keys=False))
    os.chmod(params_path,0o600)
    manifest.update(nav2_yaml=str(params_path),restore_checkpoint=str(checkpoint_path),
                    capture_before_delivery=False,checkpoint_directory=str(output/'checkpoints'),
                    checkpoint_warmup=warmup,
                    checkpoint_parent={'snapshot_id':value['snapshot_id'],
                        'world_session_id':value['world_session_id'],
                        'episode_id':value['application']['episode_id'],
                        'localization_source':value['context'].get('localization_source'),
                        'localized_pose':copy.deepcopy(pose),
                        'parent_localization_covariance':value['context'].get('localization_covariance'),
                        'initial_covariance_is_branch_configuration':True,
                        'branch_initial_covariance':{k:amcl.get(k) for k in
                            ('initial_cov_xx','initial_cov_yy','initial_cov_aa')},
                        'external_components_restored':False,
                        'warmup':'native SetInitialPose prior when configured, held world and 3 fresh AMCL frames'})
    _write_json(output/'manifest.json',manifest,64*1024*1024)
    return manifest


def request(payload):
    if not isinstance(payload, dict) or payload.get('action', 'capture') != 'capture':
        raise ValueError('live checkpoint interface supports capture only; restore uses a fresh branch')
    identity = {key: str(uuid.UUID(payload[key])) for key in ('request_id', 'episode_id')}
    issued = payload.get('issued_at')
    if isinstance(issued, bool) or not isinstance(issued, (int, float)) or not math.isfinite(issued):
        raise ValueError('checkpoint request needs finite issued_at')
    context = payload.get('context', {})
    if not isinstance(context, dict):
        logging.warning('Checkpoint context is not an object; continuing without optional context')
        context = {}
    return {**identity, 'issued_at': float(issued), 'action': 'capture', 'context': context}


def receipt(request, *, message='', **values):
    return {'request_id': request['request_id'], 'episode_id': request['episode_id'],
            'status': 'succeeded' if values.get('snapshot_id') else 'failed',
            'message': str(message), **values}


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if hasattr(value, 'tolist'):
        return plain(value.tolist())
    return value


def tuples(value):
    return tuple(tuples(item) for item in value) if isinstance(value, list) else value


def signature(physics):
    cached = getattr(physics, '_checkpoint_model_description', None)
    if cached is not None:
        return cached
    m = physics.model
    result = {'mujoco_version': physics.mj.__version__,
            'dimensions': {key: int(getattr(m, key)) for key in
                ('nq', 'nv', 'nu', 'na', 'nbody', 'njnt', 'ngeom', 'nmocap',
                 'neq', 'nuserdata', 'npluginstate')},
            'names': {kind: [getattr(m, kind)(i).name for i in range(count)]
                      for kind, count in [('body', m.nbody), ('joint', m.njnt),
                                          ('geom', m.ngeom), ('actuator', m.nu)]},
            'topology_and_mesh': {key: getattr(m, key).tolist() for key in STRUCTURE}}
    physics._checkpoint_model_description = result
    physics._checkpoint_model_definition_id = str(uuid.uuid4())
    return result


def _ages(values, names, now):
    result = copy.deepcopy(values)
    for name in names:
        if result.get(name) is not None:
            result[name] = now-float(result[name])
    return result


def _unage(values, names, now):
    result = copy.deepcopy(values)
    for name in names:
        if result.get(name) is not None:
            result[name] = now-float(result[name])
    return result


def capture(physics, *, context=None, now=None):
    """Copy native and owned application state, without forwarding or stepping."""
    started = time.monotonic()
    now = time.monotonic() if now is None else now
    mj, model, data = physics.mj, physics.model, physics.data
    spec = int(mj.mjtState.mjSTATE_INTEGRATION)
    vector = physics.np.empty(mj.mj_stateSize(model, spec))
    mj.mj_getState(model, data, vector, spec)
    beacon = physics.station_beacon
    truth = plain(beacon.truth)
    if truth:
        truth = _ages(truth, ['received'], now)
    app = {key: plain(getattr(physics, key)) for key in APP_FIELDS}
    additional = {name: plain(arm['reference'])
                  for name, arm in getattr(physics, 'business_arms', {}).items() if name != 'load'}
    if additional:
        app['additional_arm_references'] = additional
    forces = getattr(physics, 'physical_faults', None)
    force_context = getattr(physics, 'physical_fault_context', None)
    if forces is not None and (forces.events or force_context is not None):
        app['physical_faults'] = plain(forces.capture_state())
        app['physical_fault_context'] = plain(force_context)
    app.update(odom=plain(vars(physics.odom)),
               wheels=plain(_ages(vars(physics.wheels), ['last_received'], now)),
               docking_guard=plain(vars(physics.docking_guard)),
               reset_quiet=plain(vars(physics.reset_quiet)),
               beacon={'episode_id': beacon.episode_id, 'episode_start': beacon.episode_start,
                       'sequence': beacon.sequence, 'rng': plain(beacon.rng.getstate()),
                       'last_observation': plain(beacon.last_observation), 'truth': truth},
               observation_faults=plain(_ages(vars(physics.observation_faults),
                                               ['trigger_monotonic', 'start_wall'], now)))
    result = {'schema': SCHEMA, 'snapshot_id': str(uuid.uuid4()), 'level': 'R1',
              'world_session_id': getattr(physics, 'world_session_id', physics.episode_id),
              'captured_wall_s': time.time(), 'captured_source_s': float(data.time),
              'capture_started_monotonic_s':started,
              'model': signature(physics), 'state_spec': spec,
              'model_definition_id': physics._checkpoint_model_definition_id,
              'integration_state': vector.tolist(),
              'mutable_model': {key: getattr(model, key).tolist() for key in MUTABLE},
              'options': {key: plain(getattr(model.opt, key)) for key in OPTIONS},
              'application': app, 'context': plain(context or {}),
              'unrestored_external_components': EXTERNAL,
              'native_sensor_rng': 'no native random sensor noise configured',
              'source': {'scene_name': physics.scene.name,
                         'scene_profile': physics.identity['manifest'].get('scene_profile'),
                         'manifest': copy.deepcopy(physics.identity['manifest'])}}
    result['capture_copy_wall_s'] = time.monotonic()-started
    return result


def _restore_force_adapter(physics, value, data):
    """Validate on copied native data before restoring; no ROS admission is inferred."""
    from cooperation_physical_faults import ForceImpulse, _context
    app = value['application']
    adapter = ForceImpulse(physics.model, data)
    saved = app.get('physical_faults')
    owner = app.get('physical_fault_context')
    if saved is None:
        if owner is not None:
            raise ValueError('force owner context has no application state')
        return adapter, None
    if not isinstance(saved, dict) or not isinstance(saved.get('events'), dict):
        raise ValueError('invalid force application state')
    if owner is not None:
        owner = _context(owner)
        if (owner['world_session_id'] != value.get('world_session_id', app['episode_id'])
                or owner['episode_id'] != app['episode_id']):
            raise ValueError('force owner context differs from checkpoint world or episode')
        validation_context = owner
    else:
        events = saved['events']
        if (not events or saved.get('pending') is not None or any(
                not isinstance(record, dict) or record.get('state') not in ('completed', 'dearmed', 'overrun')
                for record in events.values())):
            raise ValueError('force application state needs its explicit active owner context')
        # A withdrawn history has no active owner. Its recorded event context
        # is used only to validate metadata; it never resumes a pulse.
        validation_context = _context(next(iter(events.values()))['event'])
    adapter.restore_state(saved, context=validation_context, wrench_included=True)
    return adapter, copy.deepcopy(owner)


def compatibility(physics, value):
    """Return per-case incompatibilities before any state is changed."""
    errors = []
    if value.get('schema') != SCHEMA:
        errors.append('unsupported checkpoint schema')
    if value.get('model') != signature(physics):
        errors.append('compiled model dimensions, names, topology or meshes differ')
    spec = int(physics.mj.mjtState.mjSTATE_INTEGRATION)
    state = value.get('integration_state', [])
    if (value.get('state_spec') != spec or not isinstance(state, list)
            or len(state) != physics.mj.mj_stateSize(physics.model, spec)
            or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in state)):
        errors.append('integration state has incompatible size, signature or values')
    for key in MUTABLE:
        try:
            array = physics.np.asarray(value['mutable_model'][key])
            if array.shape != getattr(physics.model, key).shape or not physics.np.isfinite(array).all():
                errors.append('invalid model array '+key)
        except (KeyError, TypeError, ValueError):
            errors.append('missing or malformed model array '+key)
    if not isinstance(value.get('application'), dict):
        errors.append('missing owned application state')
    elif set(APP_FIELDS)-value['application'].keys():
        errors.append('incomplete owned application state')
    else:
        app = value['application']
        try:
            from cooperation_sim import ARM_JOINTS, arm_reference
            arm_reference(ARM_JOINTS, app['reference'], physics.arm_limits)
            for name, arm in getattr(physics, 'business_arms', {}).items():
                if name != 'load':
                    limits = [tuple(physics.model.jnt_range[physics.model.joint(joint).id])
                              for joint in arm['joint_names']]
                    arm_reference(ARM_JOINTS, app['additional_arm_references'][name], limits)
            for key in ('odom', 'wheels', 'docking_guard', 'reset_quiet', 'observation_faults'):
                if not isinstance(app[key], dict):
                    raise ValueError('application '+key+' must be an object')
            import random
            random.Random().setstate(tuples(app['beacon']['rng']))
            if not set(vars(physics.odom)) <= app['odom'].keys():
                raise ValueError('incomplete encoder state')
            if 'physical_faults' in app or 'physical_fault_context' in app:
                scratch = physics.mj.MjData(physics.model)
                physics.mj.mj_setState(physics.model, scratch, physics.np.asarray(state), spec)
                _restore_force_adapter(physics, value, scratch)
        except (KeyError, ValueError, TypeError) as error:
            errors.append('invalid owned application state: '+str(error))
    for key in OPTIONS:
        if key not in value.get('options', {}):
            errors.append('missing model option '+key)
    return errors


def restore(physics, value, *, level='R1', now=None):
    """Restore only a fresh, isolated instance; never rewind an active world."""
    start = time.monotonic()
    errors = compatibility(physics, value)
    if level not in ('R1', 'R2'):
        errors.append('supported restoration levels are R1 and R2')
    if physics.steps != 0 or physics.native_actions_busy:
        errors.append('restoration requires a fresh isolated physics instance')
    if errors:
        logging.warning('Checkpoint case skipped: %s', '; '.join(errors))
        return {'restored': False, 'level': level, 'reasons': errors,
                'active_world_changed': False}
    now = time.monotonic() if now is None else now
    m, d, mj = physics.model, physics.data, physics.mj
    for key, array in value['mutable_model'].items():
        if key in MUTABLE:
            getattr(m, key)[:] = array
    for key in OPTIONS:
        current = getattr(m.opt, key)
        if hasattr(current, 'shape'):
            current[:] = value['options'][key]
        else:
            setattr(m.opt, key, value['options'][key])
    mj.mj_setState(m, d, physics.np.asarray(value['integration_state']), value['state_spec'])
    app = value['application']
    for key in APP_FIELDS:
        setattr(physics, key, copy.deepcopy(app[key]))
    physics.reference = tuple(physics.reference)
    for name, arm in getattr(physics, 'business_arms', {}).items():
        if name != 'load':
            arm['reference'] = tuple(app['additional_arm_references'][name])
    physics.odom.__dict__.update(copy.deepcopy(app['odom']))
    physics.wheels.__dict__.update(_unage(app['wheels'], ['last_received'], now))
    physics.docking_guard.__dict__.update(copy.deepcopy(app['docking_guard']))
    physics.reset_quiet.__dict__.update(copy.deepcopy(app['reset_quiet']))
    b = physics.station_beacon
    for key in ('episode_id', 'episode_start', 'sequence', 'last_observation'):
        setattr(b, key, copy.deepcopy(app['beacon'][key]))
    b.rng.setstate(tuples(app['beacon']['rng']))
    from fishbot_sim_power import Truth
    truth = app['beacon']['truth']
    b.truth = Truth(**_unage(truth, ['received'], now)) if truth else None
    physics.observation_faults.__dict__.update(_unage(
        app['observation_faults'], ['trigger_monotonic', 'start_wall'], now))
    physics.physical_faults, physics.physical_fault_context = _restore_force_adapter(physics, value, d)
    parent_episode = physics.episode_id
    physics.world_session_id = value.get('world_session_id', parent_episode)
    if level == 'R2':
        physics.episode_id = str(uuid.uuid4())
        physics.world_session_id = str(uuid.uuid4())
        physics.wheels.begin_episode(float(d.time))
        physics.reset_stamp = float(d.time)
        physics.docking_guard.set_enabled(False)
        physics.native_actions_busy = False
        b.episode_id, b.episode_start, b.last_observation = physics.episode_id, float(d.time), None
        physics.observation_faults.begin_episode(physics.episode_id)
        physics.physical_faults.dearm(reason='checkpoint_R2_owner_fence')
        physics.physical_fault_context = None
    physics.identity['episode_id'] = physics.episode_id
    physics.last_wall = time.time()
    physics.refresh_snapshot()
    readback = physics.np.empty(len(value['integration_state']))
    mj.mj_getState(m, d, readback, value['state_spec'])
    readback_error = float(physics.np.max(physics.np.abs(readback-physics.np.asarray(value['integration_state']))))
    rotation = d.xmat[physics.car_body].reshape(3, 3)
    return {'restored': True, 'level': level, 'snapshot_id': value['snapshot_id'],
            'parent_world_session_id': value.get('world_session_id'),
            'world_session_id': physics.world_session_id,
            'parent_episode_id': parent_episode, 'episode_id': physics.episode_id,
            'source_s': float(d.time), 'steps': physics.steps,
            'integration_readback_max_abs_error': readback_error,
            'initial_car_pose': {'x':float(d.xpos[physics.car_body,0]),
                'y':float(d.xpos[physics.car_body,1]),
                'yaw':math.atan2(float(rotation[1,0]),float(rotation[0,0]))},
            'old_motion_commands_restored': level == 'R1',
            'physical_fault_context_source': 'explicit_owner_handoff_not_ROS_verified',
            'physical_faults_resumed': level == 'R1' and any(record['state'] in ('armed', 'active')
                for record in physics.physical_faults.events.values()),
            'external_components_restored': False,
            'unrestored_external_components': EXTERNAL,
            'restore_wall_s': time.monotonic()-start}


def _write_json(path, value, max_bytes):
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(payload) > max_bytes:
        raise ValueError('checkpoint exceeds declared per-file byte budget')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
        if path.exists():
            raise FileExistsError('checkpoint destination already exists')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(payload)


def write_checkpoint(path, value, *, max_bytes=64*1024*1024):
    started=time.monotonic()
    path = Path(path)
    definition = 'model-'+value['model_definition_id']+'.json'
    model_path = path.with_name(definition)
    model_bytes = 0
    if not model_path.exists():
        model_bytes = _write_json(model_path, value['model'], max_bytes)
    payload = {**value, 'model': {'reference': definition}}
    size = _write_json(path, payload, max_bytes)
    return {'path': str(path), 'snapshot_id': value['snapshot_id'],
            'bytes': size, 'new_model_bytes': model_bytes,
            'model_reference': definition,'captured_source_s':value['captured_source_s'],
            'capture_copy_wall_s':value['capture_copy_wall_s'],
            'io_wall_s':time.monotonic()-started,
            'capture_to_saved_wall_s':time.monotonic()-value.get('capture_started_monotonic_s',started),
            'timing_clock':'same_physics_process_monotonic'}


def read_checkpoint(path, *, max_bytes=64*1024*1024):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError('checkpoint exceeds declared per-file byte budget')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('checkpoint JSON must be an object')
    reference = value.get('model', {}).get('reference')
    if reference is not None:
        if Path(reference).name != reference or reference in ('.', '..'):
            raise ValueError('model definition must be a sibling JSON file')
        model_path = path.with_name(reference)
        if model_path.stat().st_size > max_bytes:
            raise ValueError('model definition exceeds declared per-file byte budget')
        value['model'] = json.loads(model_path.read_text())
    return value


class CheckpointIO:
    """Bound only outstanding IO copies; there is no task/daily quota."""
    def __init__(self, capacity=2):
        self.slots = threading.BoundedSemaphore(capacity)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='checkpoint-io')

    def submit(self, function, *args, **kwargs):
        if not self.slots.acquire(blocking=False):
            logging.warning('Checkpoint IO busy; skip only this request')
            return None
        try:
            future = self.executor.submit(function, *args, **kwargs)
        except Exception:
            self.slots.release()
            raise
        future.add_done_callback(lambda _: self.slots.release())
        return future

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=False)
