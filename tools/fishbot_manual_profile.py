"""Render an explicit low-speed profile without selecting a scene or starting ROS."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import time
import uuid

import yaml

from fishbot_manual_lease import LIMITS, PROFILE_ID


ROOT = Path(__file__).resolve().parent
TWIST_MUX_DEB_VERSION = '4.5.0-1noble.20260912.170228'
TWIST_MUX_SOURCE = 'https://github.com/ros-teleop/twist_mux/tree/4.5.0'


def build_manual_profile(base, geometry, *, scan_frame, observers=('fishbot_mission_bridge',)):
    """Keep the selected map/localization/filter parameters; reuse passage geometry.

    The launch integration must start exactly one Nav2 stack, apply the returned
    node-qualified smoother remap before general Nav2 remaps, and launch the
    original guard with the explicit subscriber list. This helper launches none.
    """
    if not isinstance(scan_frame, str) or not scan_frame or len(scan_frame) > 128:
        raise ValueError('an explicit scan frame from the selected simulation is required')
    if (not isinstance(observers, (list, tuple)) or len(set(observers)) != len(observers)
            or 'diff_drive_controller' in observers
            or any(not isinstance(name, str) or not name for name in observers)):
        raise ValueError('observers must be an explicit unique node list')
    spec = importlib.util.spec_from_file_location('fishbot_manual_passage', ROOT/'fishbot_passage.launch.py')
    passage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(passage)
    params, model = copy.deepcopy(base), copy.deepcopy(geometry)
    model['frames']['scan'] = scan_frame
    defaults = yaml.safe_load((ROOT/'config/fishbot_passage_nav.yaml').read_text())
    # These existing sections contain the complete low-speed controller, behavior,
    # smoother and collision configuration. Keep selected map/costmap/filter data.
    for name in ('controller_server', 'behavior_server', 'velocity_smoother', 'collision_monitor'):
        params[name]['ros__parameters'].update(copy.deepcopy(defaults[name]['ros__parameters']))
    params = passage.build_parameters(params, model, timing_profile='strict')
    for name in ('local_costmap', 'global_costmap'):
        # Nav2 uses the explicit polygon above. Retain the selected profile's
        # fallback radius for the existing owner's unchanged keepout checks.
        original = base[name][name]['ros__parameters']
        if 'robot_radius' in original:
            params[name][name]['ros__parameters']['robot_radius'] = original['robot_radius']
    model['command_guard']['expected_final_subscribers'] = ['diff_drive_controller', *observers]
    model['command_guard']['output_stamped'] = True
    mux = yaml.safe_load((ROOT/'config/fishbot_manual_mux.yaml').read_text())
    for name, section in params.items():
        nested = section.get(name, section)
        if 'ros__parameters' in nested:
            nested['ros__parameters']['use_sim_time'] = True
    mux['twist_mux']['ros__parameters']['use_sim_time'] = True
    return {'profile_id': PROFILE_ID, 'parameters': params, 'geometry': model, 'mux': mux,
            'mux_remappings': [('cmd_vel_out', '/cmd_vel_selected')],
            'nav_remappings': [('velocity_smoother:cmd_vel', '/cmd_vel_selected'),
                               ('/cmd_vel', '/cmd_vel_nav')],
            'guard_options': {'output_stamped': True, 'timing_profile': 'strict',
                              'expected_final_subscribers': model['command_guard']['expected_final_subscribers']},
            'limits': copy.deepcopy(LIMITS), 'twist_mux_version': TWIST_MUX_DEB_VERSION}


def manual_capability(*, available=False, reason='manual_profile_not_enabled'):
    return {'id': 'teleop', 'submission': 'topic_publish', 'task_lookup': True,
            'cancel': True, 'event_history': 'snapshot', 'available': bool(available),
            'protocol': 'manual_lease_v1', 'profile_id': PROFILE_ID,
            'reason': reason, 'limits': copy.deepcopy(LIMITS)}


def installed_twist_mux(prefix=Path('/opt/ros/jazzy')):
    """Read the installed official descriptor without executing its ROS node."""
    descriptor = Path(prefix)/'share/twist_mux/package.xml'
    root = ET.parse(descriptor).getroot()
    version = root.findtext('version')
    if version != '4.5.0':
        raise ValueError('manual profile requires verified twist_mux 4.5.0')
    return {'name': root.findtext('name'), 'version': version,
            'declared_license': root.findtext('license'), 'source': TWIST_MUX_SOURCE,
            'descriptor': str(descriptor)}


def prepare_manual_files(params_file, plugins_file, output_dir, *, domain, observers=('fishbot_mission_bridge',),
                         empty_domain_checked_at_ms=None):
    """Generate checked parameters in a fresh private external run directory."""
    if type(domain) is not int or not 1 <= domain <= 232:
        raise ValueError('manual profile requires an isolated nonzero domain')
    output = Path(output_dir)
    if not output.is_absolute():
        raise ValueError('manual_output_dir must be absolute and outside the source repository')
    for parent in (ROOT, *ROOT.parents):
        if (parent/'.git').exists():
            if output.resolve().is_relative_to(parent):
                raise ValueError('manual_output_dir must be outside the source repository')
            break
    installed = installed_twist_mux()
    plugins = yaml.safe_load(Path(plugins_file).read_text())
    scan_frame = plugins['/**']['ros__parameters']['mujoco_plugins']['rangefinder_lidar_plugin']['laser']['frame_name']
    base = yaml.safe_load(Path(params_file).read_text())
    geometry = yaml.safe_load((ROOT/'config/fishbot_model_geometry.yaml').read_text())
    result = build_manual_profile(base, geometry, scan_frame=scan_frame, observers=observers)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    paths = {}
    for field in ('parameters', 'geometry', 'mux'):
        path = output/(field+'.yaml')
        path.write_text(yaml.safe_dump(result[field], sort_keys=False))
        paths[field] = str(path)
    receipt = {'profile_id': PROFILE_ID, 'domain': domain, 'source_params': str(Path(params_file).resolve()),
               'source_plugins': str(Path(plugins_file).resolve()), 'scan_frame': scan_frame,
               'paths': paths, 'limits': result['limits'], 'dependency': installed,
               'boot_id': str(uuid.uuid4()), 'empty_domain_checked_at_ms': empty_domain_checked_at_ms}
    (output/'manual-profile.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


def claim_manual_boot(receipt_path, domain, *, now_ms=None):
    """Consume the launch's fresh empty-domain check once, before ROS init.

    This is a local launch/restart fence, not authentication against a local user
    deliberately forging files. A surviving Nav2 stack cannot reuse this receipt.
    """
    if not receipt_path:
        raise ValueError('passage_manual must start through its checked simulation launch')
    path = Path(receipt_path).resolve()
    receipt = json.loads(path.read_text())
    checked = receipt.get('empty_domain_checked_at_ms')
    wall = time.time_ns()//1_000_000 if now_ms is None else now_ms
    if (receipt.get('profile_id') != PROFILE_ID or receipt.get('domain') != domain
            or type(checked) is not int or not 0 <= wall-checked <= 60_000
            or str(uuid.UUID(receipt['boot_id'])) != receipt['boot_id']):
        raise ValueError('manual empty-domain boot receipt is missing, stale or mismatched')
    claim = path.with_name('manual-owner.claim')
    try:
        descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise ValueError('manual boot receipt already consumed; restart the complete isolated runtime') from None
    with os.fdopen(descriptor, 'w') as stream:
        json.dump({'boot_id': receipt['boot_id'], 'domain': domain, 'pid': os.getpid()}, stream)
    return receipt
