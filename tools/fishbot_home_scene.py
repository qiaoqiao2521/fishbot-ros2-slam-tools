#!/usr/bin/env python3
"""Complete only unknown map cells for a private, explicitly synthetic home demo.

The occupancy image is the sole physical wall source. No captured map, coordinates,
robot pose override, or recognition result is embedded in this public generator.
"""
from __future__ import annotations
import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, binary_dilation
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROBOT = ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/fishbot_inspection.xml'
GEOMETRY_PATH = ROOT / 'tools/config/fishbot_model_geometry.yaml'
_GEOMETRY = yaml.safe_load(GEOMETRY_PATH.read_text())
_POINTS = np.asarray(_GEOMETRY['footprint']['points_m'], dtype=float)
_PADDING = float(_GEOMETRY['footprint']['padding_m'])
if _POINTS.ndim != 2 or _POINTS.shape[1] != 2 or not np.isfinite(_POINTS).all() or not math.isfinite(_PADDING) or _PADDING < 0:
    raise ValueError('Invalid authoritative FishBot footprint geometry')
BODY_HALF_LENGTH, BODY_HALF_WIDTH = np.max(np.abs(_POINTS), axis=0) + _PADDING


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_map(path):
    path = Path(path).expanduser().resolve()
    info = yaml.safe_load(path.read_text())
    if not isinstance(info, dict) or info.get('mode', 'trinary') != 'trinary':
        raise ValueError('Only trinary occupancy maps are supported')
    resolution = float(info['resolution'])
    origin = list(map(float, info['origin']))
    if not math.isfinite(resolution) or not .01 <= resolution <= .20:
        raise ValueError('Map resolution must be finite and between .01 and .20 m')
    if len(origin) != 3 or not all(map(math.isfinite, origin)) or abs(origin[2]) > 1e-10:
        raise ValueError('This generator requires a finite, axis-aligned map origin')
    image_path = (path.parent / info['image']).resolve()
    raw = np.asarray(Image.open(image_path))
    if raw.ndim != 2 or raw.dtype != np.uint8 or min(raw.shape) < 3:
        raise ValueError('Map must be a nonempty 8-bit grayscale image')
    negate = int(info.get('negate', 0))
    free, occupied = float(info.get('free_thresh', .196)), float(info.get('occupied_thresh', .65))
    if negate not in (0, 1) or not 0 <= free < occupied <= 1:
        raise ValueError('Invalid map thresholds or negate flag')
    # Match Nav2 1.3.13 map_io.cpp: float32 normalization and inclusive thresholds.
    probability = raw.astype(np.float32) / np.float32(255)
    if not negate:
        probability = 1 - probability
    known_free, known_occupied = probability <= free, probability >= occupied
    return info, raw, known_free, known_occupied, path, image_path


def rectangles(mask):
    """Disjoint grid rectangles whose union is exactly the True cells."""
    active, result = {}, []
    for row in range(mask.shape[0] + 1):
        runs = []
        if row < mask.shape[0]:
            padded = np.pad(mask[row].astype(np.int8), (1, 1))
            starts, ends = np.flatnonzero(np.diff(padded) == 1), np.flatnonzero(np.diff(padded) == -1)
            runs = list(zip(map(int, starts), map(int, ends)))
        now = set(runs)
        for key in list(active):
            if key not in now:
                result.append((active.pop(key), row, key[0], key[1]))
        for key in runs:
            active.setdefault(key, row)
    return result


def reachable_cells(safe, start):
    distance = np.full(safe.shape, -1, dtype=np.int32)
    if not (0 <= start[0] < safe.shape[0] and 0 <= start[1] < safe.shape[1] and safe[start]):
        return distance
    queue = deque([start]); distance[start] = 0
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < safe.shape[0] and 0 <= nx < safe.shape[1] and safe[ny, nx] and distance[ny, nx] < 0:
                distance[ny, nx] = distance[y, x] + 1
                queue.append((ny, nx))
    return distance


