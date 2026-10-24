#!/usr/bin/env python3
"""Native contact motion panel; loaded initial fixture is not a grasp trial."""
import argparse
import json
import math
from pathlib import Path
import time

import mujoco
import numpy as np

from cooperation_scene import build_scene
from cooperation_sim import Physics

COMMANDS = [('forward', (.06, 0., 0.)), ('reverse', (-.06, 0., 0.)),
            ('left', (0., .06, 0.)), ('right', (0., -.06, 0.)),
            ('ccw', (0., 0., .1)), ('cw', (0., 0., -.1)),
            ('diagonal', (.04, .04, 0.)), ('curve', (.04, -.04, .08))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    manifest = build_scene(project.parent/'so101', project, args.output/'scene', spawn=(0., 0.),
                           scene_profile={'vehicle': 'robot_base_mecanum'})
    manifest_path = args.output/'scene/scene-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2))
    report = {'scope': 'shared MuJoCo plant motion; no ROS/navigation/grasp acceptance',
              'mujoco': mujoco.__version__, 'thresholds': {'linear_error_m_s': .02, 'yaw_error_rad_s': .04},
              'source_seconds_per_case': {'settle': 2., 'motion': 6., 'stop': 1.},
              'loaded_fixture': 'cargo initialized on tray before stepping; not an arm handover', 'cases': []}
    for loaded in (False, True):
        for label, command in COMMANDS:
            plant = Physics(manifest['world_xml'], manifest=manifest_path)
            if loaded:
                # Initial-condition fixture only, before source time starts.
                mujoco.mj_forward(plant.model, plant.data)
                floor = plant.tray_floor
                center = plant.data.geom_xpos[floor].copy()
                center[2] += plant.model.geom_size[floor, 2] + plant.model.geom_size[plant.cargo_geom, 2] + .001
                joint = plant.model.joint('target_free').id
                offset = int(plant.model.jnt_qposadr[joint])
                plant.data.qpos[offset:offset+7] = [*center, 1., 0., 0., 0.]
                mujoco.mj_forward(plant.model, plant.data)
            for _ in range(1000): plant.step()
            start = plant.data.xpos[plant.car_body].copy()
            plant.wheels.set_hold(False)
            velocities, wheel_speeds = [], []
            retention_failures = 0
            began = time.monotonic()
            for index in range(3000):
                plant.wheels.accept(command[0], command[2], time.monotonic(), lateral=command[1])
                plant.step()
                if loaded and not plant.contacts['cargo_tray_floor_contact']:
                    retention_failures += 1
                if index >= 2000:
                    world = np.asarray(plant.body_velocity(plant.car_body))
                    rotation = plant.data.xmat[plant.car_body].reshape(3, 3)
                    body_linear = rotation.T @ world[3:]
                    velocities.append([*body_linear[:2], world[2]])
                    wheel_speeds.append(plant.data.qvel[plant.wheel_v].copy())
            plant.refresh_snapshot()
            actual = np.mean(velocities, axis=0)
            wheel_mean = np.mean(wheel_speeds, axis=0)
            from cooperation_mecanum import forward
            encoder_velocity = forward(wheel_mean)
            endpoint = plant.data.xpos[plant.car_body].copy()
            yaw = math.atan2(plant.data.xmat[plant.car_body].reshape(3, 3)[1, 0], plant.data.xmat[plant.car_body].reshape(3, 3)[0, 0])
            position_error = math.hypot(plant.odom.x-endpoint[0], plant.odom.y-endpoint[1])
            yaw_error = abs(math.atan2(math.sin(plant.odom.yaw-yaw), math.cos(plant.odom.yaw-yaw)))
            plant.wheels.set_hold(True)
            for _ in range(500): plant.step()
            stop = np.asarray(plant.body_velocity(plant.car_body))
            checks = {
                'tracking': bool(max(abs(actual[:2]-command[:2])) <= .02 and abs(actual[2]-command[2]) <= .04),
                'actual_motion': bool(np.linalg.norm(endpoint-start) > .05 or abs(yaw) > .05),
                'no_external_collision': plant.total_car_forbidden_contacts == 0,
                'cargo_retained': not loaded or retention_failures == 0,
                'stopped': bool(np.linalg.norm(stop[3:5]) < .01 and abs(stop[2]) < .01),
            }
            item = {'id': f'{"loaded" if loaded else "empty"}-{label}', 'command': command,
                    'mean_truth_body_velocity': actual.tolist(), 'mean_encoder_velocity': list(encoder_velocity),
                    'encoder_endpoint_error_m': position_error, 'encoder_yaw_error_rad': yaw_error,
                    'true_displacement_m': (endpoint-start).tolist(), 'true_yaw_rad': yaw,
                    'cargo_contact_missing_500hz_steps': retention_failures,
                    'car_forbidden_contact_total': plant.total_car_forbidden_contacts,
                    'motion_and_stop_wall_s': time.monotonic()-began, 'checks': checks,
                    'passed': all(checks.values())}
            report['cases'].append(item)
            (args.output/'result.json').write_text(json.dumps(report, indent=2))
            print(item['id'], item['passed'], item['mean_truth_body_velocity'], flush=True)
    if args.render:
        from PIL import Image
        renderer = mujoco.Renderer(plant.model, height=640, width=960)
        camera = mujoco.MjvCamera()
        camera.lookat[:] = plant.data.xpos[plant.car_body] + np.array([0., 0., .08])
        camera.distance, camera.azimuth, camera.elevation = 1.15, 130., -24.
        options = mujoco.MjvOption(); options.geomgroup[:] = 1
        renderer.update_scene(plant.data, camera=camera, scene_option=options)
        Image.fromarray(renderer.render()).save(args.output/'mecanum-contact-model.png')
        renderer.close()
    report['passed'] = len(report['cases']) == 16 and all(item['passed'] for item in report['cases'])
    (args.output/'result.json').write_text(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
