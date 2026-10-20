#!/usr/bin/python3
"""Compose editable MJCF and ROS parameters for the official MuJoCo lidar plugin.

The simulator performs ray casting and PointCloud2 publication upstream. This
module only composes scene/configuration files; it never starts ROS or installs
packages. Sensor defaults describe a generic device, not a calibrated product.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco'
DEFAULT_LIBRARY = (Path.home() / '.cache/fishbot/lidar3d/prefix/lib/'
                   'mujoco_3d_lidar/mujoco_plugin/libmujoco_3d_lidar.so')
LOG = logging.getLogger(__name__)


def _scene_tree(path: Path, stack: tuple[Path, ...] = ()) -> ET.Element:
    """Expand official MJCF includes while retaining asset file locations."""
    path = path.resolve()
    if path in stack:
        raise ValueError(f'Recursive MJCF include: {path}')
    root = ET.parse(path).getroot()
    compiler = root.find('compiler')
    directories = dict(compiler.attrib) if compiler is not None else {}
    for element in root.iter():
        if element.tag in ('mesh', 'texture', 'hfield', 'skin') and element.get('file'):
            value = Path(element.get('file'))
            if not value.is_absolute():
                key = 'texturedir' if element.tag == 'texture' else 'meshdir'
                directory = directories.get(key, directories.get('assetdir', ''))
                element.set('file', str((path.parent / directory / value).resolve()))
    if compiler is not None:
        for key in ('meshdir', 'texturedir', 'assetdir'):
            if compiler.get(key):
                compiler.set(key, str((path.parent / compiler.get(key)).resolve()))
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag != 'include':
                continue
            included = _scene_tree(path.parent / child.attrib['file'], stack + (path,))
            position = list(parent).index(child)
            parent.remove(child)
            for offset, nested in enumerate(list(included)):
                parent.insert(position + offset, nested)
    return root


def _parameters(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        LOG.warning('Optional parameters %s are empty; using defaults.', path)
        return {}
    return data


def _point_source(topic: str, maximum: float) -> dict:
    return {
        'topic': topic, 'data_type': 'PointCloud2', 'marking': True,
        'clearing': True, 'min_obstacle_height': 0.025,
        'max_obstacle_height': 0.8, 'obstacle_min_range': 0.12,
        'obstacle_max_range': maximum - 0.1, 'raytrace_min_range': 0.12,
        'raytrace_max_range': maximum, 'observation_persistence': 0.0,
    }


def prepare(scene_path: str | Path, output_dir: str | Path, *,
            plugins_path: str | Path | None = None,
            nav2_path: str | Path | None = None,
            profile_path: str | Path | None = None,
            library_path: str | Path | None = None,
            metadata_path: str | Path | None = None,
            audit_contacts: bool = False) -> dict:
    """Add an official generic 16-line lidar, preserving the original 2-D scan.

    Returns absolute scene/plugins/nav2 paths plus the static TF and extension
    location needed by the caller's existing launch. Missing optional metadata
    only emits a warning. The caller can edit every generated file normally.
    """
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    profile = _parameters(Path(profile_path or PACKAGE / 'config/lidar3d.yaml'))
    settings = profile.get('fishbot_lidar3d_profile', {}).get('ros__parameters', {})
    sensor_name = str(settings.get('sensor_name', 'generic_lidar3d'))
    frame = str(settings.get('frame_name', 'lidar3d_link'))
    parent_frame = str(settings.get('parent_frame', 'laser_link'))
    mount = settings.get('mount_xyz', [0.0, 0.0, 0.035])
    topic = str(settings.get('topic', '/sensors/lidar3d/points'))
    maximum = float(settings.get('max_range', 8.0))
    config = {
        'resolution': f"{int(settings.get('horizontal_samples', 360))} {int(settings.get('lines', 16))}",
        'azimuth_range': f'{-math.pi} {math.pi - 2 * math.pi / int(settings.get("horizontal_samples", 360))}',
        'elevation_range': ' '.join(str(math.radians(float(v))) for v in settings.get('vertical_degrees', [-15, 15])),
        'max_range': str(maximum), 'min_range': str(settings.get('min_range', 0.12)),
        'update_rate': str(settings.get('rate_hz', 10.0)), 'async': '0',
    }
    tree = _scene_tree(Path(scene_path))
    body = tree.find(f'.//body[@name="{parent_frame}"]')
    if body is None:
        raise ValueError(f'MJCF has no lidar mount body: {parent_frame}')
    site_name = 'fishbot_lidar3d_site'
    site = body.find(f'site[@name="{site_name}"]')
    if site is None:
        site = ET.SubElement(body, 'site', name=site_name)
    site.attrib.update(pos=' '.join(str(v) for v in mount), size='0.001', rgba='0 0 0 0')
    extension = tree.find('extension')
    if extension is None:
        extension = ET.SubElement(tree, 'extension')
    plugin = extension.find('plugin[@plugin="mujoco.plugin.lidar"]')
    if plugin is None:
        plugin = ET.SubElement(extension, 'plugin', plugin='mujoco.plugin.lidar')
    instance_name = 'fishbot_generic_lidar3d'
    instance = plugin.find(f'instance[@name="{instance_name}"]')
    if instance is None:
        instance = ET.SubElement(plugin, 'instance', name=instance_name)
    for child in list(instance):
        instance.remove(child)
    for key, value in config.items():
        ET.SubElement(instance, 'config', key=key, value=value)
    sensors = tree.find('sensor')
    if sensors is None:
        sensors = ET.SubElement(tree, 'sensor')
    for old in list(sensors.findall(f'plugin[@name="{sensor_name}"]')):
        sensors.remove(old)
    ET.SubElement(sensors, 'plugin', name=sensor_name, instance=instance_name,
                  objtype='site', objname=site_name)
    ET.indent(tree)
    scene = out / 'scene_lidar3d.xml'
    ET.ElementTree(tree).write(scene, encoding='utf-8', xml_declaration=True)

    plugins = _parameters(Path(plugins_path or PACKAGE / 'config/plugins.yaml'))
    plugin_params = plugins.setdefault('/**', {}).setdefault('ros__parameters', {})
    # The upstream 0.1.1 wrapper hard-codes this instance prefix.
    plugin_params.setdefault('mujoco_plugins', {})['mujoco_3d_lidar_plugin'] = {
        'type': 'mujoco_ros2_control_plugins/Mujoco3dLidarPlugin',
        sensor_name: {'frame_name': frame, 'topic': topic},
    }
    if audit_contacts:
        plugin_params['mujoco_plugins']['contact_audit'] = {
            'type': 'fishbot_mujoco/ContactAudit',
            'robot_body': 'base_footprint', 'floor_geoms': ['floor'],
        }
    plugins_out = out / 'plugins_lidar3d.yaml'
    plugins_out.write_text(yaml.safe_dump(plugins, sort_keys=False))

    nav2 = _parameters(Path(nav2_path or PACKAGE / 'config/nav2.yaml'))
    for name in ('local_costmap', 'global_costmap'):
        params = nav2.setdefault(name, {}).setdefault(name, {}).setdefault('ros__parameters', {})
        layers = params.setdefault('plugins', [])
        key = 'voxel_layer' if 'voxel_layer' in layers else 'lidar3d_voxel_layer'
        if key not in layers:
            position = layers.index('inflation_layer') if 'inflation_layer' in layers else len(layers)
            layers.insert(position, key)
        layer = params.setdefault(key, {
            'plugin': 'nav2_costmap_2d::VoxelLayer', 'enabled': True,
            'publish_voxel_map': True, 'origin_z': 0.0, 'z_resolution': 0.05,
            'z_voxels': 16, 'max_obstacle_height': 0.8, 'mark_threshold': 0,
        })
        sources = str(layer.get('observation_sources', '')).split()
        if 'lidar3d' not in sources:
            sources.append('lidar3d')
        layer['observation_sources'] = ' '.join(sources)
        layer['lidar3d'] = _point_source(topic, maximum)
    nav2_out = out / 'nav2_voxel.yaml'
    nav2_out.write_text(yaml.safe_dump(nav2, sort_keys=False))
    prefix = os.environ.get('FISHBOT_LIDAR3D_PREFIX')
    selected_library = (Path(prefix) / 'lib/mujoco_3d_lidar/mujoco_plugin/libmujoco_3d_lidar.so'
                        if prefix else DEFAULT_LIBRARY)
    library = Path(library_path or selected_library).expanduser().resolve()
    if not library.is_file():
        LOG.warning('Official lidar extension is not available yet: %s', library)
    metadata = {}
    if metadata_path:
        try:
            metadata = json.loads(Path(metadata_path).read_text())
        except (OSError, ValueError) as error:
            LOG.warning('Optional scene metadata unavailable: %s', error)
    return {
        'scene': str(scene), 'plugins': str(plugins_out), 'nav2': str(nav2_out),
        'library': str(library), 'plugin_directory': str(library.parent),
        'sensor_name': sensor_name, 'topic': topic, 'metadata': metadata,
        'static_transform': {
            'parent_frame': parent_frame, 'child_frame': frame,
            'translation': list(mount), 'rotation_rpy': [0.0, 0.0, 0.0],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--plugins', type=Path)
    parser.add_argument('--nav2', type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--library', type=Path)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--contact-audit', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.scene, args.output, plugins_path=args.plugins,
                             nav2_path=args.nav2, profile_path=args.profile,
                             library_path=args.library, metadata_path=args.metadata,
                             audit_contacts=args.contact_audit), indent=2))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    main()