class Grid:
    def __init__(self, occupied, known, origin, resolution):
        self.occupied, self.known = occupied, known
        self.origin, self.resolution = list(origin), resolution

    def cell(self, x, y):
        r = self.resolution
        return (self.occupied.shape[0]-1-math.floor((y-self.origin[1])/r), math.floor((x-self.origin[0])/r))

    def xy(self, row, col):
        r = self.resolution
        return [self.origin[0]+(col+.5)*r, self.origin[1]+(self.occupied.shape[0]-row-.5)*r]

    def region(self, x, y, half_x, half_y):
        r0, c0 = self.cell(x-half_x, y+half_y)
        r1, c1 = self.cell(x+half_x-1e-9, y-half_y+1e-9)
        return r0, r1+1, c0, c1+1

    def valid_region(self, rect):
        r0, r1, c0, c1 = rect
        return 0 <= r0 < r1 <= self.occupied.shape[0] and 0 <= c0 < c1 <= self.occupied.shape[1]

    def clearance(self):
        return distance_transform_edt(~self.occupied)*self.resolution - self.resolution/math.sqrt(2)

    def safe_centers(self, yaw=0.):
        """Exact separating-axis overlap of a padded rectangle and occupied cells."""
        r = self.resolution
        radius = math.hypot(BODY_HALF_LENGTH, BODY_HALF_WIDTH) + r/math.sqrt(2)
        n = math.ceil(radius/r)
        yy, xx = np.mgrid[-n:n+1, -n:n+1]*r
        c, s = math.cos(yaw), math.sin(yaw)
        a, b, h = BODY_HALF_LENGTH, BODY_HALF_WIDTH, r/2
        # Touching the padded boundary retains 5 mm of physical clearance.
        kernel = ((abs(xx) < abs(c)*a+abs(s)*b+h-1e-9) &
                  (abs(yy) < abs(s)*a+abs(c)*b+h-1e-9) &
                  (abs(xx*c+yy*s) < a+h*(abs(c)+abs(s))-1e-9) &
                  (abs(-xx*s+yy*c) < b+h*(abs(c)+abs(s))-1e-9))
        return ~binary_dilation(self.occupied, structure=kernel, border_value=1)

    def pose_is_free(self, pose):
        """Test continuous XY, not only the nearest cell center, at the actual heading."""
        x, y, yaw = map(float, pose)
        if not all(map(math.isfinite, (x, y, yaw))): return False
        c, s = math.cos(yaw), math.sin(yaw)
        a, b, h = BODY_HALF_LENGTH, BODY_HALF_WIDTH, self.resolution/2
        ex, ey = abs(c)*a+abs(s)*b, abs(s)*a+abs(c)*b
        rect = self.region(x, y, ex, ey)
        if not self.valid_region(rect): return False
        r0, r1, c0, c1 = rect
        for row, col in zip(*np.nonzero(self.occupied[r0:r1, c0:c1])):
            wx, wy = self.xy(row+r0, col+c0); dx, dy = wx-x, wy-y
            if (abs(dx) < ex+h-1e-9 and abs(dy) < ey+h-1e-9 and
                abs(dx*c+dy*s) < a+h*(abs(c)+abs(s))-1e-9 and
                abs(-dx*s+dy*c) < b+h*(abs(c)+abs(s))-1e-9):
                return False
        return True

    def reachable(self):
        """Geometric center connectivity with the physical rectangle in cardinal views.

        This checks scene topology, not differential-drive trajectories or turn feasibility.
        Goal poses are separately checked at their exact requested heading. Nav2 must
        actually traverse the inherited narrow opening during runtime acceptance.
        """
        safe = self.safe_centers(0.) | self.safe_centers(math.pi/2)
        return reachable_cells(safe, self.cell(0., 0.))

    def bounds(self, rect):
        r0, r1, c0, c1 = rect; r = self.resolution
        xmin = self.origin[0]+c0*r; xmax = self.origin[0]+c1*r
        ymin = self.origin[1]+(self.occupied.shape[0]-r1)*r
        ymax = self.origin[1]+(self.occupied.shape[0]-r0)*r
        return xmin, ymin, xmax, ymax


