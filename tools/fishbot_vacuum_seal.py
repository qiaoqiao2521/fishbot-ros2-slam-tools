#!/usr/bin/env python3
"""Finite skirt geometry and continuous leakage for assumed vacuum modules.

This is a reduced contact/flow model, not an elastomer FEM, manufactured J100
tire or seal calibration. It never turns pressure on from a contact boolean.
The caller owns pump integration and applies the resulting backplate force.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

DEFAULT_CONFIG = Path(__file__).resolve().parent / 'config/vacuum_seal.json'


def load_config(path: Path | None = None) -> dict[str, Any]:
    c = json.loads(DEFAULT_CONFIG.read_text())
    if path is not None and Path(path) != DEFAULT_CONFIG:
        c.update(json.loads(Path(path).read_text()))
    for key in ('inner_radius_m', 'outer_radius_m', 'lip_minor_radius_m',
                'module_mass_kg', 'roughness_equivalent_gap_m',
                'air_dynamic_viscosity_pa_s', 'air_density_kg_m3',
                'maximum_ray_distance_m', 'probe_backoff_m'):
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f'{key} must be finite and positive')
    if c['inner_radius_m'] >= c['outer_radius_m']:
        raise ValueError('inner_radius_m must be smaller than outer_radius_m')
    if not 0 < c['discharge_coefficient'] <= 1:
        raise ValueError('discharge_coefficient must be in (0, 1]')
    return c


def effective_area(c: dict[str, Any]) -> float:
    """Conservative enclosed area; no independent fictional force multiplier."""
    return math.pi * c['inner_radius_m'] ** 2


def chamber_geometry(c: dict[str, Any]) -> dict[str, Any]:
    """Nominal gas space inside the real polygon lip, with the lip just seated.

    At each height the capsule tube cuts an inward-offset regular polygon.
    Simpson integration resolves that cross-section rather than pretending
    the conservative pressure-force disk is the entire empty chamber volume.
    Lip deformation changes the real volume; this nominal-volume first model
    does not claim to resolve that small compliant swept volume.
    """
    count = int(c['lip_capsules'])
    radius = (c['inner_radius_m'] + c['outer_radius_m']) / 2
    minor = c['lip_minor_radius_m']
    bottom = -minor
    top = c['backplate_center_local_m'][2] - c['backplate_half_thickness_m']
    n = 256
    dz = (top - bottom) / n
    def cross_section(z: float) -> float:
        tube_half_width = math.sqrt(max(0.0, minor ** 2 - z ** 2)) if abs(z) <= minor else 0.0
        apothem = radius * math.cos(math.pi / count) - tube_half_width
        return count * apothem ** 2 * math.tan(math.pi / count)
    volume = dz / 3 * sum((1 if i in (0, n) else 4 if i % 2 else 2)
                          * cross_section(bottom + i * dz) for i in range(n + 1))
    return {'cavity_volume_m3': volume, 'cavity_depth_m': top - bottom,
            'pressure_effective_area_m2': effective_area(c),
            'backplate_port_local_m': list(c['backplate_port_local_m']),
            'basis': 'nominal_seated_16_capsule_polygon_void_integrated_to_colliding_backplate'}


def _rim_points(c: dict[str, Any]) -> tuple[list[tuple[float, float, float]], float]:
    """Midpoint quadrature along actual straight capsule axes, not a circle."""
    radius = (c['inner_radius_m'] + c['outer_radius_m']) / 2
    segments, samples = int(c['lip_capsules']), int(c['rim_samples'])
    points = []
    for j in range(samples):
        perimeter_coordinate = (j + .5) * segments / samples
        edge = math.floor(perimeter_coordinate)
        t = perimeter_coordinate - edge
        a, b = 2 * math.pi * edge / segments, 2 * math.pi * (edge + 1) / segments
        points.append((radius * ((1-t) * math.cos(a) + t * math.cos(b)),
                       radius * ((1-t) * math.sin(a) + t * math.sin(b)), 0.0))
    return points, segments * 2 * radius * math.sin(math.pi / segments) / samples


def pad_body_names(c: dict[str, Any], prefix: str = 'vacuum_pad') -> list[str]:
    return [f'{prefix}{i}' for i in range(len(c['module_centers_m']))]


def pad_bodies_xml(c: dict[str, Any], prefix: str = 'vacuum_pad') -> str:
    """Fixed bodies for insertion inside the chassis body.

    A soft native contact lip surrounds each pressure area. Geometry is in
    group 0 so the world-only ray query cannot see the robot itself. The lip
    has no artificial normal attraction or long contact margin.
    """
    parts = []
    radius = (c['inner_radius_m'] + c['outer_radius_m']) / 2
    count = int(c['lip_capsules'])
    mass = c['module_mass_kg']
    # A thin annular module's declared inertia; the explicit body mass prevents
    # the collision capsules from silently multiplying the hardware mass.
    ixy = mass * radius ** 2 / 2
    iz = mass * radius ** 2
    for name, center in zip(pad_body_names(c, prefix), c['module_centers_m']):
        geoms = []
        for j in range(count):
            a, b = 2 * math.pi * j / count, 2 * math.pi * (j + 1) / count
            ends = (radius * math.cos(a), radius * math.sin(a), 0,
                    radius * math.cos(b), radius * math.sin(b), 0)
            geoms.append(
                f'<geom name="{name}_lip{j}" type="capsule" '
                f'fromto="{" ".join(map(str, ends))}" '
                f'size="{c["lip_minor_radius_m"]}" mass="0" group="0" '
                f'priority="{c["lip_contact_priority"]}" '
                f'friction="{c["lip_friction"]} .001 .0001" condim="3" '
                f'solref="{c["lip_contact_time_constant_s"]} {c["lip_contact_damping_ratio"]}" '
                f'solimp=".9 .95 .001" margin="0" gap="0" rgba=".12 .18 .20 1"/>')
        # The backplate is a real rigid support once the lip is overcompressed.
        # It must not pass through a wall while the seal pretends to stay closed.
        parts.append(f'<body name="{name}" pos="{" ".join(map(str, center))}">'
                     f'<inertial pos="0 0 0" mass="{mass}" diaginertia="{ixy} {ixy} {iz}"/>'
                     f'<geom name="{name}_backplate" type="cylinder" '
                     f'size="{c["outer_radius_m"]} {c["backplate_half_thickness_m"]}" '
                     f'pos="{" ".join(map(str, c["backplate_center_local_m"]))}" '
                     f'mass="0" contype="1" conaffinity="1" group="0" rgba=".85 .52 .12 1"/>'
                     f'<site name="{name}_vacuum_port" '
                     f'pos="{" ".join(map(str, c["backplate_port_local_m"]))}" '
                     f'size=".001" rgba=".05 .5 .9 1"/>'
                     + ''.join(geoms) + '</body>')
    return ''.join(parts)


def adhesion_actuators_xml(c: dict[str, Any], prefix: str = 'vacuum_pad') -> str:
    """Optional native contact-adhesion comparison, on pads rather than tires.

    The caller must document that native adhesion distributes forces across
    actual pad contacts. It is not a free-space backplate-force replacement.
    """
    cap = c['maximum_pressure_pa'] * effective_area(c)
    return ''.join(f'<adhesion name="{name}_vacuum" body="{name}" gain="1" '
                   f'ctrlrange="0 {cap}"/>' for name in pad_body_names(c, prefix))


def _surface_normal(model: Any, data: Any, geom_id: int, point: Any) -> Any:
    """Outward normals of the native plane/box world used in this fixture."""
    import mujoco
    import numpy as np
    rotation = data.geom_xmat[geom_id].reshape(3, 3)
    if model.geom_type[geom_id] == mujoco.mjtGeom.mjGEOM_PLANE:
        return rotation[:, 2].copy()
    if model.geom_type[geom_id] == mujoco.mjtGeom.mjGEOM_BOX:
        local = rotation.T @ (point - data.geom_xpos[geom_id])
        axis = int(np.argmin(np.abs(np.abs(local) - model.geom_size[geom_id])))
        normal = np.zeros(3)
        normal[axis] = 1.0 if local[axis] >= 0 else -1.0
        return rotation @ normal
    # A new surface type requires its real normal implementation. Unknown is
    # explicit and may be inspected; no guessed aligned normal grants a seal.
    return None


def sample_gaps(model: Any, data: Any, body_id: int,
                c: dict[str, Any]) -> dict[str, Any]:
    """Ray-cast the actual lip around a module's outward -local-Z face.

    Rays start behind the nominal lip to retain signed compression. A missed
    surface is an open gap. Normal disagreement remains explicit diagnostic
    evidence while leakage stays continuous; there is no sealed/unsealed
    pressure-force switch.
    """
    import mujoco
    import numpy as np
    rotation = data.xmat[body_id].reshape(3, 3)
    face_normal = -rotation[:, 2]
    backoff = c['probe_backoff_m']
    points, segment_width = _rim_points(c)
    groups = np.zeros(6, dtype=np.uint8)
    groups[int(c['world_surface_geom_group'])] = 1
    gaps, signed_gaps, ids, normals, alignments = [], [], [], [], []
    for point in points:
        rim = data.xpos[body_id] + rotation @ np.asarray(point)
        start = rim - backoff * face_normal
        geom_id = np.array([-1], dtype=np.int32)
        distance = mujoco.mj_ray(model, data, start, face_normal,
                                groups, 1, body_id, geom_id)
        found = 0 <= distance <= c['maximum_ray_distance_m']
        signed = (float(distance) - backoff - c['lip_minor_radius_m']
                  if found else c['maximum_ray_distance_m'])
        hit = start + distance * face_normal if found else None
        normal = _surface_normal(model, data, int(geom_id[0]), hit) if found else None
        signed_gaps.append(signed)
        gaps.append(max(0.0, signed))
        ids.append(int(geom_id[0]) if found else -1)
        normals.append(normal.tolist() if normal is not None else None)
        alignments.append(float(np.dot(normal, -face_normal)) if normal is not None else None)
    # A box/plane face has one normal regardless of how many rim rays hit it.
    # Compare unique native face normals, avoiding a quadratic 64x64 loop for
    # every pad at each source update without discarding a corner's two faces.
    actual_normals = [np.asarray(n) for n in
                      {tuple(round(float(v), 12) for v in n)
                       for n in normals if n is not None}]
    spread = max((math.acos(min(1.0, max(-1.0, float(np.dot(a, b)))))
                  for a in actual_normals for b in actual_normals), default=0.0)
    misalignment = max((math.acos(min(1.0, max(-1.0, a)))
                       for a in alignments if a is not None), default=math.pi)
    compression = max(0.0, -min(signed_gaps))
    missing = sum(g < 0 for g in ids)
    status = ('open_surface' if missing else
              'unsupported_surface_normal' if any(n is None for n in normals) else
              'mixed_surface_normals' if spread > c['maximum_normal_spread_rad'] else
              'tilted_face' if misalignment > c['maximum_face_misalignment_rad'] else
              'compression_limit_exceeded' if compression > c['maximum_compression_m'] else
              'sampled')
    return {'gaps_m': gaps, 'signed_gaps_m': signed_gaps,
            'segment_width_m': segment_width,
            'surface_geom_ids': ids, 'surface_normals': normals,
            'face_normal_world': face_normal.tolist(),
            'normal_spread_rad': spread, 'face_misalignment_rad': misalignment,
            'maximum_compression_m': compression, 'missing_samples': missing,
            'status': status}


def evaluate_leak(c: dict[str, Any], gaps: dict[str, Any] | Iterable[float],
                  delta_p: float) -> dict[str, Any]:
    """Evaluate the continuous viscous/inertial series resistance per segment.

    Small gaps recover Q=width*h^3*DeltaP/(12*mu*lip_width). The added inertial
    term limits that approximation for open gaps; it is an explicit surrogate,
    not calibrated CFD. All returned flow is referred to ambient air density.
    """
    sample = gaps if isinstance(gaps, dict) else {'gaps_m': list(gaps), 'status': 'provided'}
    gap_values = list(sample['gaps_m'])
    if not gap_values:
        raise ValueError('at least one perimeter gap is needed')
    radius = (c['inner_radius_m'] + c['outer_radius_m']) / 2
    polygon_perimeter = int(c['lip_capsules']) * 2 * radius * math.sin(math.pi / int(c['lip_capsules']))
    width = float(sample.get('segment_width_m', polygon_perimeter / len(gap_values)))
    # The colliding rim is a capsule tube, not a filled 10mm annular band.
    # Its entire 4mm diameter is already an optimistic upper bound for the
    # hydraulic contact path. Do not claim outer-inner backplate width seals.
    length = min(c['outer_radius_m'] - c['inner_radius_m'],
                 2 * c['lip_minor_radius_m'])
    pressure = max(0.0, float(delta_p))
    flow = zero_pressure_conductance = 0.0
    hydraulic_gaps = []
    for geometric_gap in gap_values:
        h = max(0.0, float(geometric_gap)) + c['roughness_equivalent_gap_m']
        hydraulic_gaps.append(h)
        resistance = 12 * c['air_dynamic_viscosity_pa_s'] * length / (width * h ** 3)
        inertia = c['air_density_kg_m3'] / (2 * c['discharge_coefficient'] ** 2 * width ** 2 * h ** 2)
        zero_pressure_conductance += 1 / resistance
        if pressure:
            flow += 2 * pressure / (resistance + math.sqrt(resistance ** 2 + 4 * inertia * pressure))
    area = effective_area(c)
    return {'leak_flow_m3_s': flow,
            'leak_conductance_m3_s_pa': flow / pressure if pressure else zero_pressure_conductance,
            'effective_area_m2': area, 'pressure_force_n': area * pressure,
            'pressure_pa': pressure,
            'mean_gap_m': sum(gap_values) / len(gap_values),
            'maximum_gap_m': max(gap_values),
            'minimum_hydraulic_gap_m': min(hydraulic_gaps),
            'maximum_hydraulic_gap_m': max(hydraulic_gaps),
            'perimeter_m': width * len(gap_values), 'lip_flow_path_m': length,
            'sample_count': len(gap_values), 'status': sample.get('status', 'provided'),
            'missing_samples': sample.get('missing_samples', 0),
            'normal_spread_rad': sample.get('normal_spread_rad'),
            'face_misalignment_rad': sample.get('face_misalignment_rad')}
