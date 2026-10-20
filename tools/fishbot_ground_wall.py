#!/usr/bin/env python3
"""A source-derived free chassis drives continuously from floor to wall.

Only four bounded wheel servos and four native MuJoCo contact-adhesion
actuators move the vehicle. There is no body pose servo, external lifting
force, weld or state reset. The hypothetical tire seals are not CFD.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
import uuid
from typing import Any

from fishbot_suction import Chamber

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / 'config/ground_wall_reference.json'
CASES = ('transition', 'no_pump')
WHEELS = ('front_left', 'front_right', 'rear_left', 'rear_right')
LIMITATIONS = [
    'Simulation of a dedicated adhesive-wheel conversion with J100 dimensions and inertia; an unmodified Jackal cannot climb walls.',
    'Four independent hypothetical tire seals use contact presence and effective area; no seal deformation, leakage calibration, CFD or duct flow is resolved.',
    'Friction 0.8, pump area, valve timing and bounded motor servos are assumptions, not measured hardware parameters.',
    'Added pump, valves and seal hardware mass/geometry are not modeled; the declared J100 chassis mass and inertia are retained.',
    'Equal wheel speed commands permit actual frictional slip through the corner; this is not a no-slip kinematic gait.',
    'Parking uses ideal wheel encoders and a bounded wheel-angle feedback brake; it does not hold the chassis by a world pose constraint.',
    'This is a native MuJoCo mechanics experiment, not Nav2 wall navigation or sim-to-real validation.',
]


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    import yaml
    c = json.loads(path.read_text())
    profile = yaml.safe_load((ROOT.parent / c['source']['profile']).read_text())
    # Existing source-attributed baseline owns dimensions and inertia. The new
    # file owns only adhesive hardware/control assumptions.
    c['chassis'] = profile['chassis']
    c['drivetrain'] = profile['drivetrain']
    c['source'] = dict(profile['source'], profile=c['source']['profile'])
    for key in ('timestep_s', 'duration_s', 'trace_hz', 'render_fps'):
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f'{key} must be finite and positive')
    return c


def chamber_config(c: dict[str, Any]) -> dict[str, Any]:
    """Split the existing pump model into four independent chambers."""
    pump = json.loads((ROOT / 'config/suction_reference.json').read_text())
    for key in ('chamber_volume_m3', 'pump_free_flow_m3_s',
                'leak_conductance_m3_s_pa', 'pump_idle_power_w'):
        pump[key] /= 4.0
    pump['effective_area_m2'] = c['assumptions']['total_effective_adhesion_area_m2'] / 4.0
    return pump


def model_xml(c: dict[str, Any]) -> str:
    a, ch, d = c['assumptions'], c['chassis'], c['drivetrain']
    bodies, acts = [], []
    assets = ROOT.parent/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/jackal_j100'
    for i, (front, left) in enumerate(((True, True), (True, False), (False, True), (False, False))):
        x, y = d['wheelbase']/2*(1 if front else -1), d['track']/2*(1 if left else -1)
        bodies.append(f'''<body name="{WHEELS[i]}" pos="{x} {y} {d['wheel_vertical_offset']}">
          <joint name="axle{i}" type="hinge" axis="0 1 0" damping=".01"/>
          <inertial mass="{d['wheel_mass']}" pos="0 0 0" diaginertia="{' '.join(map(str, d['wheel_inertia']))}"/>
          <geom name="tire{i}" type="cylinder" size="{d['wheel_radius']} {d['wheel_width']/2}" euler="90 0 0"
            margin="{a['seal_gap_m']}" gap="{a['seal_gap_m']}" rgba=".10 .12 .14 1"/>
          <geom type="mesh" mesh="jackal_wheel" euler="90 0 0" mass="0" contype="0" conaffinity="0" rgba=".12 .14 .16 1"/>
          <geom type="box" size=".006 {d['wheel_width']/2+.001} {d['wheel_radius']*.8}" contype="0" conaffinity="0" mass="0" rgba=".7 .72 .75 1"/>
        </body>''')
        cap = chamber_config(c)['max_pressure_pa'] * a['total_effective_adhesion_area_m2']/4
        acts.append(f'<adhesion name="vacuum{i}" body="{WHEELS[i]}" gain="1" ctrlrange="0 {cap}"/>')
    for i in range(4):
        limit, speed = a['wheel_torque_limit_nm'], a['wheel_speed_limit_rad_s']
        acts.append(f'<velocity name="drive{i}" joint="axle{i}" kv="{a["velocity_servo_kv"]}" '
                    f'ctrllimited="true" ctrlrange="-{speed} {speed}" '
                    f'forcelimited="true" forcerange="-{limit} {limit}"/>')
    return f'''<mujoco model="j100_adhesive_conversion_ground_wall">
      <compiler angle="degree"/><option timestep="{c['timestep_s']}" integrator="implicitfast" cone="elliptic" impratio="10"/>
      <visual><headlight ambient=".6 .6 .6" diffuse=".6 .6 .6"/><global offwidth="640" offheight="480"/></visual>
      <asset><mesh name="jackal_body" file="{assets/'j100_base.stl'}"/>
      <mesh name="jackal_wheel" file="{assets/'outdoor.stl'}"/>
      <texture name="grid" type="2d" builtin="checker" rgb1=".80 .83 .87" rgb2=".58 .64 .70" width="256" height="256"/>
      <material name="gridmat" texture="grid" texrepeat="8 8" texuniform="true"/></asset>
      <default><geom friction="{a['friction']} .005 .0001" condim="3" solref=".005 1" solimp=".99 .999 .001"/></default>
      <worldbody><light pos="-3 -2 4" dir="1 0 -1" diffuse=".9 .9 .9" castshadow="false"/>
        <geom name="floor" type="plane" size="4 4 .1" material="gridmat"/>
        <geom name="wall" type="box" pos=".1 0 1.5" size=".1 2 1.5" material="gridmat"/>
        <body name="car" pos="{' '.join(map(str,a['initial_position_m']))}"><freejoint name="free"/>
          <inertial mass="{ch['mass']}" pos="{' '.join(map(str,ch['com']))}" fullinertia="{' '.join(map(str,ch['inertia']))}"/>
          <geom name="chassis" type="box" pos="0 0 {ch['height']/2}" size="{ch['length']/2} {ch['width']/2} {ch['height']/2}" group="3" rgba=".12 .46 .75 1"/>
          <geom name="source_body_visual" type="mesh" mesh="jackal_body" pos="0 0 -.0655" quat=".5 .5 .5 .5" mass="0" contype="0" conaffinity="0" rgba=".18 .40 .64 1"/>
          <geom type="box" pos=".13 0 {ch['height']+.006}" size=".025 .10 .006" mass="0" contype="0" conaffinity="0" rgba=".95 .65 .12 1"/>
          {''.join(bodies)}
        </body>
      </worldbody><actuator>{''.join(acts)}</actuator>
    </mujoco>'''


def wheel_contacts(model: Any, data: Any, *, load_bearing: bool = True) -> tuple[list[dict[str, int]], list[dict[str, float]]]:
    import mujoco
    import numpy as np
    tires = {model.geom(f'tire{i}').id: i for i in range(4)}
    surfaces = {model.geom('floor').id: 'floor', model.geom('wall').id: 'wall'}
    result = [{'floor': 0, 'wall': 0} for _ in range(4)]
    forces = [{'floor': 0.0, 'wall': 0.0} for _ in range(4)]
    force = np.zeros(6)
    for j in range(data.ncon):
        contact = data.contact[j]
        pair = (int(contact.geom1), int(contact.geom2))
        tire = next((tires[g] for g in pair if g in tires), None)
        surface = next((surfaces[g] for g in pair if g in surfaces), None)
        if tire is not None and surface is not None:
            mujoco.mj_contactForce(model,data,j,force)
            normal = max(0.0,float(force[0]))
            forces[tire][surface] += normal
            if not load_bearing or normal > 1e-6:
                result[tire][surface] += 1
    return result, forces


def rear_vent_mask(contacts: list[dict[str, int]]) -> list[bool]:
    """Release only rear floor seals after both front tires secure the wall."""
    front_secured = all(p['wall'] > 0 and p['floor'] == 0 for p in contacts[:2])
    return [False, False] + [front_secured and p['floor'] > 0 for p in contacts[2:]]


class WheelBrake:
    """Hold encoder angles through existing bounded wheel velocity servos."""
    def __init__(self, radius: float, distance: float, gain: float, limit: float):
        self.radius, self.distance, self.gain, self.limit = radius, distance, gain, limit
        self.wall_angles = self.park_angles = None
        self.reason = None

    def update(self, angles: Any, all_wall: bool, source_s: float,
               timeout_s: float, forward_rad_s: float, enabled: bool = True) -> list[float]:
        values = list(map(float, angles))
        if all_wall and self.wall_angles is None:
            self.wall_angles = values.copy()
        traveled = 0.0 if self.wall_angles is None else sum(x-y for x,y in zip(values,self.wall_angles))/4*self.radius
        if self.park_angles is None and (traveled >= self.distance or source_s >= timeout_s):
            self.park_angles = values.copy()
            self.reason = 'wheel_encoder_distance' if traveled >= self.distance else 'drive_timeout'
        if self.park_angles is not None:
            return [min(self.limit, max(-self.limit, self.gain*(p-x))) for p,x in zip(self.park_angles,values)]
        return [forward_rad_s if enabled else 0.0] * 4


def _row(model: Any, data: Any, contacts: Any, chambers: Any, phase: str,
         pressure_values: Any, energy: float, work: float, brake: WheelBrake,
         contact_forces: Any, seal_contacts: Any, episode_id: str) -> dict[str, Any]:
    import mujoco
    import numpy as np
    rotation = data.xmat[model.body('car').id].reshape(3,3)
    world_velocity = np.zeros(6)
    mujoco.mj_objectVelocity(model,data,mujoco.mjtObj.mjOBJ_XBODY,model.body('car').id,world_velocity,0)
    return {'episode_id':episode_id,'source_s': float(data.time), 'position_m': data.qpos[:3].tolist(),
            'quaternion_wxyz': data.qpos[3:7].tolist(),
            'pitch_up_rad': math.atan2(float(rotation[2,0]),float(rotation[0,0])),
            'velocity_m_s': world_velocity[3:].tolist(), 'angular_velocity_rad_s': world_velocity[:3].tolist(),
            'velocity_reference': 'world_frame_at_free_chassis_origin_mjOBJ_XBODY',
            'wheel_contacts': contacts, 'pressure_pa': [p.pressure_pa for p in chambers],
            'wheel_normal_contact_force_n': contact_forces, 'wheel_seal_near_contacts': seal_contacts,
            'phase': phase, 'brake_mode': 'wheel_encoder_angle_feedback' if brake.park_angles is not None else 'velocity_drive',
            'brake_reason': brake.reason,
            'adhesion_command_n': [float(x) for x in data.ctrl[:4]],
            'actual_adhesion_force_n': [float(x) for x in data.actuator_force[:4]],
            'wheel_torque_nm': [float(x) for x in data.actuator_force[4:]],
            'wheel_velocity_command_rad_s': [float(x) for x in data.ctrl[4:]],
            'pump_electrical_power_w': sum(p['electrical_power_w'] for p in pressure_values),
            'pump_electrical_energy_j': energy, 'drive_positive_mechanical_work_j': work}


def run_case(name: str, c: dict[str, Any], output: Path, render: bool = False) -> dict[str, Any]:
    import mujoco
    import numpy as np
    from fishbot_ground_wall_score import score

    output.mkdir(parents=True, exist_ok=True)
    episode_id = str(uuid.uuid4())
    xml = model_xml(c)
    (output/'scene.xml').write_text(xml)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model,data)
    a, d = c['assumptions'], c['drivetrain']
    chambers = [Chamber(chamber_config(c)) for _ in range(4)]
    addresses = [model.jnt_qposadr[model.joint(f'axle{i}').id] for i in range(4)]
    brake = WheelBrake(d['wheel_radius'],a['wall_encoder_travel_before_brake_m'],
                       a['parking_encoder_gain_s_inv'],a['wheel_speed_limit_rad_s'])
    energy = work = 0.0
    peaks = dict(wheel_torque_nm=0.0,pressure_pa=0.0,adhesion_force_n=0.0,
                 penetration_m=0.0,applied_body_force=0.0,applied_generalized_force=0.0,
                 chassis_surface_normal_n=0.0)
    values = [dict(electrical_power_w=0.0) for _ in range(4)]
    rows, snapshots = [], []
    renderer = camera = encoder = render_option = None
    render_warning = None
    fps = float(c['render_fps'])
    nframes, next_frame = 0, 0.0
    frame_targets = [(0.0,'initial'), (3.5,'approach'), (6.5,'pitching'),
                     (9.0,'wall'), (12.0,'climbing'), (17.5,'hold')]
    if render:
        try:
            renderer = mujoco.Renderer(model,height=480,width=640)
            camera = mujoco.MjvCamera()
            render_option = mujoco.MjvOption()
            render_option.geomgroup[3] = 0
            camera.lookat[:] = [-.25,0,.38]
            # MuJoCo azimuth 45 places this camera on negative world X, in
            # front of the wall; 145 would hide the vehicle behind the wall.
            camera.distance, camera.azimuth, camera.elevation = 2.3, 45, -18
            if shutil.which('ffmpeg'):
                encoder = subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y',
                    '-f','rawvideo','-vcodec','rawvideo','-pix_fmt','rgb24','-s','640x480',
                    '-r',str(fps),'-i','-','-an','-c:v','libx264','-pix_fmt','yuv420p',
                    '-movflags','+faststart',str(output/'transition.mp4')],stdin=subprocess.PIPE)
        except Exception as exc:
            render_warning = f'{type(exc).__name__}: {exc}'
    stride = max(1,round(1/c['trace_hz']/c['timestep_s']))
    steps = round(c['duration_s']/c['timestep_s'])
    started = time.monotonic()
    with (output/'trace.jsonl').open('w') as stream:
        for step in range(steps+1):
            contacts, contact_forces = wheel_contacts(model,data)
            seal_contacts, _ = wheel_contacts(model,data,load_bearing=False)
            all_wall = all(p['wall'] > 0 and p['floor'] == 0 for p in contacts)
            on_wall = any(p['wall'] > 0 for p in contacts)
            enabled = data.time >= a['pump_start_s']
            phase = ('hold' if brake.park_angles is not None else 'wall_climb' if all_wall else
                     'corner_transfer' if on_wall else 'approach' if enabled else 'settle')
            if step % stride == 0 or step == steps:
                row = _row(model,data,contacts,chambers,phase,values,energy,work,brake,contact_forces,seal_contacts,episode_id)
                rows.append(row); stream.write(json.dumps(row)+'\n')
            if renderer is not None and data.time+1e-9 >= next_frame:
                try:
                    from PIL import Image
                    renderer.update_scene(data,camera=camera,scene_option=render_option)
                    frame = renderer.render()
                    if encoder is not None:
                        encoder.stdin.write(frame.tobytes())
                    nframes += 1
                    while frame_targets and data.time >= frame_targets[0][0]-1e-9:
                        _, label = frame_targets.pop(0)
                        filename = f'frame-{label}.png'
                        Image.fromarray(frame).save(output/filename)
                        snapshots.append({'source_s':float(data.time),'path':filename})
                    next_frame = nframes/fps
                except Exception as exc:
                    render_warning = f'{type(exc).__name__}: {exc}'
                    renderer.close(); renderer = None
            if step == steps:
                break
            # A floor contact may become unloaded while the front tire still
            # seals against it. Releasing the rear then stalls the pitch-up.
            # Require the front floor seal to open geometrically as well as
            # actual front wall load before venting each rear floor chamber.
            vents = rear_vent_mask(seal_contacts)
            if not all(p['wall'] > 0 for p in contacts[:2]):
                vents = [False] * 4
            values = []
            for i, chamber in enumerate(chambers):
                command = 1.0 if enabled and name != 'no_pump' and not vents[i] else 0.0
                sealed = sum(seal_contacts[i].values()) > 0
                state = chamber.step(c['timestep_s'],command,sealed,100.0 if vents[i] else 1.0)
                values.append(state); data.ctrl[i] = state['requested_adhesion_n']
            data.ctrl[4:] = brake.update([data.qpos[j] for j in addresses],all_wall,float(data.time),
                                        a['drive_timeout_s'],a['drive_speed_m_s']/d['wheel_radius'],enabled)
            mujoco.mj_step(model,data)
            # mj_step advances qpos/time after evaluating contacts. Refresh
            # kinematics, velocities and forces for that same source instant.
            mujoco.mj_forward(model,data)
            energy += sum(p['electrical_power_w'] for p in values)*c['timestep_s']
            work += float(np.sum(np.maximum(0.0,data.actuator_force[4:]*data.actuator_velocity[4:])))*c['timestep_s']
            peaks['wheel_torque_nm'] = max(peaks['wheel_torque_nm'],float(np.max(np.abs(data.actuator_force[4:]))))
            peaks['pressure_pa'] = max(peaks['pressure_pa'],max(p.pressure_pa for p in chambers))
            peaks['adhesion_force_n'] = max(peaks['adhesion_force_n'],float(np.max(np.abs(data.actuator_force[:4]))))
            peaks['applied_body_force'] = max(peaks['applied_body_force'],float(np.max(np.abs(data.xfrc_applied))))
            peaks['applied_generalized_force'] = max(peaks['applied_generalized_force'],float(np.max(np.abs(data.qfrc_applied))))
            force = np.zeros(6)
            chassis_geom = model.geom('chassis').id
            surfaces = {model.geom('floor').id,model.geom('wall').id}
            for j in range(data.ncon):
                con = data.contact[j]
                peaks['penetration_m'] = max(peaks['penetration_m'],max(0.0,-float(con.dist)))
                pair = {int(con.geom1),int(con.geom2)}
                if chassis_geom in pair and pair.intersection(surfaces):
                    mujoco.mj_contactForce(model,data,j,force)
                    peaks['chassis_surface_normal_n'] = max(peaks['chassis_surface_normal_n'],max(0.0,float(force[0])))
    if renderer is not None:
        renderer.close()
    video_available = False
    if encoder is not None:
        try:
            encoder.stdin.close()
            video_available = encoder.wait(timeout=30) == 0
        except Exception as exc:
            render_warning = f'{type(exc).__name__}: {exc}'
            encoder.kill(); encoder.wait()
    oracle = score(rows,expected=name,criteria=c.get('criteria'))
    native_checks = {
        'free_chassis_and_four_driven_hinges': model.nq == 11 and model.nv == 10 and model.nu == 8,
        'no_equality_constraint': model.neq == 0,
        'complete_native_steps': abs(data.time-c['duration_s']) < c['timestep_s']*1.1,
        'no_native_warnings': not any(w.number for w in data.warning),
        'colliding_chassis': bool(model.geom_contype[model.geom('chassis').id]) and bool(model.geom_conaffinity[model.geom('chassis').id]),
        'bounded_wheel_torque': peaks['wheel_torque_nm'] <= a['wheel_torque_limit_nm']+1e-8,
        'bounded_pressure': peaks['pressure_pa'] <= chamber_config(c)['max_pressure_pa']+1e-8,
        'bounded_adhesion_force': peaks['adhesion_force_n'] <= chamber_config(c)['max_pressure_pa']*chamber_config(c)['effective_area_m2']+1e-8,
        'bounded_contact_penetration': peaks['penetration_m'] <= c['maximum_penetration_m'],
        'zero_applied_body_and_generalized_forces': peaks['applied_body_force']==0.0 and peaks['applied_generalized_force']==0.0,
        # The failed no-pump attempt may physically hit its chassis. It must
        # never inherit the successful vehicle's no-chassis-support claim.
        'successful_climb_not_assisted_by_chassis_contact': name != 'transition' or peaks['chassis_surface_normal_n'] <= 1e-6,
    }
    status = ('failed' if not all(native_checks.values()) else
              'incomplete' if oracle['status'] == 'unknown' else oracle['status'])
    report = {'id':'ground_to_wall' if name=='transition' else 'pump_off','source_case':name,
        'episode_id':episode_id,'label':'连续地面转墙并爬升停车' if name=='transition' else '同车无负压对照',
        'status':status,'oracle_status':oracle['status'],'oracle':oracle,'native_checks':native_checks,
        'task_motion_success': oracle['task_motion_success'], 'metrics':oracle['metrics'],
        'checks':dict(oracle['checks'],**native_checks),'physical_peaks':peaks,
        'chassis_contact_observed':peaks['chassis_surface_normal_n'] > 1e-6,
        'chassis_support_check_scope':'positive transition only; failed no-pump contact impacts are recorded without a successful-climb claim',
        'model':{'nq':model.nq,'nv':model.nv,'nu':model.nu,'neq':model.neq,
                 'mass_kg':float(sum(model.body_mass)), 'wheel_order':list(WHEELS),
                 'chassis_collision_enabled':bool(model.geom_contype[model.geom('chassis').id]),
                 'pressure_model':'four_independent_existing_Chamber_models',
                 'brake_mode':'ideal_wheel_encoder_angle_feedback_through_bounded_velocity_servos'},
        'warnings':[int(w.number) for w in data.warning], 'source_duration_s':float(data.time),
        'trace_rows':len(rows),'runtime_wall_s':time.monotonic()-started,
        'pump_electrical_energy_j':energy,'drive_positive_mechanical_work_j':work,
        'snapshots':snapshots,'video':{'available':video_available,'path':'transition.mp4' if video_available else None,
            'episode_id':episode_id,
            'fps':fps,'frame_count':nframes,'source_start_s':0.0,'source_end_s':float(data.time),
            'playback_duration_s':nframes/fps if nframes else None,'realtime_speed':1.0},
        'render_warning':render_warning,'limitations':LIMITATIONS}
    (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',choices=CASES,action='append')
    parser.add_argument('--render',action='store_true')
    args = parser.parse_args()
    c = load_config(args.config)
    args.output.mkdir(parents=True,exist_ok=True)
    reports = []
    for name in args.case or CASES:
        try:
            reports.append(run_case(name,c,args.output/name,args.render))
        except Exception as exc:
            warning = f'{type(exc).__name__}: {exc}'
            item = {'id':'ground_to_wall' if name=='transition' else 'pump_off',
                    'source_case':name,'status':'incomplete','oracle_status':'unknown',
                    'task_motion_success':False,'warning':warning}
            (args.output/name).mkdir(parents=True,exist_ok=True)
            (args.output/name/'report.json').write_text(json.dumps(item,indent=2)+'\n')
            reports.append(item)
            print(f'WARNING {name}: {warning}',flush=True)
    report = {'schema':'fishbot.ground-wall.v1','scope':'simulation',
              'generated_at':datetime.now(timezone.utc).isoformat(),'label':c['label'],
              'status':'passed' if all(x['status']=='passed' for x in reports) else 'failed' if any(x['status']=='failed' for x in reports) else 'incomplete',
              'config':c,'cases':reports,'limitations':LIMITATIONS}
    (args.output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'status':report['status'],'cases':[(x['id'],x['status']) for x in reports],
                      'report':str(args.output/'report.json')},ensure_ascii=False))
    return 0 if report['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