def pose_toward(x, y, target):
    return [round(x, 6), round(y, 6), math.atan2(target[1]-y, target[0]-x)]


def choose_layout(grid):
    """Find an unknown annex reachable from spawn, never clear measured obstacles."""
    safe = grid.safe_centers()
    distance = grid.reachable()
    if not grid.pose_is_free([0., 0., 0.]) or distance[grid.cell(0, 0)] < 0:
        raise ValueError('Spawn [0,0,0] lacks full-footprint clearance in the measured map')
    # Relative synthetic fixture dimensions, not captured room coordinates.
    candidates = []
    step = max(1, round(.20/grid.resolution))
    for row in range(0, safe.shape[0], step):
        for col in range(0, safe.shape[1], step):
            if distance[row, col] < 0 or grid.known[row, col]:
                continue
            x, y = grid.xy(row, col)
            region = grid.region(x+.1, y, 1.55, 1.15)
            if not grid.valid_region(region):
                continue
            r0, r1, c0, c1 = region
            if grid.known[r0:r1, c0:c1].any() or grid.occupied[r0:r1, c0:c1].any():
                continue
            candidates.append((int(distance[row, col]), row, col))
    for _, row, col in sorted(candidates):
        x, y = grid.xy(row, col)
        objects = [
            {'id': 'inspection_green', 'center': [x-.75, y+.70], 'half': [.20, .075], 'texture': 'green'},
            {'id': 'toolshelf', 'center': [x+.75, y+.70], 'half': [.20, .075], 'texture': 'red_box'},
            {'id': 'inspection_empty', 'center': [x-.75, y-.75], 'half': [.20, .075], 'texture': 'empty'},
            {'id': 'tool_occluder', 'center': [x+.47, y+.10], 'half': [.30, .075], 'texture': None},
        ]
        occupied = grid.occupied.copy()
        for obj in objects:
            obj['rect'] = grid.region(*obj['center'], *obj['half'])
            r0, r1, c0, c1 = obj['rect']
            occupied[r0:r1, c0:c1] = True
            bounds = grid.bounds(obj['rect'])
            obj['center'] = [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2]
        views = {
            'green': pose_toward(x-.75, y-.15, objects[0]['center']),
            'tool_hidden': pose_toward(x+.20, y-.50, objects[1]['center']),
            'tool_visible': pose_toward(x+1.40, y-.50, objects[1]['center']),
            'empty': pose_toward(x-.75, y+.15, objects[2]['center']),
        }
        trial = Grid(occupied, grid.known, grid.origin, grid.resolution)
        reach = trial.reachable()
        if all(reach[trial.cell(*pose[:2])] >= 0 and trial.pose_is_free(pose) for pose in views.values()):
            grid.occupied = occupied
            return objects, views, reach
    raise ValueError('No reachable all-unknown annex fits the synthetic fixtures; increase --padding')


