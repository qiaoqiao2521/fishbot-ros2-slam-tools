#!/usr/bin/env python3
"""Source-attributed carried hardware and a single shared vacuum pump.

The isothermal pump/leak balance follows fishbot_suction.Chamber. This adapter
adds manufacturer curve interpolation, shared volume and physical valve delay.
It never moves a body or supplies an external force; the caller owns native
MuJoCo adhesion and the independently scored mechanics experiment.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path(__file__).resolve().parent / 'config/vacuum_hardware.json'


def load_hardware(path: Path = DEFAULT_CONFIG,
                  seal_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derive tubing endpoints and gas volumes from the selected real lip XML."""
    from fishbot_vacuum_seal import chamber_geometry, load_config
    path = Path(path)
    c = json.loads(path.read_text())
    seal = seal_config if seal_config is not None else load_config(path.parent/c['seal_config'])
    geometry = chamber_geometry(seal)
    hose, p = c['installation']['hose'], c['pneumatics']
    endpoints = [[a+b for a, b in zip(center, geometry['backplate_port_local_m'])]
                 for center in seal['module_centers_m']]
    hose['routes_m'] = [[*points, end] for points, end in zip(hose['routing_waypoints_m'], endpoints)]
    def route_length(route: list[list[float]]) -> float:
        return sum(math.dist(a, b) for a, b in zip(route, route[1:]))
    section = math.pi*(hose['inner_diameter_m']/2)**2
    branch_hose_volumes = [route_length(route)*section for route in hose['routes_m']]
    main_hose_volume = route_length(hose['pump_route_m'])*section
    p['chamber_volumes_m3'] = [geometry['cavity_volume_m3']+v for v in branch_hose_volumes]
    p['manifold_volume_m3'] = p['manifold_internal_volume_m3'] + p['pump_internal_volume_m3'] + main_hose_volume
    c['gas_geometry'] = dict(skirt=geometry, branch_hose_volumes_m3=branch_hose_volumes,
        main_hose_volume_m3=main_hose_volume, hose_endpoints_chassis_m=endpoints,
        chamber_volumes_m3=list(p['chamber_volumes_m3']), manifold_volume_m3=p['manifold_volume_m3'],
        basis='nominal_seated_polygon_void_plus_real_hose_inner_volume_not_deformation_FSI')
    return c


def _box(name: str, c: dict[str, Any], color: str) -> dict[str, Any]:
    dimensions = c['dimensions_m']
    mass = c.get('mass_kg', math.prod(dimensions) * c.get('density_kg_m3', 0.0))
    inertia = [mass * (dimensions[(i+1) % 3]**2 + dimensions[(i+2) % 3]**2) / 12
               for i in range(3)]
    return dict(name=name, mass_kg=mass, position_m=c['position_m'],
                shape='box', dimensions_m=dimensions, inertia_diagonal=inertia,
                quaternion_wxyz=[1, 0, 0, 0], color=color)


def _cylinder(name: str, mass: float, radius: float, inner: float, length: float,
              position: list[float], axis: list[float], color: str,
              capsule: bool = False) -> dict[str, Any]:
    radial = mass * (3 * (radius**2 + inner**2) + length**2) / 12
    axial = mass * (radius**2 + inner**2) / 2
    # Quaternion rotates the local cylinder Z axis onto the declared hose/union.
    q = [1 + axis[2], -axis[1], axis[0], 0.0]
    norm = math.sqrt(sum(v*v for v in q))
    q = [v/norm for v in q] if norm > 1e-12 else [0.0, 1.0, 0.0, 0.0]
    return dict(name=name, mass_kg=mass, position_m=position,
                shape='capsule' if capsule else 'cylinder', radius_m=radius,
                length_m=length, inertia_diagonal=[radial, radial, axial],
                quaternion_wxyz=q, axis=axis, color=color)


