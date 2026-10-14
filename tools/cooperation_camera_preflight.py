#!/usr/bin/env python3
"""Twenty finite RGB renders; no ROS, actions, dynamics or network access."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from cooperation_camera import system_vision_environment, downsample_camera_rgb


def run(args):
    import mujoco
    import numpy as np
    from PIL import Image
    from cooperation_scene import build_scene
    output = args.output.resolve()
    if output.exists():
        raise ValueError('preflight output must be new; preserve earlier evidence')
    output.mkdir(parents=True)
    project = Path(__file__).resolve().parents[1]
    sources = [project/'tools'/name for name in ('cooperation_scene.py', 'cooperation_camera.py',
                                               'cooperation_station_vision.py', 'cooperation_camera_preflight.py')]
    receipts = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    distances, yaws = [.20, .35, .90, 1.05], [-.14, -.07, 0., .07, .14]
    declaration = {'schema': 1, 'scope': 'static_render_calibration_only',
                   'distances_camera_tag_at_zero_yaw_m': distances, 'robot_yaw_rad': yaws,
                   'case_count': 20, 'positive_count': 15, 'resolution_rejection_count': 5,
                   'quality_gate': .75, 'xy_error_gate_m': .02, 'yaw_error_gate_rad': .04,
                   'source_start': receipts, 'started_wall_time': time.time()}
    (output/'declaration.json').write_text(json.dumps(declaration, indent=2)+'\n')
    manifest = build_scene(args.so101_project, project, output/'scene', camera=True,
                           tag_lateral_offset=args.tag_lateral_offset, camera_light_scale=args.camera_light_scale)
    config = manifest['station_camera']
    model = mujoco.MjModel.from_xml_path(manifest['world_xml'])
    for values in (model.light_diffuse, model.light_ambient, model.light_specular,
                   model.vis.headlight.diffuse, model.vis.headlight.ambient, model.vis.headlight.specular):
        values[:] *= config['light_scale']
    data = mujoco.MjData(model)
    data.qpos[:6] = manifest['initial_arm_q6']
    options = mujoco.MjvOption()
    options.geomgroup[:] = 1
    options.sitegroup[:] = 0
    options.flags[mujoco.mjtVisFlag.mjVIS_RANGEFINDER] = False
    cases = []
    tag = config['tag_world_position']
    factor = config['supersample_factor']
    with mujoco.Renderer(model, height=config['height']*factor, width=config['width']*factor) as renderer:
        for distance in distances:
            for yaw in yaws:
                x, y = tag[0]+distance+.06, manifest['dock_pose'][1]
                data.qpos[13:20] = [x, y, 0., math.cos(yaw/2), 0., 0., math.sin(yaw/2)]
                mujoco.mj_forward(model, data)
                renderer.update_scene(data, camera=config['name'], scene_option=options)
                renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = config['shadows_enabled']
                image = output/f'case-{len(cases):02d}.png'
                began = time.monotonic()
                Image.fromarray(downsample_camera_rgb(renderer.render(), config)).save(image)
                dx, dy = manifest['dock_pose'][0]-x, manifest['dock_pose'][1]-y
                expected = [math.cos(yaw)*dx+math.sin(yaw)*dy,
                            -math.sin(yaw)*dx+math.cos(yaw)*dy,
                            math.atan2(math.sin(math.pi-yaw), math.cos(math.pi-yaw))]
                cases.append({'case': len(cases), 'image': str(image), 'distance_m': distance,
                              'yaw_rad': yaw, 'expected_kind': 'resolution_rejection' if distance == 1.05 else 'positive',
                              'render_readback_save_duration_s': time.monotonic()-began,
                              'expected_relative_for_oracle_only': expected})
    index = output/'cases.json'
    index.write_text(json.dumps(cases, indent=2)+'\n')
    detector_inputs = output/'detector-inputs.json'
    detector_inputs.write_text(json.dumps([{'case': case['case'], 'image': case['image']} for case in cases]))
    code = r'''
import json,sys,time
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,sys.argv[1])
from cooperation_station_vision import estimate_station
manifest=json.loads(Path(sys.argv[2]).read_text())
cases=json.loads(Path(sys.argv[3]).read_text())
results=[]
for case in cases:
 rgb=np.asarray(Image.open(case['image']).convert('RGB'));began=time.monotonic()
 metrics=estimate_station(rgb,manifest['station_camera'])
 metrics['inference_duration_s']=time.monotonic()-began
 results.append({'case':case['case'],**metrics})
Path(sys.argv[4]).write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')
'''
    result = subprocess.run(['/usr/bin/python3', '-B', '-c', code, str(project/'tools'),
                             str(output/'scene/scene-manifest.json'), str(detector_inputs), str(output/'detections.json')],
                            env=system_vision_environment(), capture_output=True, text=True, timeout=60)
    if result.returncode:
        (output/'detector-error.txt').write_text(result.stdout+result.stderr)
        raise RuntimeError('system OpenCV detector failed; preserve preflight artifacts')
    detections = json.loads((output/'detections.json').read_text())
    for case, detected in zip(cases, detections):
        case['detector'] = detected
        case['quality_admitted'] = detected['detected'] and detected['confidence'] >= .75
        if case['expected_kind'] == 'resolution_rejection':
            case['passed'] = (not detected['detected'] and detected['reason'] == 'insufficient_resolution'
                              and detected['relative'] is None and detected['covariance'] is None)
        elif detected['detected']:
            expected, actual = case['expected_relative_for_oracle_only'], detected['relative']
            case['xy_error_m'] = math.dist(expected[:2], actual[:2])
            case['yaw_error_rad'] = abs(math.atan2(math.sin(expected[2]-actual[2]), math.cos(expected[2]-actual[2])))
            case['passed'] = case['quality_admitted'] and case['xy_error_m'] <= .02 and case['yaw_error_rad'] <= .04
        else:
            case['passed'] = False
    end = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    report = {'scope': declaration['scope'], 'cases': cases,
              'detected_cases': sum(item['detector']['detected'] for item in cases),
              'passed_cases': sum(item['passed'] for item in cases),
              'positive_passed': sum(item['passed'] and item['expected_kind'] == 'positive' for item in cases),
              'resolution_rejection_passed': sum(item['passed'] and item['expected_kind'] == 'resolution_rejection' for item in cases),
              'source_start': receipts, 'source_end': end, 'source_unchanged': receipts == end,
              'scene_sha256': hashlib.sha256(Path(manifest['world_xml']).read_bytes()).hexdigest(),
              'manifest_sha256': hashlib.sha256((output/'scene/scene-manifest.json').read_bytes()).hexdigest(),
              'passed': len(cases) == 20 and all(item['passed'] for item in cases) and receipts == end,
              'finished_wall_time': time.time(), 'no_ros_or_motion': True}
    (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': report['passed'], 'detected': report['detected_cases'],
                      'passed_cases': report['passed_cases'], 'report': str(output/'report.json')}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--so101-project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tag-lateral-offset', type=float, default=.03)
    parser.add_argument('--camera-light-scale', type=float, default=1.)
    args = parser.parse_args()
    os.environ.setdefault('MUJOCO_GL', 'egl')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
