"""Merge optional keepout filters without replacing the navigation baseline."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

import yaml


FILTER_NAME = 'keepout_filter'
FILTER_PLUGIN = 'nav2_costmap_2d::KeepoutFilter'
FILTER_INFO_TOPIC = '/keepout_costmap_filter_info'
INFLATION_NAME = 'keepout_inflation'
INFLATION_PLUGIN = 'nav2_costmap_2d::InflationLayer'


def merge_keepout_parameters(parameters):
    """Return a separate configuration, preserving other node and layer settings."""
    if not isinstance(parameters, dict):
        raise ValueError('Navigation parameters must be a YAML mapping')
    merged = copy.deepcopy(parameters)
    for name in ('global_costmap', 'local_costmap'):
        try:
            values = merged[name][name]['ros__parameters']
        except (KeyError, TypeError) as error:
            raise ValueError(f'Missing {name}.{name}.ros__parameters') from error
        if not isinstance(values, dict):
            raise ValueError(f'{name} ros__parameters must be a mapping')
        filters = values.get('filters', [])
        if not isinstance(filters, list) or any(
                not isinstance(item, str) or not item for item in filters):
            raise ValueError(f'{name} filters must be a list of names')
        existing = values.get(FILTER_NAME, {})
        if not isinstance(existing, dict):
            raise ValueError(f'{name}.{FILTER_NAME} must be a mapping')
        if existing.get('plugin', FILTER_PLUGIN) != FILTER_PLUGIN:
            raise ValueError(f'{name}.{FILTER_NAME} has a different plugin')
        baseline_inflation = values.get('inflation_layer', {})
        existing_inflation = values.get(INFLATION_NAME, {})
        for block, label in ((baseline_inflation, 'inflation_layer'),
                             (existing_inflation, INFLATION_NAME)):
            if not isinstance(block, dict):
                raise ValueError(f'{name}.{label} must be a mapping')
            if block.get('plugin', INFLATION_PLUGIN) != INFLATION_PLUGIN:
                raise ValueError(f'{name}.{label} has a different plugin')
        # Plugins finish before filters. Keepout needs its own following
        # inflation stage; never pre-expand the lethal mask by the robot radius.
        others = [item for item in filters if item not in (FILTER_NAME, INFLATION_NAME)]
        values['filters'] = [*dict.fromkeys(others), FILTER_NAME, INFLATION_NAME]
        values[FILTER_NAME] = {
            **existing,
            'plugin': FILTER_PLUGIN,
            'enabled': True,
            'filter_info_topic': FILTER_INFO_TOPIC,
            'override_lethal_cost': False,
        }
        values[INFLATION_NAME] = {
            'inflation_radius': 0.3,
            'cost_scaling_factor': 4.0,
            **copy.deepcopy(baseline_inflation),
            'plugin': INFLATION_PLUGIN,
            'enabled': True,
        }
    return merged


def prepare_keepout_parameters(params_file, enabled, output_dir=None):
    """Return exact input/output provenance and write only when rules are enabled."""
    source = Path(params_file).expanduser().resolve()
    try:
        raw = source.read_bytes()
    except OSError as error:
        raise ValueError(f'Cannot read navigation parameters: {source}') from error
    provenance = {
        'map_rules': bool(enabled),
        'source_path': str(source),
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'params_path': os.fspath(params_file),
        'params_sha256': hashlib.sha256(raw).hexdigest(),
    }
    if not enabled:
        return provenance
    try:
        parameters = yaml.safe_load(raw.decode('utf-8'))
        merged = merge_keepout_parameters(parameters)
    except (UnicodeError, yaml.YAMLError, ValueError) as error:
        raise ValueError(f'Invalid navigation parameters in {source}: {error}') from error
    if output_dir is None:
        output_dir = os.environ.get('ROS_LOG_DIR') or (
            Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
            / 'fishbot' / 'launch')
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(merged, sort_keys=False).encode('utf-8')
    descriptor, generated = tempfile.mkstemp(
        prefix='fishbot-keepout-', suffix='.yaml', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
        provenance.update(params_path=generated,
                          params_sha256=hashlib.sha256(content).hexdigest())
        Path(generated + '.source.json').write_text(
            json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    except Exception:
        Path(generated).unlink(missing_ok=True)
        Path(generated + '.source.json').unlink(missing_ok=True)
        raise
    return provenance