def hardware_parts(c: dict[str, Any]) -> list[dict[str, Any]]:
    """Rigid installation parts in the original chassis frame, with nonzero mass."""
    installation = c['installation']
    parts = [_box('vacuum_pump', c['pump'], '.23 .24 .26 1'),
             _box('vacuum_mount_plate', installation['mount_plate'], '.65 .68 .72 1'),
             _box('vacuum_manifold', installation['manifold'], '.55 .57 .60 1'),
             _box('vacuum_electrics', installation['electrics'], '.10 .35 .22 1')]
    valves = installation['valves']
    for i, y in enumerate(valves['y_positions_m']):
        parts.append(_box(f'vacuum_valve{i}', dict(
            mass_kg=valves['mass_each_kg'], dimensions_m=valves['dimensions_m'],
            position_m=[valves['position_x_m'], y, valves['position_z_m']]),
            '.12 .30 .60 1' if i < 4 else '.70 .27 .12 1'))
    hose = installation['hose']
    routes = [*hose['routes_m'], hose['pump_route_m']]
    for i, points in enumerate(routes):
        for j, (start, end) in enumerate(zip(points, points[1:])):
            delta = [b-a for a, b in zip(start, end)]
            length = math.sqrt(sum(v*v for v in delta))
            parts.append(_cylinder(f'vacuum_hose{i}_{j}',
                hose['linear_mass_kg_m']*length, hose['outer_diameter_m']/2,
                hose['inner_diameter_m']/2, length,
                [(a+b)/2 for a, b in zip(start, end)],
                [v/length for v in delta], '.12 .48 .85 1', capsule=True))
    return parts


def hardware_xml(c: dict[str, Any]) -> str:
    """Insert in the chassis body; every part has explicit inertia and collision."""
    result = []
    for p in hardware_parts(c):
        shape = p['shape']
        size = ([v/2 for v in p['dimensions_m']] if shape == 'box'
                else [p['radius_m'], p['length_m']/2])
        vector = lambda x: ' '.join(format(v, '.12g') for v in x)
        result.append(f'<body name="{p["name"]}" pos="{vector(p["position_m"])}" '
            f'quat="{vector(p["quaternion_wxyz"])}">'
            f'<inertial pos="0 0 0" mass="{p["mass_kg"]:.12g}" '
            f'diaginertia="{vector(p["inertia_diagonal"])}"/>'
            f'<geom name="{p["name"]}_collision" type="{shape}" size="{vector(size)}" '
            f'mass="0" rgba="{p["color"]}" contype="1" conaffinity="1"/>'
            '</body>')
    return '\n'.join(result)


def mass_properties(c: dict[str, Any], base_mass: float = 0.0,
                    base_com: list[float] | None = None,
                    base_inertia: list[float] | None = None) -> dict[str, Any]:
    """Sum rigid mass and tensors via parallel-axis theorem; no dynamics reset.

    Optional base tensor order is MuJoCo fullinertia xx yy zz xy xz yz. This
    function does not include wheels unless the caller includes their parts.
    """
    parts = hardware_parts(c)
    extra = sum(p['mass_kg'] for p in parts)
    base_com = base_com or [0.0, 0.0, 0.0]
    base_inertia = base_inertia or [0.0]*6
    total = base_mass + extra
    com = [(base_mass*base_com[i] + sum(p['mass_kg']*p['position_m'][i] for p in parts))/total
           for i in range(3)]
    tensor = [[0.0]*3 for _ in range(3)]
    base_tensor = [[base_inertia[0], base_inertia[3], base_inertia[4]],
                   [base_inertia[3], base_inertia[1], base_inertia[5]],
                   [base_inertia[4], base_inertia[5], base_inertia[2]]]
    values = [(base_mass, base_com, base_tensor)]
    for p in parts:
        diag = p['inertia_diagonal']
        axis = p.get('axis')
        local = [[(diag[0] if i == j else 0.0) + (diag[2]-diag[0])*axis[i]*axis[j]
                  for j in range(3)] for i in range(3)] if axis else [
                      [diag[i] if i == j else 0.0 for j in range(3)] for i in range(3)]
        values.append((p['mass_kg'], p['position_m'], local))
    for mass, center, local in values:
        delta = [x-y for x, y in zip(center, com)]
        distance2 = sum(v*v for v in delta)
        for i in range(3):
            for j in range(3):
                tensor[i][j] += local[i][j] + mass*((distance2 if i == j else 0.0)-delta[i]*delta[j])
    return dict(added_mass_kg=extra, total_mass_kg=total, center_of_mass_m=com,
                fullinertia=[tensor[0][0], tensor[1][1], tensor[2][2],
                             tensor[0][1], tensor[0][2], tensor[1][2]],
                part_count=len(parts), inertia_basis='sourced_mass_uniform_envelopes_and_parallel_axis')


