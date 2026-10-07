"""Offline launch contracts; this module never imports or initializes ROS."""
import os
from pathlib import Path

import yaml


def simulation_environment(domain='94'):
    selected = str(domain)
    if (not selected.isascii() or not selected.isdigit()
            or not 1 <= int(selected) <= 232):
        raise ValueError('Light simulation requires domain 1..232; domain 0 is reserved for hardware')
    return {'ROS_DOMAIN_ID': selected,
            'FISHBOT_LIGHT_SIM_DOMAIN_ID': selected,
            'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
            'ROS_LOCALHOST_ONLY': '1',
            'ROS_STATIC_PEERS': ''}


def configure_simulation_environment(environ=None):
    """Select this simulator's domain before rclpy.init, ignoring ambient ROS domains."""
    env = os.environ if environ is None else environ
    values = simulation_environment(env.get('FISHBOT_LIGHT_SIM_DOMAIN_ID', '94'))
    env.update(values)
    return int(values['ROS_DOMAIN_ID'])


def ground_truth_enabled(use_amcl):
    if isinstance(use_amcl, bool):
        return not use_amcl
    if not isinstance(use_amcl, str) or use_amcl.lower() not in ('true', 'false'):
        raise ValueError('use_amcl must be true or false')
    return use_amcl.lower() != 'true'


def readable_map(path):
    """Require an explicit YAML and its image; never choose a local room map."""
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ValueError('An explicit readable map YAML path is required')
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError('Map YAML is not a regular file')
    try:
        document = yaml.safe_load(source.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError('Map YAML cannot be read') from error
    if not isinstance(document, dict) or not isinstance(document.get('image'), str) or not document['image'].strip():
        raise ValueError('Map YAML requires an image path')
    image = Path(document['image'])
    if not image.is_absolute():
        image = source.parent / image
    if not image.is_file():
        raise ValueError('Map image is not a regular file')
    try:
        with image.open('rb') as stream:
            if not stream.read(1):
                raise ValueError('Map image is empty')
    except OSError as error:
        raise ValueError('Map image cannot be read') from error
    return str(source)