def choose_dock(grid, reach):
    best = None
    for angle in (0., math.pi/2, math.pi, -math.pi/2):
        heading = [math.cos(angle), math.sin(angle)]
        staging = [.55*heading[0], .55*heading[1], math.atan2(-heading[1], -heading[0])]
        if any(not grid.pose_is_free([staging[0]*f, staging[1]*f, staging[2]]) or reach[grid.cell(staging[0]*f, staging[1]*f)] < 0 for f in np.linspace(0, 1, 20)):
            continue
        for distance in np.arange(.15, 1., grid.resolution/2):
            cell = grid.cell(-heading[0]*distance, -heading[1]*distance)
            if grid.occupied[cell]:
                if grid.known[cell] and (best is None or distance < best[0]):
                    best = (distance, cell, staging)
                break
    if best is None:
        raise ValueError('No measured wall and safe straight staging approach near spawn for dock')
    _, cell, staging = best
    # Mark an existing occupied wall rectangle: no new contact geometry in measured free cells.
    rect = next(r for r in rectangles(grid.occupied & grid.known)
                if r[0] <= cell[0] < r[1] and r[2] <= cell[1] < r[3])
    pose = {'x': 0., 'y': 0., 'yaw': staging[2]}
    return {'id': 'home_dock', 'type': 'home_charging_dock', 'frame': 'map', 'pose': pose,
            'staging_pose': dict(zip(('x', 'y', 'yaw'), staging)),
            'truth_to_dock_frame': {'x': 0., 'y': 0., 'yaw': 0.},
            'contact': {'center': {'x': 0., 'y': 0.}, 'half_length': .12, 'half_width': .12,
                        'yaw_tolerance_rad': .12, 'max_linear_mps': .015, 'max_angular_rps': .03, 'dwell_s': 1.},
            'charge_model': {'initial_soc': .36, 'low_soc': .28, 'resume_soc': .80, 'capacity_ah': 2.,
                             'idle_discharge_a': .1, 'linear_discharge_a_per_mps': 3.,
                             'angular_discharge_a_per_rps': .3, 'charging_current_a': 2.,
                             'discharge_time_scale': 45., 'charge_time_scale': 288.},
            'model_scope': 'synthetic pose-speed-dwell contact and accelerated battery; not real charging hardware',
            'marker_grid_rectangle': list(rect)}, rect


