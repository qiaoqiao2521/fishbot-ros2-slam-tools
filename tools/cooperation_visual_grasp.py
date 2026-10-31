"""On-demand RGB-D source and isolated pretrained inference for a held workcell.

Physics state is consumed only by the rendering producer. The model subprocess
receives a visible point cloud and the public gripper descriptor, never state.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time


def model_proposals(manifest, snapshot, arm_id, cargo_id, *, model=None):
    import mujoco
    import numpy as np
    from cooperation_workcell_vision import render_rgbd, object_points
    config = manifest['pretrained_grasp']
    camera = dict(manifest['workcell_cameras'][arm_id], target_id=cargo_id)
    directory = Path(config['output_directory'])/(
        snapshot['episode_id']+'-'+arm_id+'-'+cargo_id+'-'+str(snapshot['sequence']))
    directory.mkdir(parents=True, exist_ok=True)
    if model is None:
        model = mujoco.MjModel.from_xml_path(manifest['world_xml'])
    data = mujoco.MjData(model)
    data.qpos[:] = snapshot['qpos']
    data.time = snapshot['stamp']
    mujoco.mj_forward(model, data)
    # This boundary deliberately discards state before inference.
    rgb, depth = render_rgbd(model, data, camera)
    from PIL import Image
    Image.fromarray(rgb).save(directory/'rgb.png')
    np.save(directory/'depth.npy', depth)
    (directory/'camera.json').write_text(json.dumps(camera, indent=2)+'\n')
    observed = object_points(rgb, depth, camera)
    points = observed['points_camera']
    Image.fromarray((observed['mask']*255).astype(np.uint8)).save(directory/'mask.png')
    calibration_path = directory/'camera-to-station.json'
    calibration_path.write_text(json.dumps(camera['T_station_camera'])+'\n')
    np.save(directory/'points.npy', np.ascontiguousarray(points, dtype=np.float32))
    observation = {'stamp': snapshot['stamp'], 'episode_id': snapshot['episode_id'],
        'sequence': snapshot['sequence'], 'arm_id': arm_id, 'cargo_id': cargo_id,
        'point_count': len(points), 'mask_kind': 'declared_colour_prior',
        'frame': camera['frame_id'], 'source': 'rendered_rgbd_visible_surface_only'}
    (directory/'observation.json').write_text(json.dumps(observation, indent=2)+'\n')
    inference = directory/'inference'
    command = [config['python'], '-B', str(Path(__file__).with_name('cooperation_grasp_inference.py')),
        '--points', str(directory/'points.npy'), '--descriptor', config['descriptor'],
        '--models', config['models'], '--output', str(inference),
        '--camera-to-station', str(calibration_path)]
    server_port = os.environ.get('FISHBOT_GRASP_SERVER_PORT')
    if server_port:
        command += ['--server-port', server_port]
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    began = time.monotonic()
    with (directory/'inference.log').open('w') as log:
        try:
            # The existing query owner enforces the complete 30s deadline and
            # reaps this process group. Do not add an earlier inference cutoff
            # that rejects completed output during Torch process teardown.
            subprocess.run(command, env=environment, check=True, timeout=30.,
                           stdout=log, stderr=subprocess.STDOUT)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError('GraspGen-X inference failed: '+type(error).__name__+
                               '; log: '+str(directory/'inference.log')) from error
    archive = np.load(inference/'candidates.npz', allow_pickle=False)
    poses, scores = archive['poses'], archive['scores']
    origins = archive['origins'] if 'origins' in archive else ['model']*len(scores)
    matrix = np.asarray(camera['T_station_camera'], dtype=float)
    candidates = [{'index': int(i), 'score': float(scores[i]), 'origin': str(origins[i]),
                   'pose_station': (matrix@poses[i]).tolist()}
                  for i in np.argsort(-scores, kind='stable')]
    report_path = inference/'report.json'
    report = json.loads(report_path.read_text())
    report.update(elapsed_owner_wall_s=time.monotonic()-began,
                  source_directory=str(directory), report_path=str(report_path))
    return {'candidates': candidates, 'observation': observation, 'inference': report,
            'T_body_model': report['T_body_model']}
