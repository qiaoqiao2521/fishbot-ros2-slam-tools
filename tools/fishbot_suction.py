#!/usr/bin/env python3
"""Native MuJoCo contact-adhesion experiments; no ROS or hidden pose constraint.

Pressure is a lumped isothermal pump/leak model, not CFD. All reference fixture
parameters are assumptions, not a calibration of FishBot or commercial hardware.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

DEFAULT_CONFIG = Path(__file__).resolve().parent / 'config/suction_reference.json'
CASES = ('ground_off', 'ground_on', 'wall_on', 'wall_pressure_loss', 'wall_climb')
SOURCES = [
    'https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html#actuator-adhesion',
    'https://mujoco.readthedocs.io/en/3.3.7/modeling.html#preventing-slip',
]


@dataclass
class Chamber:
    """Gauge vacuum p >= 0; linear pump curve and linear leak conductance."""
    config: dict[str, Any]
    pressure_pa: float = 0.0

    def step(self, dt: float, command: float, sealed: bool,
             leak_multiplier: float = 1.0) -> dict[str, float]:
        c = self.config
        u = min(1.0, max(0.0, command))
        max_p = c['max_pressure_pa']
        # A broken seal is an open vent. Its conductance is an explicit surrogate.
        leak = c['leak_conductance_m3_s_pa'] * leak_multiplier
        if not sealed:
            leak = max(leak, c['pump_free_flow_m3_s'] / max_p * 100.0)
        a = c['ambient_pressure_pa'] / c['chamber_volume_m3']
        pump0 = u * c['pump_free_flow_m3_s']
        rate = a * (pump0 / max_p + leak)
        equilibrium = a * pump0 / rate if rate > 0.0 else self.pressure_pa
        # Exact integration avoids timestep-dependent overshoot of this linear ODE.
        self.pressure_pa = min(max_p, max(0.0,
            equilibrium + (self.pressure_pa - equilibrium) * math.exp(-rate * dt)))
        flow = pump0 * max(0.0, 1.0 - self.pressure_pa / max_p)
        pneumatic = self.pressure_pa * flow
        electrical = pneumatic / c['pump_efficiency'] + u * c['pump_idle_power_w']
        return {'pressure_pa': self.pressure_pa, 'pump_flow_m3_s': flow,
                'pneumatic_power_w': pneumatic, 'electrical_power_w': electrical,
                'requested_adhesion_n': self.pressure_pa * c['effective_area_m2']
                if sealed else 0.0}


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(DEFAULT_CONFIG.read_text())
    selected = json.loads(path.read_text())
    config.update({k: v for k, v in selected.items() if k != 'criteria'})
    config['criteria'].update(selected.get('criteria', {}))
    for name in ('mass_kg', 'effective_area_m2', 'chamber_volume_m3',
                 'ambient_pressure_pa', 'max_pressure_pa', 'pump_efficiency',
                 'timestep_s', 'duration_s', 'seal_gap_m'):
        if not math.isfinite(config[name]) or config[name] <= 0:
            raise ValueError(f'{name} must be finite and positive')
    if config['max_pressure_pa'] >= config['ambient_pressure_pa']:
        raise ValueError('max_pressure_pa must be below ambient_pressure_pa')
    if not 0 < config['pump_efficiency'] <= 1:
        raise ValueError('pump_efficiency must be in (0,1]')
    return config


def model_xml(c: dict[str, Any], wall: bool) -> str:
    half = c['wall_half_size_m'] if wall else c['half_size_m']
    xyz = f'{c["wheel_radius_m"] + .03} 0 1.5' if wall else f'0 0 {half[2]}'
    target = ('<geom name="surface" type="plane" size="3 3 .1" '
              'euler="0 90 0" material="checker"/>' if wall else
              '<geom name="surface" type="plane" size="5 5 .1" material="checker"/>')
    if wall:
        parts = []
        actuators = []
        for i, (y, z) in enumerate(((-.1, -.12), (.1, -.12), (-.1, .12), (.1, .12))):
            parts.append(f'''<body name="wheel{i}" pos="-.03 {y} {z}">
              <joint name="axle{i}" type="hinge" axis="0 1 0" damping=".001"/>
              <geom name="pad{i}" type="cylinder" size="{c['wheel_radius_m']} .015" euler="90 0 0" mass="{c['wheel_mass_kg']}" margin="{c['seal_gap_m']}" gap="{c['seal_gap_m']}" rgba=".10 .12 .15 1" condim="3"/>
            </body>''')
            actuators.append(f'<adhesion name="vacuum{i}" body="wheel{i}" gain="1" ctrlrange="0 {c["max_pressure_pa"] * c["effective_area_m2"] / 4}"/>')
        for i in range(4):
            actuators.append(f'<velocity name="drive{i}" joint="axle{i}" kv="{c["wheel_servo_kv"]}" forcelimited="true" forcerange="-{c["wheel_torque_limit_nm"]} {c["wheel_torque_limit_nm"]}"/>')
        pad_xml = (f'<geom name="chassis" type="box" size="{half[0]} {half[1]} {half[2]}" '
                   f'mass="{c["mass_kg"] - 4 * c["wheel_mass_kg"]}" contype="0" conaffinity="0" rgba=".12 .55 .85 1"/>'
                   + ''.join(parts))
        actuator_xml = ''.join(actuators)
    else:
        pad_xml = f'<geom name="pad" type="box" size="{" ".join(map(str, half))}" mass="{c["mass_kg"]}" rgba=".12 .55 .85 1" margin="{c["seal_gap_m"]}" gap="{c["seal_gap_m"]}"/>'
        actuator_xml = f'<adhesion name="vacuum" body="module" gain="1" ctrlrange="0 {c["max_pressure_pa"] * c["effective_area_m2"]}"/>'
    return f'''<mujoco model="suction_reference_{'wall' if wall else 'ground'}">
  <compiler angle="degree"/>
  <option timestep="{c['timestep_s']}" integrator="implicitfast" cone="elliptic" impratio="10" gravity="0 0 -9.81"/>
  <visual><headlight ambient=".5 .5 .5" diffuse=".8 .8 .8" specular=".1 .1 .1"/></visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1=".85 .88 .9" rgb2=".6 .65 .7" width="128" height="128"/>
    <material name="checker" texture="grid" texrepeat="5 5" texuniform="true" emission=".2"/>
  </asset>
  <default><geom friction="{c['friction']} .005 .0001" condim="4" solref=".005 1" solimp=".99 .999 .001"/></default>
  <worldbody>
    <light pos="3 -2 5" dir="-1 0 -1" diffuse="1 1 1" ambient=".5 .5 .5" castshadow="false"/>
    {target}
    {'<geom name="catch_floor" type="plane" size="4 4 .1" rgba=".55 .6 .65 1"/>' if wall else ''}
    <body name="module" pos="{xyz}">
      <freejoint name="free"/>
      {pad_xml}
      <site name="center" size=".005"/>
    </body>
  </worldbody>
  <actuator>{actuator_xml}</actuator>
</mujoco>'''


def seal_state(model: Any, data: Any, body: int, pads: set[int], surface: int,
               wall: bool, c: dict[str, Any]) -> tuple[bool, float, int]:
    rot = data.xmat[body].reshape(3, 3)
    alignment = float(rot[0, 0] if wall else rot[2, 2])
    tilt = math.acos(min(1.0, max(-1.0, alignment)))
    contacts = [data.contact[i] for i in range(data.ncon)
                if surface in (int(data.contact[i].geom1), int(data.contact[i].geom2))
                and bool(pads.intersection((int(data.contact[i].geom1), int(data.contact[i].geom2))))]
    touching_pads = {g for con in contacts for g in (int(con.geom1), int(con.geom2)) if g in pads}
    sealed = (tilt <= c['seal_max_tilt_rad'] and len(contacts) >= 3
              and (not wall or len(touching_pads) == 4)
              and max(float(x.dist) for x in contacts) <= c['seal_gap_m'])
    return sealed, tilt, len(contacts)


def run_case(name: str, c: dict[str, Any], output: Path, render: bool = False) -> dict[str, Any]:
    import mujoco
    import numpy as np

    wall = name.startswith('wall')
    output.mkdir(parents=True, exist_ok=True)
    xml = model_xml(c, wall)
    (output / 'scene.xml').write_text(xml)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    body = model.body('module').id
    pads = {model.geom(f'pad{i}').id for i in range(4)} if wall else {model.geom('pad').id}
    surface = model.geom('surface').id
    mujoco.mj_forward(model, data)
    initial = data.qpos[:3].copy()
    chamber = Chamber(c, c['wall_initial_pressure_pa'] if wall else 0.0)
    energy = motor_work = 0.0
    peak_tilt = peak_speed = peak_p = 0.0
    contact_steps = sealed_steps = 0
    force = np.zeros(6)
    snapshots: list[dict[str, Any]] = []
    trace = output / 'trace.jsonl'
    renderer = camera = None
    render_warning = None
    if render:
        try:
            renderer = mujoco.Renderer(model, height=480, width=640)
            camera = mujoco.MjvCamera()
            camera.lookat[:] = [0, 0, .75] if wall else [.5, 0, 0]
            camera.distance = 3.5
            camera.azimuth = 25 if wall else 100
            camera.elevation = -15 if wall else -25
        except Exception as exc:
            render_warning = f'{type(exc).__name__}: {exc}'
    # Sample at 50Hz; small wheel inertia/contact needs 5kHz native integration.
    stride = max(1, round(.02 / c['timestep_s']))
    nsteps = round(c['duration_s'] / c['timestep_s'])
    at_fault = None
    started = time.monotonic()
    with trace.open('w') as stream:
        for step in range(nsteps):
            sealed, tilt, count = seal_state(model, data, body, pads, surface, wall, c)
            fault = name == 'wall_pressure_loss' and data.time >= c['fault_time_s']
            if fault and at_fault is None:
                at_fault = {'source_s': float(data.time), 'position_m': data.qpos[:3].tolist(),
                            'drop_before_fault_m': float(initial[2] - data.qpos[2]),
                            'peak_tilt_before_fault_rad': peak_tilt,
                            'pressure_before_fault_pa': chamber.pressure_pa}
            command = 0.0 if name == 'ground_off' or fault else 1.0
            values = chamber.step(c['timestep_s'], command, sealed,
                                  c['fault_leak_multiplier'] if fault else 1.0)
            if wall:
                data.ctrl[:4] = values['requested_adhesion_n'] / 4.0
                climbing = name == 'wall_climb' and c['push_start_s'] <= data.time < c['push_end_s'] + 1.0
                data.ctrl[4:] = -c['climb_speed_m_s'] / c['wheel_radius_m'] if climbing else 0.0
            else:
                data.ctrl[0] = values['requested_adhesion_n']
            data.xfrc_applied[:] = 0.0
            push = c['ground_push_n'] if not wall and c['push_start_s'] <= data.time < c['push_end_s'] else 0.0
            data.xfrc_applied[body, 0] = push
            mujoco.mj_step(model, data)
            energy += values['electrical_power_w'] * c['timestep_s']
            motor_power = float(np.sum(np.maximum(0.0, data.actuator_force[4:] * data.actuator_velocity[4:]))) if wall else 0.0
            motor_work += motor_power * c['timestep_s']
            peak_tilt = max(peak_tilt, tilt)
            peak_speed = max(peak_speed, float(np.linalg.norm(data.qvel[:3])))
            peak_p = max(peak_p, values['pressure_pa'])
            sealed_steps += int(sealed)
            contact_steps += int(count > 0)
            if step % stride == 0 or step == nsteps - 1:
                normal = tangent = 0.0
                contact_positions = []
                for j in range(data.ncon):
                    con = data.contact[j]
                    if surface in (int(con.geom1), int(con.geom2)) and pads.intersection((int(con.geom1), int(con.geom2))):
                        mujoco.mj_contactForce(model, data, j, force)
                        normal += max(0.0, float(force[0]))
                        tangent += float(np.linalg.norm(force[1:3]))
                        contact_positions.append(con.pos.copy())
                span_axis = 2 if wall else 0
                center = float(data.xpos[body, span_axis])
                support_lever = min(center - min(p[span_axis] for p in contact_positions),
                                    max(p[span_axis] for p in contact_positions) - center) if contact_positions else 0.0
                gravity_torque = c['mass_kg'] * 9.81 * float(data.xpos[body, 0]) if wall else push * float(data.xpos[body, 2])
                resisting = normal * support_lever
                row = {'source_s': float(data.time), 'position_m': data.qpos[:3].tolist(),
                       'velocity_m_s': data.qvel[:3].tolist(), 'sealed': sealed,
                       'tilt_rad': tilt, 'contacts': count, 'fault_active': fault,
                       **values, 'normal_contact_n': normal, 'tangent_contact_n': tangent,
                       'coulomb_capacity_n': c['friction'] * normal,
                       'required_tangent_n': c['mass_kg'] * 9.81 if wall else push,
                       'tip_moment_margin_nm': resisting - gravity_torque,
                       'pump_electrical_energy_j': energy,
                       'drive_positive_mechanical_power_w': motor_power,
                       'drive_positive_mechanical_work_j': motor_work}
                stream.write(json.dumps(row) + '\n')
            if renderer is not None and step in (0, nsteps // 2 - 1, nsteps - 1):
                try:
                    import PIL.Image
                    renderer.update_scene(data, camera=camera)
                    filename = f'frame-{step:05d}.png'
                    PIL.Image.fromarray(renderer.render()).save(output / filename)
                    snapshots.append({'source_s': float(data.time), 'path': filename})
                except Exception as exc:
                    render_warning = f'{type(exc).__name__}: {exc}'
                    renderer.close()
                    renderer = None
    if renderer is not None:
        renderer.close()
    horizontal = float(np.linalg.norm(data.qpos[:2] - initial[:2]))
    drop = float(initial[2] - data.qpos[2])
    crit = c['criteria']
    checks = {'native_free_body': model.nq == (11 if wall else 7) and model.nv == (10 if wall else 6) and model.neq == 0,
              'physical_steps_complete': abs(data.time - c['duration_s']) < c['timestep_s'] * 1.1,
              'pressure_bounded': peak_p <= c['max_pressure_pa'],
              'actual_contacts_seen': contact_steps > 0,
              'no_native_warnings': not any(w.number for w in data.warning)}
    if name == 'ground_off':
        checks['expected_slip_observed'] = horizontal >= crit['ground_off_min_displacement_m']
    elif name == 'ground_on':
        checks['held_against_push'] = horizontal <= crit['ground_on_max_displacement_m']
        checks['no_tip'] = peak_tilt <= crit['max_tilt_rad']
    elif name == 'wall_on':
        checks['wall_hold'] = abs(drop) <= crit['wall_on_max_drop_m']
        checks['no_tip'] = peak_tilt <= crit['max_tilt_rad']
    elif name == 'wall_climb':
        checks['powered_rise'] = -drop >= crit['wall_climb_min_rise_m']
        checks['no_tip'] = peak_tilt <= crit['max_tilt_rad']
    else:
        checks['loss_event_observed'] = at_fault is not None
        checks['held_before_loss'] = at_fault is not None and abs(at_fault['drop_before_fault_m']) <= crit['wall_on_max_drop_m']
        checks['lost_hold_after_pressure_loss'] = drop >= crit['wall_loss_min_drop_m']
    result = {'case': name, 'status': 'passed' if all(checks.values()) else 'failed',
              'checks': checks, 'scope': 'contact_adhesion_reference_fixture',
              'mujoco_version': mujoco.__version__, 'source_duration_s': float(data.time),
              'wall_elapsed_s': time.monotonic() - started,
              'physics_steps': nsteps, 'initial_position_m': initial.tolist(),
              'final_position_m': data.qpos[:3].tolist(),
              'horizontal_displacement_m': horizontal, 'vertical_drop_m': drop,
              'peak_tilt_rad': peak_tilt, 'peak_speed_m_s': peak_speed,
              'peak_pressure_pa': peak_p, 'final_pressure_pa': chamber.pressure_pa,
              'electrical_energy_j': energy, 'sealed_steps': sealed_steps,
              'pump_electrical_energy_j': energy,
              'drive_positive_mechanical_work_j': motor_work,
              'native_drive_wheel_count': 4 if wall else 0,
              'contact_steps': contact_steps, 'fault_event': at_fault,
              'native_warnings': [{'index': i, 'number': int(w.number)} for i, w in enumerate(data.warning) if w.number],
              'trace': str(trace), 'snapshots': snapshots, 'render_warning': render_warning,
              'no_weld_or_pose_servo': True, 'parameters_assumed': True}
    (output / 'result.json').write_text(json.dumps(result, indent=2))
    return result


def campaign(config_path: Path, output: Path, names: list[str], render: bool = False) -> dict[str, Any]:
    config = load_config(config_path)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'config.json').write_text(json.dumps(config, indent=2))
    report = {'schema_version': 1, 'kind': 'suction_reference',
              'created_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'reduced_order_contact_adhesion_not_cfd_or_real_robot',
              'source': {'label': config['label'], 'basis': config['basis']},
              'parameters': config, 'official_sources': SOURCES,
              'limitations': ['Assumed rigid sealed pad, not FishBot geometry or calibrated hardware',
                              'Wall fixture chassis is visual and inertial only; four wheels make contact. Pressure-loss cases do not validate chassis impact or whole-robot protection.',
                              'No CFD, duct thrust, surface roughness or compliant seal FEM',
                              'Four-wheel force distribution and four-contact seal detection are declared surrogates for a chamber/skirt',
                              'Wall climb is a short four-wheel rise on one planar wall, not wall-transition navigation',
                              'Pump power is estimated; drive work excludes motor losses, stall current and controller draw',
                              'Tip margin is support-span diagnostic; observed tilt is scored separately'],
              'cases': []}
    for name in names:
        try:
            result = run_case(name, config, output / name, render)
        except Exception as exc:
            result = {'case': name, 'status': 'incomplete',
                      'reason': f'{type(exc).__name__}: {exc}'}
            print(f'WARNING {name}: {result["reason"]}', file=sys.stderr)
        report['cases'].append(result)
        (output / 'report.json').write_text(json.dumps(report, indent=2))
    rows = ''.join(f'<tr><td>{html.escape(x["case"])}</td><td>{x["status"]}</td><td>'
                   f'{html.escape(json.dumps(x.get("checks", {})))}</td></tr>' for x in report['cases'])
    (output / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>负压接触对照</title>'
        '<style>body{font:16px system-ui;margin:2rem;max-width:1100px}td,th{padding:12px;border-bottom:1px solid #ddd}'
        'table{border-collapse:collapse}code{overflow-wrap:anywhere}</style><h1>负压接触对照</h1>'
        '<p>真实 MuJoCo 步进；假设刚体与降阶压力模型。仅验证抓地、竖墙保持与失压滑落。</p>'
        f'<table><tr><th>工况</th><th>验收</th><th>检查</th></tr>{rows}</table>'
        '<p><a href="report.json">完整 JSON</a> · 每例目录含 scene.xml、trace.jsonl 与 result.json。</p>')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=CASES, action='append')
    parser.add_argument('--render', action='store_true', help='Optional native rendered snapshots')
    args = parser.parse_args()
    report = campaign(args.config, args.output, args.case or list(CASES), args.render)
    print(json.dumps({'output': str(args.output),
                      'cases': [{k: row[k] for k in ('case', 'status')} for row in report['cases']]}))
    return 0 if all(x['status'] == 'passed' for x in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