def prepare_output(output):
    output = Path(output).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be a new or empty directory; source maps are never overwritten')
    probe = output
    while not probe.exists():
        probe = probe.parent
    result = subprocess.run(['git', '-C', str(probe), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if result.returncode == 0:
        repository = Path(result.stdout.strip())
        ignored = subprocess.run(['git', '-C', str(repository), 'check-ignore', '-q', str(output)], capture_output=True)
        if ignored.returncode:
            raise ValueError('Private scene output inside Git must use an ignored directory')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    return output


def panel_texture(path, state):
    image = Image.new('RGB', (256, 256), (8, 28, 242)); draw = ImageDraw.Draw(image)
    draw.rectangle((26, 26, 229, 229), fill=(3, 3, 3))
    if state == 'green':
        draw.ellipse((78, 78, 178, 178), fill=(6, 242, 15))
    elif state == 'red_box':
        draw.rectangle((74, 86, 181, 170), fill=(242, 8, 5))
    elif state == 'dock':
        draw.rectangle((0, 0, 255, 255), fill=(12, 210, 215))
        draw.rectangle((24, 24, 231, 231), fill=(8, 8, 8))
        draw.line((128, 60, 128, 195), fill=(250, 225, 20), width=25)
        draw.line((60, 128, 195, 128), fill=(250, 225, 20), width=25)
    image.save(path)


def write_scene(grid, objects, dock_rect, robot, output):
    root = ET.Element('mujoco', model='fishbot_private_map_completion')
    ET.SubElement(root, 'include', file=str(robot))
    visual = ET.SubElement(root, 'visual')
    ET.SubElement(visual, 'global', offwidth='640', offheight='480', azimuth='110', elevation='-35')
    ET.SubElement(visual, 'rgba', rangefinder='1 1 0.1 0')
    ET.SubElement(visual, 'headlight', ambient='.35 .35 .35', diffuse='.6 .6 .6')
    asset = ET.SubElement(root, 'asset')
    ET.SubElement(asset, 'texture', name='floor_grid', type='2d', builtin='checker', width='256', height='256', rgb1='.65 .67 .7', rgb2='.8 .82 .85')
    ET.SubElement(asset, 'material', name='floor_material', texture='floor_grid', texrepeat='16 16', texuniform='true')
    for state in ('green', 'red_box', 'empty', 'dock'):
        panel_texture(output / f'panel_{state}.png', state)
        ET.SubElement(asset, 'texture', name=f'tex_{state}', type='2d', file=f'panel_{state}.png')
        ET.SubElement(asset, 'material', name=f'mat_{state}', texture=f'tex_{state}', texuniform='false', specular='0', emission='.25')
    world = ET.SubElement(root, 'worldbody')
    ET.SubElement(world, 'light', name='home_light', pos='0 0 6', dir='0 0 -1', diffuse='.7 .7 .7')
    ET.SubElement(world, 'geom', name='floor', type='plane', size='20 20 .1', material='floor_material')
    remaining = grid.occupied.copy()
    special = [*objects, {'id': 'dock_marker', 'rect': dock_rect, 'texture': 'dock'}]
    physical_rectangles = []
    def emit(name, rect, texture=None, height=.55):
        xmin, ymin, xmax, ymax = grid.bounds(rect)
        attributes = {'name': name, 'type': 'box',
                      'pos': f'{(xmin+xmax)/2:.9f} {(ymin+ymax)/2:.9f} {height/2:.9f}',
                      'size': f'{(xmax-xmin)/2:.9f} {(ymax-ymin)/2:.9f} {height/2:.9f}'}
        if texture:
            # Put the texture on the box's local Z face, rotated onto world +/-Y.
            # Swapping Y/Z half-sizes keeps the occupied planar rectangle identical.
            attributes.update(material=f'mat_{texture}', euler='1.5707963267948966 0 0',
                              size=f'{(xmax-xmin)/2:.9f} {height/2:.9f} {(ymax-ymin)/2:.9f}')
        else:
            attributes['rgba'] = '.68 .69 .72 1'
        ET.SubElement(world, 'geom', **attributes)
        physical_rectangles.append({'name': name, 'grid_rectangle': list(rect), 'bounds_m': [xmin, ymin, xmax, ymax]})
    for obj in special:
        r0, r1, c0, c1 = obj['rect']; remaining[r0:r1, c0:c1] = False
        emit(obj['id'], obj['rect'], obj.get('texture'), .70 if obj['id'] == 'tool_occluder' else .55)
    for i, rect in enumerate(rectangles(remaining)):
        emit(f'occupancy_wall_{i}', rect)
    # Named diagnostics actor remains outside the closed map, never on a mission route.
    actor = ET.SubElement(world, 'body', name='moving_obstacle', pos=f'{grid.origin[0]-1} {grid.origin[1]-1} .222')
    ET.SubElement(actor, 'freejoint', name='moving_obstacle_free_joint')
    ET.SubElement(actor, 'geom', name='moving_obstacle_collision', type='box', size='.18 .18 .22', mass='2', rgba='.4 .4 .4 1')
    ET.indent(root)
    ET.ElementTree(root).write(output / 'scene.xml', encoding='utf-8', xml_declaration=True)
    return physical_rectangles


def overview(grid, source_free, source_occupied, objects, views, dock, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    image = np.full((*grid.occupied.shape, 3), [224, 238, 252], dtype=np.uint8)
    image[grid.occupied] = [53, 97, 148]
    image[source_free] = [250, 250, 250]
    image[source_occupied] = [30, 30, 30]
    bounds = grid.bounds((0, grid.occupied.shape[0], 0, grid.occupied.shape[1]))
    fig, ax = plt.subplots(figsize=(11, 10))
    ax.imshow(image, extent=[bounds[0], bounds[2], bounds[1], bounds[3]], interpolation='nearest')
    for name, pose in views.items():
        x, y, yaw = pose
        ax.arrow(x, y, .23*math.cos(yaw), .23*math.sin(yaw), width=.015, color='#a3247f', length_includes_head=True)
        ax.text(x+.07, y-.08, name, fontsize=9, color='#6b1452')
    for obj in objects:
        x, y = obj['center']; ax.text(x, y+.16, obj['id'], fontsize=8, ha='center')
    ax.plot(0, 0, 'o', color='#d56800'); ax.text(.05, .1, 'spawn / dock', color='#994800')
    stage = dock['staging_pose']; ax.plot(stage['x'], stage['y'], 'x', color='#d56800')
    ax.set(xlabel='map x / m', ylabel='map y / m', title='Measured occupancy + explicitly assumed simulation completion')
    ax.set_aspect('equal'); ax.grid(alpha=.15)
    ax.legend(handles=[Patch(color=np.array(c)/255, label=l) for c, l in
                       [([250,250,250], 'measured free (unchanged)'), ([30,30,30], 'measured occupied (unchanged)'),
                        ([224,238,252], 'assumed free'), ([53,97,148], 'assumed occupied')]], loc='upper left', fontsize=8)
    fig.tight_layout(); fig.savefig(output / 'overview.png', dpi=150); plt.close(fig)


def generate(source_map, output_dir, robot_model=DEFAULT_ROBOT, padding=3.):
    info, raw, free, occupied, source, image_path = load_map(source_map)
    if not math.isfinite(padding) or not 1 <= padding <= 8:
        raise ValueError('Padding must be between 1 and 8 m')
    robot = Path(robot_model).expanduser().resolve()
    if not robot.is_file():
        raise ValueError('Camera robot model does not exist')
    resolution = float(info['resolution']); pad = math.ceil(padding/resolution)
    known_free = np.pad(free, pad); known_occupied = np.pad(occupied, pad)
    known = known_free | known_occupied
    completed = known_occupied.copy()
    completed[[0, -1], :] = True; completed[:, [0, -1]] = True
    origin = [float(info['origin'][0])-pad*resolution, float(info['origin'][1])-pad*resolution, 0.]
    grid = Grid(completed, known, origin, resolution)
    objects, views, reach = choose_layout(grid)
    dock, dock_rect = choose_dock(grid, reach)
    if not np.array_equal(grid.occupied[known], known_occupied[known]):
        raise AssertionError('Measured cells changed')
    negate = int(info.get('negate', 0)); free_pixel, occupied_pixel = (255, 0) if negate == 0 else (0, 255)
    pixels = np.where(grid.occupied, occupied_pixel, free_pixel).astype(np.uint8)
    original_area = pixels[pad:pad+raw.shape[0], pad:pad+raw.shape[1]]
    original_area[free | occupied] = raw[free | occupied]
    output = prepare_output(output_dir)
    Image.fromarray(pixels).save(output / 'map.pgm')
    mask = np.where(known, 0, np.where(grid.occupied, 255, 127)).astype(np.uint8)
    Image.fromarray(mask).save(output / 'assumption_mask.pgm')
    map_info = {**info, 'image': 'map.pgm', 'origin': origin, 'mode': 'trinary'}
    (output / 'map.yaml').write_text(yaml.safe_dump(map_info, sort_keys=False))
    walls = write_scene(grid, objects, dock_rect, robot, output)
    stations = [
        {'id': 'inspection_green', 'name': 'Green indicator station', 'goal': views['green'], 'target': 'indicator'},
        {'id': 'inspection_red', 'name': 'Tool shelf indicator station', 'goal': views['tool_visible'], 'target': 'indicator'},
        {'id': 'inspection_empty', 'name': 'Empty indicator station', 'goal': views['empty'], 'target': 'indicator'},
    ]
    places = {
        'toolshelf': {'id': 'toolshelf', 'name': '工具架', 'aliases': ['工具架', '工具区', 'tool shelf'],
                     'views': [views['tool_hidden'], views['tool_visible']], 'target': 'red_box', 'question': '工具架上有没有红色盒子'},
        'observation_point': {'id': 'observation_point', 'name': '观察点', 'aliases': ['观察点', '第二观察位'],
                              'views': [views['tool_visible']], 'target': 'red_box', 'question': '从第二观察位检查红色盒子'},
        'entrance_indicator': {'id': 'entrance_indicator', 'name': '门口指示灯', 'aliases': ['门口指示灯', '门口', '指示灯'],
                               'views': [views['green']], 'target': 'indicator', 'question': '检查门口指示灯'},
    }
    semantic = {'schema_version': 1, 'frame': 'map', 'scope': 'private measured map with explicit synthetic unknown completion',
                'spawn': [0., 0., 0.], 'home': [0., 0., 0.], 'stations': stations, 'places': places, 'dock': dock,
                'camera': {'topic': '/inspection/camera/image_raw', 'frame': 'inspection_camera_optical_frame',
                           'encoding': 'rgb8', 'width': 640, 'height': 480},
                'recognition_boundary': 'Targets describe requested tasks, never observed results. Classify only fresh rendered RGB.',
                'map': 'map.yaml', 'scene': 'scene.xml', 'assumption_mask': 'assumption_mask.pgm'}
    provenance = {'schema_version': 1, 'source_yaml': str(source), 'source_image': str(image_path),
                  'source_yaml_sha256': digest(source), 'source_image_sha256': digest(image_path),
                  'robot_model': str(robot), 'robot_model_sha256': digest(robot),
                  'footprint_geometry': str(GEOMETRY_PATH), 'footprint_geometry_sha256': digest(GEOMETRY_PATH),
                  'source_shape_rows_cols': list(raw.shape), 'source_offset_rows_cols': [pad, pad],
                  'resolution_m': resolution, 'origin': origin,
                  'source_known_free_cells': int(free.sum()), 'source_known_occupied_cells': int(occupied.sum()),
                  'source_known_cells_preserved_exactly': True,
                  'assumption_mask_legend': {'0': 'unchanged measured free/occupied', '127': 'assumed free', '255': 'assumed occupied'},
                  'completion_policy': 'Unknown cells and exterior padding become open synthetic space, bounded by one-cell walls. New fixtures occupy only unknown cells.',
                  'assumed_free_cells': int((mask == 127).sum()), 'assumed_occupied_cells': int((mask == 255).sum()),
                  'physics_policy': 'All occupied grid cells are partitioned exactly into axis-aligned wall boxes. Textures change appearance only.',
                  'robot_padded_half_size_m': [BODY_HALF_LENGTH, BODY_HALF_WIDTH], 'reachable_goal_check': 'cardinal footprint center connectivity; not differential-drive trajectory acceptance',
                  'physical_wall_rectangles': walls, 'artifacts_sha256': {}}
    semantic['provenance'] = {k: provenance[k] for k in (
        'source_yaml_sha256', 'source_image_sha256', 'source_known_free_cells',
        'source_known_occupied_cells', 'source_known_cells_preserved_exactly',
        'assumption_mask_legend', 'completion_policy', 'physics_policy',
        'assumed_free_cells', 'assumed_occupied_cells', 'reachable_goal_check')}
    semantic['provenance']['details_file'] = 'provenance.json'
    (output / 'semantic.json').write_text(json.dumps(semantic, ensure_ascii=False, indent=2)+'\n')
    overview(grid, known_free, known_occupied, objects, views, dock, output)
    for path in output.iterdir():
        if path.is_file(): provenance['artifacts_sha256'][path.name] = digest(path)
    (output / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2)+'\n')
    (output / 'README.txt').write_text(
        'PRIVATE SIMULATION FIXTURE — NOT A RECONSTRUCTION OF UNOBSERVED REAL SPACE\n'
        'Original known free/occupied pixels are preserved exactly at the recorded offset.\n'
        'Unknown cells and exterior padding are hypothetical; see assumption_mask.pgm and provenance.json.\n'
        'Map occupied cells and MuJoCo wall boxes have the same exact planar union.\n'
        'Named targets, colors, dock contact, battery and charging are synthetic demonstrations.\n'
        'No visual observation or real-hardware acceptance is generated by this scene builder.\n')
    return semantic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-map', '--map', dest='source_map', required=True, type=Path)
    parser.add_argument('--output-dir', '--output', dest='output_dir', required=True, type=Path)
    parser.add_argument('--robot-model', type=Path, default=DEFAULT_ROBOT)
    parser.add_argument('--padding', type=float, default=3.)
    args = parser.parse_args()
    generate(args.source_map, args.output_dir, args.robot_model, args.padding)
    print(json.dumps({'output_dir': str(args.output_dir.resolve()), 'result': 'generated',
                      'recognition': 'not run', 'navigation': 'not run'}))


if __name__ == '__main__':
    main()