def pump_flow_m3_s(c: dict[str, Any], vacuum_pa: float) -> float:
    """Single pump's approximate STP flow; never multiplied by branch count."""
    absolute = c['pneumatics']['ambient_pressure_pa'] - vacuum_pa
    curve = c['pump']['absolute_pressure_pa_flow_stp_l_min']
    if absolute <= curve[0][0]:
        return curve[0][1] / 60000
    for (p0, q0), (p1, q1) in zip(curve, curve[1:]):
        if absolute <= p1:
            return (q0 + (q1-q0)*(absolute-p0)/(p1-p0)) / 60000
    return curve[-1][1] / 60000


class SharedVacuumNetwork:
    """Five gas volumes, one pump, four delayed isolation and vent valve pairs.

    Open branches use a high-conductance mixing approximation. Closed branches
    retain their own gas and leak/vent independently. All pressure values are
    nonnegative gauge vacuum. The exact local linear exponential step reuses
    the isothermal balance in Chamber; curve knots are approximated per step.
    """
    def __init__(self, config: dict[str, Any], areas: list[float]):
        self.config, self.areas = config, list(areas)
        self.pressure_pa = [0.0]*len(areas)
        self.manifold_pressure_pa = 0.0
        self.time_s = 0.0
        self.isolation_open = [False]*len(areas)
        self.vent_open = [False]*len(areas)
        self._desired = [[False]*len(areas), [False]*len(areas)]
        self._since = [[0.0]*len(areas), [0.0]*len(areas)]
        self.valve_switches = 0
        self.chamber_volumes_m3 = config['pneumatics']['chamber_volumes_m3'][:len(areas)]

    def _valves(self, requested: list[list[bool]], dt: float) -> None:
        v = self.config['installation']['valves']
        self.time_s += dt
        for group, actual in enumerate((self.isolation_open, self.vent_open)):
            for i, desired in enumerate(requested[group]):
                if desired != self._desired[group][i]:
                    self._desired[group][i] = desired
                    self._since[group][i] = self.time_s-dt
                delay = v['opening_s'] if desired else v['closing_s']
                if desired != actual[i] and self.time_s-self._since[group][i] >= delay-1e-12:
                    actual[i] = desired
                    self.valve_switches += 1

    def step(self, dt: float, command: float, sealed: list[bool],
             vented: list[bool] | None = None,
             leak_conductance: list[float] | None = None) -> dict[str, Any]:
        c, n = self.config, len(self.areas)
        p = c['pneumatics']
        u = max(0.0, min(1.0, command))
        vented = vented or [False]*n
        self._valves([[bool(s and not v) for s, v in zip(sealed, vented)],
                      [bool(not s or v) for s, v in zip(sealed, vented)]], dt)
        leak = list(leak_conductance) if leak_conductance is not None else [
            p['sealed_leak_conductance_each_m3_s_pa']]*n
        for i in range(n):
            # Geometric gap leakage is already represented by an explicitly
            # supplied conductance. Only an actually opened vent adds its flow;
            # the contact flag must not bypass the valve's physical delay.
            if self.vent_open[i] or (leak_conductance is None and not sealed[i]):
                leak[i] = max(leak[i], p['vent_conductance_each_m3_s_pa'])
        volume = p['manifold_volume_m3']
        chambers = self.chamber_volumes_m3
        connected = [i for i in range(n) if self.isolation_open[i]]
        total_volume = volume + sum(chambers[i] for i in connected)
        start = (self.manifold_pressure_pa*volume + sum(self.pressure_pa[i]*chambers[i] for i in connected))/total_volume
        # Local pump curve Q(P)=intercept-slope*P. The existing Chamber ODE is
        # dP/dt = p_ambient/V * (u*Q_ambient(P) - C_ambient*P).
        # Manufacturer STP-volume pump flow and ambient-density leak flow are
        # converted through equal ideal-gas molar flow, not mixed silently.
        stp_to_ambient = (p['reference_pressure_pa']/p['ambient_pressure_pa']
                          * p['ambient_temperature_k']/p['reference_temperature_k'])
        q = pump_flow_m3_s(c, start)
        probe = min(start+1.0, p['ambient_pressure_pa']-10000.0)
        slope = (q-pump_flow_m3_s(c, probe))/(probe-start) if probe > start else 0.0
        intercept = q + slope*start
        conductance = p['manifold_leak_conductance_m3_s_pa'] + sum(leak[i] for i in connected)
        rate = p['ambient_pressure_pa']/total_volume * (u*slope*stp_to_ambient + conductance)
        derivative0 = p['ambient_pressure_pa']/total_volume*u*intercept*stp_to_ambient
        equilibrium = derivative0/rate if rate else start
        unconstrained = (equilibrium+(start-equilibrium)*math.exp(-rate*dt)
                         if rate else start+derivative0*dt)
        next_pressure = min(p['operating_vacuum_limit_pa'], max(0.0, unconstrained))
        self.manifold_pressure_pa = next_pressure
        for i in range(n):
            self.pressure_pa[i] = (next_pressure if self.isolation_open[i] else
                self.pressure_pa[i]*math.exp(-p['ambient_pressure_pa']/chambers[i]*leak[i]*dt))
        available_flow = pump_flow_m3_s(c, next_pressure)
        # At the cap an assumed average-duty regulator supplies only the leak
        # plus the gas removed during this step. Four branches share this duty.
        demand = (next_pressure-start)*total_volume/(p['ambient_pressure_pa']*dt) + conductance*next_pressure
        duty = min(u, max(0.0, demand/(available_flow*stp_to_ambient))) if (
            unconstrained > p['operating_vacuum_limit_pa'] and available_flow > 0.0) else u
        flow = duty*available_flow
        valve_power = c['installation']['valves']['power_each_w']*(sum(self.isolation_open)+sum(self.vent_open))
        return dict(pressure_pa=list(self.pressure_pa), manifold_pressure_pa=next_pressure,
            requested_adhesion_n=[self.pressure_pa[i]*self.areas[i] for i in range(n)],
            pump_flow_m3_s=flow, pump_flow_basis='single_pump_coarse_manufacturer_graph_STP',
            pump_flow_ambient_m3_s=flow*stp_to_ambient,
            stp_to_ambient_volume_ratio=stp_to_ambient,
            relief_active=unconstrained > p['operating_vacuum_limit_pa'],
            regulator_duty=duty,
            regulation_basis='assumed_average_duty_pressure_cap_not_measured_motor_control',
            isolation_valve_open=list(self.isolation_open), vent_valve_open=list(self.vent_open),
            valve_switches=self.valve_switches,
            pump_electrical_power_upper_bound_w=duty*c['pump']['electrical_power_upper_bound_w'],
            valve_electrical_power_w=valve_power,
            electrical_power_w=duty*c['pump']['electrical_power_upper_bound_w']+valve_power,
            electrical_power_basis='pump_nameplate_upper_bound_plus_rated_valve_power')
