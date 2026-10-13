"""Software-only map rules and local route/run persistence; no ROS dependency.

Mask cells describe the rule geometry, with one cell half-diagonal allowance for
rasterization, including rotated map origins. Nav2 handles the robot footprint
and inflation; adding it here would count the same physical outline twice. Goal
validation still checks the existing circular 0.13 m footprint. The published
mask is axis aligned because Jazzy KeepoutFilter ignores mask yaw.
"""
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

ROBOT_RADIUS = 0.13
MAX_ZONES = 64
MAX_ROUTES = 100
MAX_RUNS = 50
ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


class MapRulesError(Exception):
    def __init__(self, message, status=400, issue=None):
        super().__init__(message)
        self.status = status
        self.issue = issue


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MapRulesError(f'{label} must be finite')
    return float(value)


def integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MapRulesError(f'{label} must be a nonnegative integer')
    return value


def valid_id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise MapRulesError('ID must contain 1–64 ASCII letters, digits, underscores or hyphens')
    return value


def map_identity(grid):
    encoded = json.dumps({key: grid[key] for key in ('width', 'height', 'resolution', 'origin', 'data')},
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def world_to_grid(x, y, grid):
    ox, oy, yaw = grid['origin']
    dx, dy = x-ox, y-oy
    return math.cos(yaw)*dx+math.sin(yaw)*dy, -math.sin(yaw)*dx+math.cos(yaw)*dy


def grid_to_world(x, y, grid):
    ox, oy, yaw = grid['origin']
    return ox+math.cos(yaw)*x-math.sin(yaw)*y, oy+math.sin(yaw)*x+math.cos(yaw)*y


def point_in_map(point, grid):
    x, y = world_to_grid(point['x'], point['y'], grid)
    return (-1e-9 <= x <= grid['width']*grid['resolution']+1e-9
            and -1e-9 <= y <= grid['height']*grid['resolution']+1e-9)


def validate_zones(raw, grid):
    if not isinstance(raw, list) or len(raw) > MAX_ZONES:
        raise MapRulesError(f'Provide at most {MAX_ZONES} zones')
    zones, ids = [], set()
    for item in raw:
        if not isinstance(item, dict) or set(item)-{'id', 'kind', 'points', 'width'}:
            raise MapRulesError('Zone requires id, kind, points and optional wall width')
        identity = valid_id(item.get('id'))
        if identity in ids:
            raise MapRulesError('Zone IDs must be unique')
        ids.add(identity)
        kind = item.get('kind')
        if kind not in {'wall', 'no_go'}:
            raise MapRulesError('Zone kind must be wall or no_go')
        raw_points = item.get('points')
        if not isinstance(raw_points, list) or len(raw_points) != (2 if kind == 'wall' else 4):
            raise MapRulesError('A wall needs two points; a no_go rectangle needs four points')
        points = []
        for point in raw_points:
            if not isinstance(point, dict) or set(point) != {'x', 'y'}:
                raise MapRulesError('Zone points require exactly x and y')
            parsed = {key: number(point[key], f'zone point {key}') for key in ('x', 'y')}
            if not point_in_map(parsed, grid):
                raise MapRulesError('Zone point is outside the map')
            points.append(parsed)
        zone = {'id': identity, 'kind': kind, 'points': points}
        if kind == 'wall':
            if math.hypot(points[1]['x']-points[0]['x'], points[1]['y']-points[0]['y']) < 1e-6:
                raise MapRulesError('Wall endpoints must differ')
            width = number(item.get('width', 0.02), 'wall width')
            if not 0.01 <= width <= 0.5:
                raise MapRulesError('Wall width must be between 0.01 and 0.5 metres')
            zone['width'] = width
        else:
            if 'width' in item:
                raise MapRulesError('width is only valid for a wall')
            xs, ys = sorted({p['x'] for p in points}), sorted({p['y'] for p in points})
            if (len(xs) != 2 or len(ys) != 2 or xs[1]-xs[0] < 1e-6 or ys[1]-ys[0] < 1e-6
                    or {(p['x'], p['y']) for p in points} != {(x, y) for x in xs for y in ys}):
                raise MapRulesError('no_go must be a nonzero world-axis-aligned rectangle')
            # Normalize corner order so editor input order cannot form a bow tie.
            zone['points'] = [{'x': xs[0], 'y': ys[0]}, {'x': xs[1], 'y': ys[0]},
                              {'x': xs[1], 'y': ys[1]}, {'x': xs[0], 'y': ys[1]}]
        zones.append(zone)
    return zones


def distance_to_zone(x, y, zone):
    points = zone['points']
    if zone['kind'] == 'no_go':
        xs, ys = [p['x'] for p in points], [p['y'] for p in points]
        return math.hypot(max(min(xs)-x, 0., x-max(xs)), max(min(ys)-y, 0., y-max(ys)))
    a, b = points
    dx, dy = b['x']-a['x'], b['y']-a['y']
    fraction = max(0., min(1., ((x-a['x'])*dx+(y-a['y'])*dy)/(dx*dx+dy*dy)))
    return max(0., math.hypot(x-a['x']-fraction*dx, y-a['y']-fraction*dy)-zone['width']/2)


def require_outside_rules(point, zones, radius=ROBOT_RADIUS):
    for index, zone in enumerate(zones):
        clearance = distance_to_zone(point['x'], point['y'], zone)
        if clearance <= radius+1e-9:
            # Describe the existing rejection; do not change its geometry or threshold.
            x, y = point['x'], point['y']
            if zone['kind'] == 'no_go':
                xs, ys = [p['x'] for p in zone['points']], [p['y'] for p in zone['points']]
                blocking = {'x': max(min(xs), min(x, max(xs))),
                            'y': max(min(ys), min(y, max(ys)))}
            else:
                a, b = zone['points']
                dx, dy = b['x']-a['x'], b['y']-a['y']
                fraction = max(0., min(1., ((x-a['x'])*dx+(y-a['y'])*dy)/(dx*dx+dy*dy)))
                bx, by = a['x']+fraction*dx, a['y']+fraction*dy
                distance = math.hypot(x-bx, y-by)
                if distance <= zone['width']/2:
                    blocking = {'x': x, 'y': y}
                else:
                    scale = zone['width']/2/distance
                    blocking = {'x': bx+(x-bx)*scale, 'y': by+(y-by)*scale}
            issue = {'kind': 'map_rule', 'point': dict(point), 'rule_id': zone['id'],
                     'rule_kind': zone['kind'], 'rule_index': index+1,
                     'clearance_m': clearance, 'required_clearance_m': radius,
                     'shortfall_m': max(0., radius-clearance), 'blocking_point': blocking}
            raise MapRulesError(f'Waypoint footprint intersects map rule {zone["id"]}', issue=issue)


def build_mask(grid, zones, radius=0.0):
    res = grid['resolution']
    corners = [grid_to_world(x, y, grid) for x in (0., grid['width']*res)
               for y in (0., grid['height']*res)]
    ox = math.floor(min(p[0] for p in corners)/res+1e-9)*res
    oy = math.floor(min(p[1] for p in corners)/res+1e-9)*res
    width = math.ceil((max(p[0] for p in corners)-ox)/res-1e-9)
    height = math.ceil((max(p[1] for p in corners)-oy)/res-1e-9)
    if not 0 < width*height <= 4_000_000:
        raise MapRulesError('Axis-aligned mask exceeds the supported map size')
    mask = {'width': width, 'height': height, 'resolution': res,
            'origin': [ox, oy, 0.], 'data': [0]*(width*height)}
    half_diagonal = res/math.sqrt(2.)
    for zone in zones:
        padding = radius+half_diagonal+(zone.get('width', 0.)/2)
        xs, ys = [p['x'] for p in zone['points']], [p['y'] for p in zone['points']]
        c0 = max(0, math.floor((min(xs)-padding-ox)/res))
        c1 = min(width-1, math.floor((max(xs)+padding-ox)/res))
        r0 = max(0, math.floor((min(ys)-padding-oy)/res))
        r1 = min(height-1, math.floor((max(ys)+padding-oy)/res))
        for row in range(r0, r1+1):
            for col in range(c0, c1+1):
                x, y = ox+(col+.5)*res, oy+(row+.5)*res
                if distance_to_zone(x, y, zone) <= radius+half_diagonal+1e-9:
                    mask['data'][row*width+col] = 100
    return mask


def grid_value_at(x, y, grid):
    gx, gy = world_to_grid(x, y, grid)
    col, row = math.floor(gx/grid['resolution']), math.floor(gy/grid['resolution'])
    if 0 <= col < grid['width'] and 0 <= row < grid['height']:
        return grid['data'][row*grid['width']+col]
    return None


def costmap_matches_mask(costmap, mask, previous=None, source_grid=None):
    """Read back changed cells; unknown cost 255 never confirms a keepout cell.

    Local rolling maps can cover only part of the mask. Global coverage of every
    marked cell is checked separately by the caller. Removed cells are checked
    only where the static source map is known free; live obstacles can keep the
    result ambiguous, in which case the caller must retain 'published'.
    """
    marked = cleared = 0
    for row in range(costmap['height']):
        for col in range(costmap['width']):
            x, y = grid_to_world((col+.5)*costmap['resolution'],
                                 (row+.5)*costmap['resolution'], costmap)
            expected = grid_value_at(x, y, mask)
            value = costmap['data'][row*costmap['width']+col]
            if expected == 100:
                marked += 1
                if value != 254:
                    return False, marked, cleared
            elif (previous is not None and grid_value_at(x, y, previous) == 100
                  and source_grid is not None and grid_value_at(x, y, source_grid) == 0):
                cleared += 1
                if value == 254 or value == 255:
                    return False, marked, cleared
    return True, marked, cleared


def validate_route(route, grid, identity=None):
    if not isinstance(route, dict) or set(route) != {
            'id', 'name', 'map_id', 'revision', 'waypoints', 'return_home'}:
        raise MapRulesError('Malformed stored route')
    valid_id(route['id'])
    if not isinstance(route['name'], str) or not 1 <= len(route['name'].strip()) <= 80:
        raise MapRulesError('Route name must contain 1–80 characters')
    if route['map_id'] != (identity or map_identity(grid)):
        raise MapRulesError('Stored route belongs to another map')
    integer(route['revision'], 'route revision')
    if not isinstance(route['return_home'], bool):
        raise MapRulesError('return_home must be boolean')
    points = route['waypoints']
    if not isinstance(points, list) or not 1 <= len(points) <= 12:
        raise MapRulesError('A route requires 1–12 waypoints')
    for point in points:
        if not isinstance(point, dict) or set(point) != {'x', 'y', 'yaw'}:
            raise MapRulesError('Route waypoint must contain x, y and yaw')
        for key in point:
            number(point[key], f'route waypoint {key}')
        if not point_in_map(point, grid):
            raise MapRulesError('Route waypoint is outside the map')
    return copy.deepcopy(route)


class MapRulesStore:
    """One content-addressed map per document, with atomic writes and CAS rules."""
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.map_id = ''
        self.grid = None
        self.document = None
        self.error = None
        self.file_signature = None

    def bind(self, grid):
        identity = map_identity(grid)
        if identity == self.map_id:
            return False
        self.map_id, self.grid, self.error = identity, copy.deepcopy(grid), None
        self.file_signature = None
        self.document = {'schema': 1, 'map_id': identity, 'revision': 0,
                         'zones': [], 'routes': [], 'runs': []}
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.document = self._read() or self.document
            if any(run['status'] in {'running', 'canceling'} for run in self.document['runs']):
                def interrupted(doc):
                    for run in doc['runs']:
                        if run['status'] in {'running', 'canceling'}:
                            run.update(status='unknown', finished_at=None,
                                       message='桥接重启，旧任务实际终态未知；不会恢复或重发')
                            run.setdefault('events', []).append({'time_unix': time.time(),
                                'sim_time': None, 'type': 'bridge_restart', 'status': 'unknown'})
                self._transaction(interrupted)
            self.file_signature = self._signature()
        except (OSError, ValueError, MapRulesError) as error:
            self.error = f'Map rules persistence unavailable: {error}'
        return True

    @property
    def filename(self):
        return self.directory / f'{self.map_id}.json'

    def _signature(self):
        try:
            stat = self.filename.stat()
            return stat.st_ino, stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None

    def refresh(self):
        """Refresh only changed local data; callers own all ROS publication."""
        self.require_available()
        try:
            signature = self._signature()
            if signature == self.file_signature:
                return False
            with (self.directory / f'{self.map_id}.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                doc = self._read()
                if doc is None:
                    raise MapRulesError('Persistence document disappeared', 503)
                changed = (doc['map_id'], doc['revision']) != (self.document['map_id'], self.document['revision'])
                self.document, self.file_signature = doc, self._signature()
                return changed
        except (OSError, ValueError, MapRulesError) as error:
            self.error = f'Map rules persistence unavailable: {error}'
            raise MapRulesError(self.error, 503) from error

    def _read(self):
        if not self.filename.exists():
            return None
        if self.filename.stat().st_size > 32_000_000:
            raise MapRulesError('Persistence document is too large', 503)
        def reject_constant(value):
            raise ValueError(f'Nonfinite JSON number {value}')
        doc = json.loads(self.filename.read_text(), parse_constant=reject_constant)
        if (not isinstance(doc, dict) or set(doc) != {'schema', 'map_id', 'revision', 'zones', 'routes', 'runs'}
                or doc['schema'] != 1 or doc['map_id'] != self.map_id):
            raise MapRulesError('Persistence schema or map identity mismatch', 503)
        integer(doc['revision'], 'rules revision')
        doc['zones'] = validate_zones(doc['zones'], self.grid)
        if not isinstance(doc['routes'], list) or len(doc['routes']) > MAX_ROUTES:
            raise MapRulesError('Malformed stored routes', 503)
        ids = set()
        for route in doc['routes']:
            validate_route(route, self.grid, self.map_id)
            if route['id'] in ids:
                raise MapRulesError('Duplicate stored route ID', 503)
            ids.add(route['id'])
        if not isinstance(doc['runs'], list) or len(doc['runs']) > MAX_RUNS:
            raise MapRulesError('Malformed stored runs', 503)
        ids = set()
        for run in doc['runs']:
            if (not isinstance(run, dict) or run.get('map_id') != self.map_id
                    or run.get('status') not in {'running', 'canceling', 'canceled', 'succeeded', 'failed', 'unknown'}
                    or not isinstance(run.get('waypoints'), list)):
                raise MapRulesError('Malformed stored run', 503)
            valid_id(run.get('id'))
            integer(run.get('rules_revision'), 'run rules revision')
            integer(run.get('current_index'), 'run current_index')
            if (not isinstance(run.get('return_home'), bool) or not isinstance(run.get('message'), str)
                    or not 1 <= len(run['waypoints']) <= 13):
                raise MapRulesError('Malformed stored run fields', 503)
            for point in run['waypoints']:
                if not isinstance(point, dict) or set(point) != {'x', 'y', 'yaw'}:
                    raise MapRulesError('Malformed stored run waypoint', 503)
                for key in point:
                    number(point[key], f'run waypoint {key}')
            if run.get('start_pose') is not None:
                start = run['start_pose']
                if not isinstance(start, dict) or set(start) != {'x', 'y', 'yaw'}:
                    raise MapRulesError('Malformed stored run start_pose', 503)
                for key in start:
                    number(start[key], f'run start_pose {key}')
            for key in ('events', 'observations'):
                if key in run and (not isinstance(run[key], list) or len(run[key]) > 300
                                   or any(not isinstance(item, dict) for item in run[key])):
                    raise MapRulesError(f'Malformed stored run {key}', 503)
            number(run.get('started_at'), 'run started_at')
            if run.get('finished_at') is not None:
                number(run['finished_at'], 'run finished_at')
            if run['id'] in ids:
                raise MapRulesError('Duplicate stored run ID', 503)
            ids.add(run['id'])
        return doc

    def require_available(self):
        if not self.map_id or self.grid is None:
            raise MapRulesError('Map is not available', 503)
        if self.error:
            raise MapRulesError(self.error, 503)

    def _transaction(self, mutate):
        self.require_available()
        temporary = None
        try:
            with (self.directory / f'{self.map_id}.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                doc = self._read() or copy.deepcopy(self.document)
                mutate(doc)
                encoded = json.dumps(doc, ensure_ascii=False, allow_nan=False,
                                     separators=(',', ':')).encode()
                if len(encoded) > 32_000_000:
                    raise MapRulesError('Persistence document is too large', 503)
                fd, temporary = tempfile.mkstemp(prefix=f'.{self.map_id}.', dir=self.directory)
                with os.fdopen(fd, 'wb') as output:
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.filename)
                temporary = None
                directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                self.document = doc
                self.file_signature = self._signature()
        except (OSError, ValueError) as error:
            self.error = f'Map rules persistence unavailable: {error}'
            raise MapRulesError(self.error, 503) from error
        except MapRulesError as error:
            if error.status >= 500:
                self.error = f'Map rules persistence unavailable: {error}'
            raise
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)

    def rules(self):
        self.require_available()
        return {key: copy.deepcopy(self.document[key]) for key in ('map_id', 'revision', 'zones')}

    def update_rules(self, body, active=False):
        self.require_available()
        if active:
            raise MapRulesError('Active or unresolved mission prevents map-rule editing', 409)
        if not isinstance(body, dict) or set(body) != {'map_id', 'base_revision', 'zones'}:
            raise MapRulesError('Expected map_id, base_revision and zones')
        if body['map_id'] != self.map_id:
            raise MapRulesError('Map identity changed; reload before editing', 409)
        revision = integer(body['base_revision'], 'base_revision')
        zones = validate_zones(body['zones'], self.grid)
        def mutate(doc):
            if any(run['status'] in {'running', 'canceling', 'unknown'} for run in doc['runs']):
                raise MapRulesError('Active or unresolved stored mission prevents map-rule editing', 409)
            if revision != doc['revision']:
                raise MapRulesError('Map rules revision conflict; reload before saving', 409)
            doc.update(revision=revision+1, zones=zones)
        self._transaction(mutate)
        return self.rules()

    def routes(self):
        self.require_available()
        return {'map_id': self.map_id, 'routes': copy.deepcopy(self.document['routes'])}

    def save_route(self, body):
        self.require_available()
        if not isinstance(body, dict) or set(body)-{'map_id', 'id', 'name', 'waypoints', 'return_home'}:
            raise MapRulesError('Expected map_id, name, waypoints, return_home and optional id')
        if body.get('map_id') != self.map_id:
            raise MapRulesError('Route belongs to another map', 409)
        identity = valid_id(body['id']) if 'id' in body else uuid.uuid4().hex
        name = body.get('name')
        if not isinstance(name, str):
            raise MapRulesError('Route name must be text')
        def mutate(doc):
            existing = next((r for r in doc['routes'] if r['id'] == identity), None)
            if existing is None and len(doc['routes']) >= MAX_ROUTES:
                raise MapRulesError(f'At most {MAX_ROUTES} routes can be saved')
            route = validate_route({'id': identity, 'name': name.strip(), 'map_id': self.map_id,
                'revision': existing['revision']+1 if existing else 1,
                'waypoints': body.get('waypoints'), 'return_home': body.get('return_home', False)},
                self.grid, self.map_id)
            doc['routes'] = [r for r in doc['routes'] if r['id'] != identity]+[route]
        self._transaction(mutate)
        return self.routes()

    def runs(self):
        self.require_available()
        return {'runs': copy.deepcopy(list(reversed(self.document['runs'])))}

    def save_run(self, record, expected_rules_revision=None):
        self.require_available()
        def mutate(doc):
            if expected_rules_revision is not None and doc['revision'] != expected_rules_revision:
                raise MapRulesError('Rules changed before mission ownership was saved; reload before sending', 409)
            doc['runs'] = ([r for r in doc['runs'] if r['id'] != record['id']]
                           + [copy.deepcopy(record)])[-MAX_RUNS:]
        self._transaction(mutate)
