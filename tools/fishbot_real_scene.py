#!/usr/bin/env python3
"""Prepare a private known-space route from a measured occupancy map.

This reuses home_scene's map, footprint and wall partitioning. No ROS process,
motion command, unknown-space completion or replacement scheduler is created.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
import yaml

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
spec = importlib.util.spec_from_file_location('fishbot_real_home_reuse', TOOLS / 'fishbot_home_scene.py')
home = importlib.util.module_from_spec(spec)
spec.loader.exec_module(home)


def measured_space(source_map):
    """Return the original raster and conservative all-heading footprint clearance."""
    info, raw, free, occupied, source, image = home.load_map(source_map)
    grid = home.Grid(~free, free | occupied, info['origin'], float(info['resolution']))
    # Subtract half a cell diagonal: clearance is to the entire non-free cell.
    # Padding with non-free cells also treats outside the raster as unobserved.
    clearance = distance_transform_edt(np.pad(free, 1))[1:-1, 1:-1] * grid.resolution
    clearance -= grid.resolution / math.sqrt(2)
    radius = math.hypot(home.BODY_HALF_LENGTH, home.BODY_HALF_WIDTH)
    return info, raw, free, occupied, source, image, grid, clearance, radius


def pose_clearance(grid, clearance, pose):
    """Conservative clearance at continuous XY; rotation fits inside the full disk."""
    x, y = map(float, pose[:2])
    row, column = grid.cell(x, y)
    if not (0 <= row < clearance.shape[0] and 0 <= column < clearance.shape[1]):
        return -math.inf
    cx, cy = grid.xy(row, column)
    return float(clearance[row, column]) - math.hypot(x - cx, y - cy)


def measured_pose_clearance(source_map, pose):
    """Signed known-free margin outside the complete padded body turning disk."""
    *_, grid, clearance, radius = measured_space(source_map)
    return pose_clearance(grid, clearance, pose) - radius


def audit_recording(case, samples):
    """Read-only independent truth check; missing evidence stays explicitly unknown."""
    source = case.get('measured_map')
    metrics = {'measured_truth_samples': 0, 'minimum_measured_free_margin_m': None}
    if not source:
        return {'passed': None, 'metrics': metrics, 'reason': 'Measured source map is unspecified'}
    try:
        *_, grid, clearance, radius = measured_space(source)
        margins = [pose_clearance(grid, clearance, [sample['x'], sample['y']])-radius
                   for sample in samples]
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        return {'passed': None, 'metrics': metrics, 'reason': f'Measured-map evidence unavailable: {error}'}
    if not margins:
        return {'passed': None, 'metrics': metrics, 'reason': 'No independent truth samples'}
    minimum = min(margins)
    metrics.update(measured_truth_samples=len(margins),
                   minimum_measured_free_margin_m=minimum if math.isfinite(minimum) else None)
    return {'passed': math.isfinite(minimum) and minimum >= 0., 'metrics': metrics,
            'reason': 'Every independent pose must keep its complete padded turning disk inside measured free space'}


def select_route(grid, clearance, radius, distance_m=1.6, margin_m=.03):
    """Find and simplify a reachable route wholly inside measured free space."""
    if not math.isfinite(distance_m) or distance_m <= 0:
        raise ValueError('route_distance_m must be finite and positive')
    if not math.isfinite(margin_m) or margin_m < 0:
        raise ValueError('clearance_margin_m must be finite and nonnegative')
    required = radius + margin_m
    if pose_clearance(grid, clearance, [0., 0.]) < required:
        raise ValueError('Original spawn [0,0,0] lacks known-space full-turn clearance')
    safe = clearance >= required
    start = grid.cell(0., 0.)
    distances = home.reachable_cells(safe, start)
    possible = np.argwhere(distances >= math.ceil(distance_m / grid.resolution))
    if not len(possible):
        raise ValueError('Measured connected free space cannot fit the requested route distance')
    # Prefer the nearest distance budget, then greater clearance, without crossing unknown.
    end = min(map(tuple, possible), key=lambda cell: (int(distances[cell]), -float(clearance[cell])))
    cells = [end]
    while cells[-1] != start:
        row, col = cells[-1]
        options = [(row-1, col), (row+1, col), (row, col-1), (row, col+1)]
        cells.append(max((cell for cell in options
                          if 0 <= cell[0] < safe.shape[0] and 0 <= cell[1] < safe.shape[1]
                          and distances[cell] == distances[row, col] - 1),
                         key=lambda cell: float(clearance[cell])))
    points = [[0., 0.], *(grid.xy(*cell) for cell in reversed(cells))]

    def segment_free(first, second):
        steps = max(2, math.ceil(math.dist(first, second) / (grid.resolution / 5)))
        return all(pose_clearance(grid, clearance, first + (second-first)*t) >= required
                   for t in np.linspace(0., 1., steps+1))

    # Greedy line-of-sight shortening retains only necessary turns. Each segment is
    # sampled at 1/5 cell and includes a full-rotation disk, not a point robot.
    shortened = [points[0]]
    index = 0
    while index < len(points)-1:
        target = next((candidate for candidate in range(len(points)-1, index, -1)
                       if segment_free(np.array(points[index]), np.array(points[candidate]))), None)
        if target is None:
            raise ValueError('Known-space route cannot preserve the continuous swept disk')
        shortened.append(points[target])
        index = target
    poses = []
    for index, point in enumerate(shortened[1:], 1):
        previous = shortened[index-1]
        poses.append({'x': round(point[0], 6), 'y': round(point[1], 6),
                      'yaw': math.atan2(point[1]-previous[1], point[0]-previous[0])})
    return {'waypoints': poses, 'swept_path_xy': shortened, 'grid_path_xy': points,
            'route_length_m': sum(math.dist(a, b) for a, b in zip(shortened, shortened[1:])),
            'required_turn_radius_m': required, 'padded_body_radius_m': radius,
            'spawn_measured_clearance_m': pose_clearance(grid, clearance, [0., 0.]),
            'selection': 'known-free full-rotation disk and continuous segment precheck; runtime acceptance remains separate'}


def prepare(source_map, output_dir, *, distance_m=1.6, margin_m=.03, domain=132, port=9102):
    info, raw, free, occupied, source, image, grid, clearance, radius = measured_space(source_map)
    route = select_route(grid, clearance, radius, distance_m, margin_m)
    output = home.prepare_output(output_dir)
    # Keep the original Nav2/AMCL raster exactly, including unknown pixels. Unknown
    # cells are excluded by planner policy; they are never disguised as lidar walls.
    shutil.copyfile(image, output / 'map.pgm')
    (output / 'map.yaml').write_text(yaml.safe_dump({**info, 'image': 'map.pgm'}, sort_keys=False))
    mask = np.where(free | occupied, 0, 127).astype(np.uint8)
    Image.fromarray(mask).save(output / 'assumption_mask.pgm')
    physical_grid = home.Grid(occupied, free | occupied, info['origin'], float(info['resolution']))
    rectangles = home.rectangles(occupied)
    if not rectangles:
        raise ValueError('A measured wall is required for the reused physical scene writer')
    walls = home.write_scene(physical_grid, [], rectangles[0], home.DEFAULT_ROBOT, output)
    walls[0]['name'] = 'measured_wall_marker'
    tree = ET.parse(output / 'scene.xml')
    marker = tree.getroot().find("worldbody/geom[@name='dock_marker']")
    marker.set('name', 'measured_wall_marker')
    marker.attrib.pop('material', None)
    marker.set('rgba', '.68 .69 .72 1')
    ET.indent(tree)
    tree.write(output / 'scene.xml', encoding='utf-8', xml_declaration=True)
    nav = yaml.safe_load((ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml').read_text())
    nav['planner_server']['ros__parameters']['GridBased']['allow_unknown'] = False
    (output / 'nav2.yaml').write_text(yaml.safe_dump(nav, sort_keys=False))
    provenance = {'source_yaml': str(source), 'source_image': str(image),
        'basis': 'measured_occupancy', 'source_shape_rows_cols': list(raw.shape),
        'resolution_m': float(info['resolution']), 'origin': info['origin'],
        'known_free_cells': int(free.sum()), 'known_occupied_cells': int(occupied.sum()),
        'unknown_cells': int((~(free | occupied)).sum()),
        'source_raster_preserved_exactly': True, 'unknown_completion': 'none',
        'assumption_mask': str(output / 'assumption_mask.pgm'),
        'assumption_mask_legend': {'0': 'measured free/occupied, unchanged', '127': 'unobserved, no physical reconstruction'},
        'height_assumption_m': .55,
        'physics_policy': 'Only measured occupied cells become wall boxes; 2D map does not establish height, material or dynamic objects',
        'navigation_unknown_policy': 'Original unknown retained for AMCL; NavFn allow_unknown=false',
        'physical_wall_rectangles': walls, 'route': route,
        'scope': 'Measured 2D layout in simulation; not a photoreal reconstruction or real-robot validation'}
    (output / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2)+'\n')
    config = {'schema_version': 1, 'scene_path': str(output / 'scene.xml'), 'map': str(output / 'map.yaml'),
        'measured_map': str(source),
        'plugins_file': str(ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/plugins.yaml'),
        'params_file': str(output / 'nav2.yaml'),
        'source': {'label': '实测工作地图：已知区域往返', 'basis': 'measured_occupancy',
                   'assumption_cells': 'unknown not reconstructed; walls use assumed 0.55m height',
                   'assumption_mask': str(output / 'assumption_mask.pgm'), 'provenance': str(output / 'provenance.json')},
        'lidar': {'profile': 'generic-16-line-3d'},
        'lidar_probe': {'low_obstacle_required': False, 'reason': '真实场图无专用低矮测试物'},
        'domain': domain, 'api': f'http://127.0.0.1:{port}',
        'timeout_s': 150, 'startup_timeout_s': 45, 'return_home': True,
        'waypoints': route['waypoints'],
        'geometry': {'half_length': home.BODY_HALF_LENGTH, 'half_width': home.BODY_HALF_WIDTH},
        'measured_route_contract': {'source_map': str(source), 'required_turn_radius_m': radius,
                                    'preflight_margin_m': margin_m, 'route': route},
        'cases': [{'id': 'measured-roundtrip', 'label': '实测已知区域往返', 'expected': 'delivered', 'obstacle': None,
                   'measured_route_contract': {'source_map': str(source), 'required_turn_radius_m': radius,
                                               'preflight_margin_m': margin_m}}]}
    (output / 'panel-config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2)+'\n')
    return config, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-map', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--distance', type=float, default=1.6)
    parser.add_argument('--margin', type=float, default=.03)
    parser.add_argument('--domain', type=int, default=132)
    parser.add_argument('--port', type=int, default=9102)
    args = parser.parse_args()
    config, provenance = prepare(args.source_map, args.output, distance_m=args.distance,
                                 margin_m=args.margin, domain=args.domain, port=args.port)
    print(json.dumps({'config': str(Path(args.output).resolve() / 'panel-config.json'),
                      'waypoints': config['waypoints'], 'route': provenance['route']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
