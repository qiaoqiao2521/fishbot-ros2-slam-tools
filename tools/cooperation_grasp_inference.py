"""Thin official GraspGen-X inference on observed, metre-scale point clouds.

No simulator imports, object mesh completion, training or actuator access. Candidate
poses are returned in the input camera frame; all official branch scores survive.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np


def observed_points(path):
    points = np.load(path, allow_pickle=False)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 21:
        raise ValueError('Expected at least 21 observed XYZ points')
    if not np.isfinite(points).all():
        raise ValueError('Observed cloud contains nonfinite values')
    return np.ascontiguousarray(points, dtype=np.float32)


def candidate_pool(result, camera_from_inference=None):
    poses = np.concatenate([result['grasps_diff'], result['grasps_obb']]).astype(np.float32)
    scores = np.concatenate([result['scores_diff'], result['scores_obb']]).astype(np.float32)
    origins = np.asarray(['diff']*len(result['scores_diff']) + ['obb']*len(result['scores_obb']))
    if poses.shape != (len(scores), 4, 4) or scores.ndim != 1:
        raise ValueError('Official candidate pose and score counts differ')
    if not np.isfinite(poses).all() or not np.isfinite(scores).all():
        raise ValueError('Official candidates contain nonfinite values')
    if camera_from_inference is not None:
        poses = np.asarray(camera_from_inference) @ poses
    if len(poses):
        if not np.allclose(poses[:, 3], [0, 0, 0, 1], atol=1e-5):
            raise ValueError('Official candidates contain invalid homogeneous rows')
        rotations = poses[:, :3, :3]
        if (not np.allclose(rotations.transpose(0, 2, 1) @ rotations, np.eye(3), atol=1e-4)
                or not np.allclose(np.linalg.det(rotations), 1, atol=1e-4)):
            raise ValueError('Official candidates contain invalid rotations')
    return poses.astype(np.float32), scores, origins



def official_client():
    """Import the upstream torch-free client without its eager server facade.

    Upstream serving/__init__.py imports the server and torch even when only
    zmq_client is requested. This private CLI process retains the official
    module files and wire protocol, skipping only that package facade.
    """
    import importlib.util
    import sys
    import types
    spec = importlib.util.find_spec('graspgenx')
    package = 'graspgenx.serving'
    if package not in sys.modules:
        facade = types.ModuleType(package)
        facade.__path__ = [str(Path(spec.origin).parent/'serving')]
        sys.modules[package] = facade
    from graspgenx.serving.zmq_client import GraspGenXClient
    return GraspGenXClient


def serve(args):
    """Own the official loopback server and reuse its eagerly loaded weights."""
    import signal
    os.environ['GRASPGENX_CHECKPOINT_DIR'] = str(args.models.resolve())
    os.environ['GRASPGENX_GRIPPER_CFG_DIR'] = str(args.models.resolve())
    import torch
    from graspgenx.serving.zmq_server import GraspGenXZMQServer
    torch.set_num_threads(2)

    class SeededOfficialServer(GraspGenXZMQServer):
        # The official single-request REP loop serializes this seed reset.
        def _handle_infer_object(self, request):
            np.random.seed(args.seed)
            torch.manual_seed(args.seed)
            torch.cuda.manual_seed_all(args.seed)
            torch.cuda.reset_peak_memory_stats()
            with torch.inference_mode():
                response = super()._handle_infer_object(request)
            torch.cuda.synchronize()
            return response

        def _handle_metadata(self):
            return dict(super()._handle_metadata(), runtime={
                'request_seed': args.seed, 'gpu': torch.cuda.get_device_name(0),
                'torch_version': torch.__version__, 'server_model_load_s': loaded_s,
                'peak_allocated_mib': torch.cuda.max_memory_allocated()/2**20,
                'peak_reserved_mib': torch.cuda.max_memory_reserved()/2**20})

    began = time.monotonic()
    server = SeededOfficialServer(config_path=str(args.models/'release'),
        assets_dir=str(args.models), host='127.0.0.1', port=args.serve_port)
    loaded_s = time.monotonic()-began
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    server.serve_forever()


def warm_candidates(args, points, descriptor):
    """Use the upstream client and return all branch candidates, unfiltered."""
    client_type = official_client()
    began = time.monotonic()
    with client_type(host='127.0.0.1', port=args.server_port, timeout_ms=30000) as client:
        metadata = client.server_metadata
        runtime = metadata.get('runtime', {})
        if runtime.get('request_seed') != args.seed:
            raise ValueError('Owned official server request seed differs from CLI seed')
        poses, scores, tags = client.infer_object(points, descriptor['params'],
            planner='graspmoe', num_grasps=args.samples, grasp_threshold=-1.,
            topk_num_grasps=-1, return_branch_tags=True,
            moe_num_yaws=36, moe_z_offsets_cm=(-2, 0),
            moe_obb_density='dense-topandside')
        if len(tags) != len(scores) or not set(tags) <= {'diff', 'obb'}:
            raise ValueError('Official server branch tags do not align with candidates')
        # The official client caches metadata; request it after inference using
        # a second lightweight client to obtain this request's GPU counters.
    with client_type(host='127.0.0.1', port=args.server_port, timeout_ms=30000) as client:
        runtime = client.server_metadata['runtime']
    tags = np.asarray(tags)
    result = {'grasps_diff': poses[tags == 'diff'], 'scores_diff': scores[tags == 'diff'],
              'grasps_obb': poses[tags == 'obb'], 'scores_obb': scores[tags == 'obb']}
    return result, dict(runtime, model_load_s=0., inference_s=time.monotonic()-began,
        inference_runtime='official_owned_zmq', server_host='127.0.0.1',
        server_port=args.server_port, client_torch_imported='torch' in __import__('sys').modules)


def run(args):
    began = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'started', 'input_kind': 'camera_visible_points',
              'training_steps': 0, 'physics_steps': 0, 'hardware_access': False,
              'candidate_cap': None, 'seed': args.seed,
              'model': 'adithyamurali/GraspGenXModel', 'score_kind': 'pretrained_discriminator',
              'source_revision': 'b9429097728cb1c430dd78b92edf17ba318aad03',
              'model_revision': '7c834043c11a11417e31d6d5ea9355801e40a2c1',
              'physical_grasp_verified': False}
    try:
        points = observed_points(args.points)
        descriptor = json.loads(args.descriptor.read_text())
        report.update(point_count=len(points), descriptor_scope=descriptor.get('validation_scope', 'unspecified'),
                      T_body_model=descriptor.get('T_body_model', np.diag([1., -1., -1., 1.]).tolist()),
                      model_frame=descriptor.get('model_frame', 'original_body_axes_z_forward'))
        transform = np.eye(4)
        if args.camera_to_station:
            transform = np.asarray(json.loads(args.camera_to_station.read_text()), dtype=np.float64)
            if transform.shape != (4, 4) or not np.isfinite(transform).all():
                raise ValueError('Camera-to-station transform must be a finite 4x4 matrix')
            if (not np.allclose(transform[3], [0, 0, 0, 1])
                    or not np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3), atol=1e-5)
                    or not np.isclose(np.linalg.det(transform[:3, :3]), 1, atol=1e-5)):
                raise ValueError('Camera-to-station transform must be rigid')
            points = np.ascontiguousarray(points @ transform[:3, :3].T + transform[:3, 3], dtype=np.float32)
        report['inference_frame'] = 'station_z_up' if args.camera_to_station else 'input_frame_assumed_z_up'
        report['frame_conversion'] = {'input': 'camera_optical', 'output': 'camera_optical',
            'T_station_camera': transform.tolist(), 'source': 'fixed_camera_calibration'}
        os.environ['GRASPGENX_CHECKPOINT_DIR'] = str(args.models.resolve())
        os.environ['GRASPGENX_GRIPPER_CFG_DIR'] = str(args.output.resolve())
        if args.server_port:
            result, runtime = warm_candidates(args, points, descriptor)
            report.update(runtime)
        else:
            import torch
            from graspgenx.grasp_server import GraspGenXSampler
            from graspgenx.samplers import run_graspmoe
            from graspgenx.utils.checkpoint_io import load_model_cfg
            if not torch.cuda.is_available():
                raise RuntimeError('CUDA unavailable for official pretrained inference')
            np.random.seed(args.seed)
            torch.manual_seed(args.seed)
            torch.cuda.manual_seed_all(args.seed)
            torch.set_num_threads(2)
            torch.cuda.reset_peak_memory_stats()
            config = load_model_cfg(args.models/'release/gen', args.models/'release/dis',
                                    'epoch_736.pth', 'epoch_1056.pth')
            loaded = time.monotonic()
            sampler = GraspGenXSampler.from_sweep_volume(config, descriptor['params'])
            torch.cuda.synchronize()
            report['model_load_s'] = time.monotonic()-loaded
            inferred = time.monotonic()
            with torch.inference_mode():
                result = run_graspmoe(points, sampler, num_grasps=args.samples, topk_num_grasps=-1,
                                      num_yaws=36, z_offsets_cm=(-2, 0), obb_density='dense-topandside')
            torch.cuda.synchronize()
            report['inference_s'] = time.monotonic()-inferred
            report.update(inference_runtime='standalone_cuda',
                gpu=torch.cuda.get_device_name(0), torch_version=torch.__version__,
                peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,
                peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20)
        poses, scores, origins = candidate_pool(result, np.linalg.inv(transform))
        np.savez_compressed(args.output/'candidates.npz', poses=poses, scores=scores, origins=origins)
        report.update(status='inference_completed' if len(scores) else 'empty_candidates',
                      candidate_count=len(scores), diffusion_count=int(np.sum(origins == 'diff')),
                      obb_count=int(np.sum(origins == 'obb')), output_frame='input_camera')
        if not len(scores):
            raise RuntimeError('Official model returned no candidates')
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report['elapsed_s'] = time.monotonic()-began
        (args.output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('points', 'descriptor', 'models', 'output'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--camera-to-station', type=Path)
    parser.add_argument('--seed', type=int, default=11)
    parser.add_argument('--samples', type=int, default=16)
    parser.add_argument('--serve-port', type=int)
    parser.add_argument('--server-port', type=int)
    args = parser.parse_args()
    if args.serve_port:
        if args.models is None:
            parser.error('--serve-port requires --models')
        serve(args)
    else:
        if any(getattr(args, name) is None for name in ('points', 'descriptor', 'models', 'output')):
            parser.error('inference requires --points, --descriptor, --models and --output')
        run(args)
