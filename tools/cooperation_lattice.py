"""Configure the installed Nav2 lattice plugin; never implement path search."""
import json
import math
from pathlib import Path

DEFAULT_LATTICE = Path(__file__).with_name('config')/'navigation_lattices/diff-r060-2cm.json'


def lattice_parameters(params, filepath=None, *, allow_reversing=False):
    path = Path(filepath or DEFAULT_LATTICE).resolve()
    try:
        value = json.loads(path.read_text())
        metadata = value['lattice_metadata']
        primitives = value['primitives']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'Cannot read native lattice primitives {path}: {error}') from error
    if not isinstance(metadata, dict):
        raise ValueError('Native lattice_metadata must be an object')
    if metadata.get('motion_model') != 'diff':
        raise ValueError('The differential lattice profile requires motion_model=diff')
    resolution = params['global_costmap']['global_costmap']['ros__parameters']['resolution']
    declared = metadata.get('grid_resolution')
    if (type(declared) not in (int, float) or not math.isfinite(declared)
            or not math.isclose(declared, resolution, abs_tol=1e-9, rel_tol=0.)):
        raise ValueError(f'Lattice grid {declared} does not match costmap {resolution} m; '
                         'generate matching primitives instead of resizing the map')
    radius = metadata.get('turning_radius')
    if type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
        raise ValueError('Lattice curved primitives require a finite positive turning_radius')
    if not isinstance(primitives, list) or not primitives:
        raise ValueError('Native lattice has no motion primitives')
    rotations = sum(1 for primitive in primitives if primitive.get('trajectory_length') == 0.
                    and len(primitive.get('poses', [])) >= 2)
    previous = params['planner_server']['ros__parameters']['GridBased']
    return ({'plugin': 'nav2_smac_planner::SmacPlannerLattice',
             'tolerance': 0., 'allow_unknown': previous.get('allow_unknown', True),
             'lattice_filepath': str(path), 'allow_reverse_expansion': bool(allow_reversing),
             'smooth_path': False, 'lookup_table_size': 5.},
            {'lattice_filepath': str(path), 'lattice_motion_model': 'diff',
             'grid_resolution_m': declared, 'minimum_turning_radius_m': radius,
             'lattice_heading_count': metadata.get('num_of_headings'),
             'lattice_allow_reverse_expansion': bool(allow_reversing),
             'lattice_primitive_count': len(primitives), 'in_place_rotation_primitives': rotations,
             'required_native_transition_fix': 'nav2-1.3.13-lattice-edge-cache',
             'turning_radius_scope': 'curved primitives; in-place rotation is separately available'})
