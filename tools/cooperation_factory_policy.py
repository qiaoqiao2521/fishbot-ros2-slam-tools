#!/usr/bin/env python3
"""Explicit local factory policy loading, without ROS or a replacement planner.

Config examples::

  {"schema": 1, "entrypoint": {"builtin": "direct"}}
  {"schema": 1, "entrypoint": {"builtin": "declared_via"},
   "parameters": {"egress_pose": {"x": 0, "y": -2.7, "yaw": 0}}}
  {"schema": 1, "entrypoint": {"module_path": "my_policy.py",
    "function": "select_egress"}, "parameters": {}}

Local Python policies are trusted user-selected code. The adapter itself never
initializes ROS or sends commands. Selection occurs once for the entire run;
the existing carrying Nav2 action and oracle own execution and acceptance.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import time
import uuid

from cooperation_acceptance import private_json
from cooperation_core import task_delivery_pose
from cooperation_workflow import read_json


class PolicyError(ValueError):
    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


def describe_config(path):
    """Inspect JSON only. Never import the selected module or call its function."""
    path = Path(path).resolve()
    config = read_json(path)
    if not isinstance(config, dict) or type(config.get('schema')) is not int or config['schema'] != 1:
        raise ValueError('Factory policy configuration requires schema 1')
    entry = config.get('entrypoint')
    if not isinstance(entry, dict):
        raise ValueError('Policy entrypoint must declare builtin or local module_path')
    if 'builtin' in entry:
        if entry.get('builtin') not in ('direct', 'declared_via') or 'module_path' in entry:
            raise ValueError('Select exactly one supported builtin or local module_path')
        resolved = {'builtin': entry['builtin']}
    else:
        module = entry.get('module_path')
        function = entry.get('function', 'select_egress')
        if not isinstance(module, str) or not module or not isinstance(function, str) or not function.isidentifier():
            raise ValueError('Local policy requires module_path and an identifier function name')
        module_path = Path(module)
        if not module_path.is_absolute():
            module_path = path.parent/module_path
        resolved = {'module_path': str(module_path.resolve()), 'function': function}
    parameters = config.get('parameters', {})
    if not isinstance(parameters, dict):
        raise ValueError('Policy parameters must be a JSON object')
    return {'config_file': str(path), 'config': config, 'resolved_entrypoint': resolved,
            'execution_status': 'not_executed', 'selected_module_imported': False,
            'function_invoked': False, 'adapter_initializes_ROS': False}


def require_supported(manifest):
    profile = manifest.get('scene_profile', {})
    if profile.get('vehicle') != 'fishbot' or 'factory_delivery' not in manifest:
        raise ValueError('Factory map-egress policies currently support FishBot factory scenes only; '
                         'J100 body-frame DriveOnHeading routes are unsupported')
    if manifest.get('egress_motion') is not None:
        raise ValueError('Factory policy cannot replace body-frame egress_motion with a map reference')


def direct(context):
    """Use the existing final delivery action without an intermediate goal."""
    return None


def declared_via(context):
    """Read one editable map point; the original pose and geometry checks follow."""
    return context['parameters']['egress_pose']


def _load(entry):
    if 'builtin' in entry:
        module = sys.modules[__name__]
        function = {'direct': direct, 'declared_via': declared_via}[entry['builtin']]
    else:
        spec = importlib.util.spec_from_file_location('factory_local_policy_'+uuid.uuid4().hex,
                                                      entry['module_path'])
        if spec is None or spec.loader is None:
            raise ValueError('Local policy file has no Python loader')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        function = getattr(module, entry['function'])
    if not callable(function):
        raise ValueError('Configured policy entrypoint is not callable')
    return function, {'module': module.__name__, 'module_file': str(Path(module.__file__).resolve()),
                      'function': function.__qualname__, 'callable_module': function.__module__,
                      'callable_source_file': inspect.getsourcefile(function)}


def _json_observation(value):
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError):
        return {'unserializable_type': type(value).__name__, 'representation': repr(value)[:1000]}


def apply_policy(manifest, description, *, declaration=None, geometry_factory=None, notify=None):
    """Call the actual selected function and derive only the map egress input."""
    receipt = {'schema': 1, **copy.deepcopy(description), 'execution_status': 'running',
               'selection_scope': 'one fixed optional map egress shared by all declared orders',
               'path_validated': False, 'arrival_validated': False,
               'custom_policy_is_trusted_local_code': True, 'stage': 'support'}
    def changed():
        if notify is not None:
            notify(receipt)
    try:
        require_supported(manifest)
        context = {'schema': 1, 'frame': 'map', 'units': {'position': 'm', 'angle': 'rad'},
                   'scene_profile': copy.deepcopy(manifest['scene_profile']),
                   'factory_delivery': copy.deepcopy(manifest['factory_delivery']),
                   'orders': copy.deepcopy((declaration or {}).get('orders',
                                           manifest['factory_delivery'].get('orders', []))),
                   'existing_egress_pose': copy.deepcopy(manifest.get('egress_pose')),
                   'parameters': copy.deepcopy(description['config'].get('parameters', {}))}
        receipt['input_context'] = copy.deepcopy(context)
        receipt['stage'] = 'load'
        changed()
        function, actual = _load(description['resolved_entrypoint'])
        receipt.update(actual_entrypoint=actual, selected_module_imported=True, stage='call',
                       call_started_wall_time=time.time(), function_invocation_attempted=True)
        changed()
        started = time.monotonic()
        try:
            returned = function(copy.deepcopy(context))
        except Exception:
            receipt.update(function_invoked=True, call_completed=False,
                           call_elapsed_wall_s=time.monotonic()-started)
            raise
        receipt.update(function_invoked=True, call_completed=True, call_elapsed_wall_s=time.monotonic()-started,
                       returned_value=_json_observation(returned), stage='pose_validation')
        pose = task_delivery_pose({'delivery_pose': returned}) if returned is not None else None
        receipt['selected_egress_pose'] = copy.deepcopy(pose)
        receipt['stage'] = 'geometry'
        changed()
        if pose is not None:
            if geometry_factory is None:
                from cooperation_geometry_check import SceneGeometry
                geometry_factory = SceneGeometry
            geometry = geometry_factory(manifest).check_pose(pose)
            receipt['point_geometry'] = geometry
            if geometry.get('passed') is not True:
                raise ValueError('Selected egress point failed original SceneGeometry: '+
                                 str(geometry.get('reason')))
        else:
            receipt['point_geometry'] = {'required': False, 'reason': 'no intermediate point selected',
                                         'path_validated': False, 'arrival_validated': False}
        derived = copy.deepcopy(manifest)
        if pose is None:
            derived.pop('egress_pose', None)
        else:
            derived['egress_pose'] = pose
        derived['factory_policy'] = {'config_file': description['config_file'],
                                     'actual_entrypoint': actual,
                                     'selected_egress_pose': copy.deepcopy(pose),
                                     'selection_scope': receipt['selection_scope'],
                                     'path_validated': False, 'arrival_validated': False}
        receipt.update(execution_status='succeeded', stage='complete', failure_reason=None)
        changed()
        return derived, receipt
    except Exception as error:
        receipt.update(execution_status='failed', failure_reason=type(error).__name__+': '+str(error))
        changed()
        raise PolicyError(receipt['failure_reason'], receipt) from error


def materialize(manifest_path, config_path, output_path, receipt_path, *, declaration=None,
                geometry_factory=None):
    """Owned software worker; preserve the original prepared manifest in place."""
    output_path, receipt_path = Path(output_path), Path(receipt_path)
    def record(value):
        private_json(receipt_path, value, replace=receipt_path.exists())
    try:
        manifest = json.loads(Path(manifest_path).read_text())
        description = describe_config(config_path)
        description['input_manifest_file'] = str(Path(manifest_path).resolve())
        derived, receipt = apply_policy(manifest, description, declaration=declaration,
                                       geometry_factory=geometry_factory, notify=record)
        receipt.update(input_manifest_file=str(Path(manifest_path).resolve()),
                       derived_manifest_file=str(output_path.resolve()))
        private_json(output_path, derived)
        record(receipt)
        return derived, receipt
    except PolicyError:
        raise
    except Exception as error:
        receipt = {'schema': 1, 'execution_status': 'failed', 'stage': 'materialize',
                   'input_manifest_file': str(Path(manifest_path).resolve()),
                   'config_file': str(Path(config_path).resolve()),
                   'failure_reason': type(error).__name__+': '+str(error)}
        record(receipt)
        raise PolicyError(receipt['failure_reason'], receipt) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-manifest', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--declaration', type=Path)
    args = parser.parse_args(argv)
    try:
        declaration = json.loads(args.declaration.read_text()) if args.declaration else None
        _, receipt = materialize(args.manifest, args.config, args.output_manifest, args.receipt,
                                 declaration=declaration)
        print(json.dumps(receipt, ensure_ascii=False, allow_nan=False))
        return 0
    except PolicyError as error:
        print(json.dumps(error.receipt, ensure_ascii=False, allow_nan=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
