"""Camera geometry and bounded source snapshots for the existing common world.

Only the rendering side receives physics snapshots. Detection receives pixels,
calibration and identity; camera metadata never contains robot or cargo poses.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

CAMERA_NAME = 'cooperation_camera'
CAMERA_FRAME = 'cooperation_camera_optical_frame'
IMAGE_TOPIC = '/cooperation/camera/image_raw'
INFO_TOPIC = '/cooperation/camera/camera_info'
METADATA_TOPIC = '/cooperation/camera/frame_metadata'
FAULT_TOPIC = '/cooperation/observation_fault_trigger'


def system_vision_environment(environment=None):
    """Retain ROS paths, excluding the planning NumPy ABI from system OpenCV."""
    result = dict(os.environ if environment is None else environment)
    paths = [value for value in result.get('PYTHONPATH', '').split(os.pathsep)
             if value and ('/opt/ros/jazzy/' in value or value == '/usr/lib/python3/dist-packages')]
    result['PYTHONPATH'] = os.pathsep.join(paths)
    result['PYTHONDONTWRITEBYTECODE'] = '1'
    result.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    return result


def calibration(dock, tag_lateral_offset=.03):
    focal = 240. / math.tan(math.radians(55.) / 2.)
    return {'schema': 1, 'name': CAMERA_NAME, 'frame_id': CAMERA_FRAME,
            'width': 640, 'height': 480, 'fovy_deg': 55.,
            'supersample_factor': 2,
            # OpenGL window pixel centers are half-integers. Published image
            # arrays use integer pixel indices, including after BOX sampling.
            'k': [focal, 0., 319.5, 0., focal, 239.5, 0., 0., 1.], 'd': [0.]*5,
            'base_camera_translation': [-.06, 0., .260],
            'base_camera_rotation': [[0., 0., -1.], [1., 0., 0.], [0., -1., 0.]],
            'tag_family': 'tag36h11', 'tag_id': 0, 'tag_size_m': .12,
            'plate_size_m': .15, 'tag_lateral_offset_m': tag_lateral_offset,
            'tag_world_position': [dock[0]-.26, dock[1]+tag_lateral_offset, .260],
            'tag_world_rotation': [[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]],
            'tag_dock_translation': [-tag_lateral_offset, -.260, .260],
            'tag_dock_rotation': [[0., -1., 0.], [0., 0., 1.], [-1., 0., 0.]],
            'capture_hz_source_time': 50., 'render_hz_wall_cap': 20., 'light_scale': 1.,
            'shadows_enabled': False,
            'pose_model': 'unconstrained_ippe',
            'detector': {'opencv_version': '4.6.0', 'max_reprojection_px': 1.5,
                         'minimum_edge_px': 60., 'pixel_sigma_px': .5,
                         'subpixel_window': 5, 'subpixel_iterations': 30, 'subpixel_epsilon': .01,
                         'scipy_version': '1.11.4',
                         'ambiguous_error_delta_px': .2,
                         'ambiguity_xy_m': .015, 'ambiguity_yaw_rad': .03,
                         'covariance_floor': [.000025, .000025, .0001]},
            'calibration_source': 'ros-controls/mujoco_ros2_control/0.1.1 camera_plugin.cpp',
            'pixel_center_source': 'Khronos OpenGL-Refpages gl_FragCoord; integer image index = window center - .5',
            'license': 'OpenCV distribution Apache-2.0 AND BSD-3-Clause'}


def add_camera_fixture(root, car, dock, asset_dir, light_scale=1., tag_lateral_offset=.03):
    """Generate the canonical marker with installed OpenCV, without new packages."""
    if not math.isfinite(tag_lateral_offset) or not 0 <= tag_lateral_offset <= .06:
        raise ValueError('tag lateral fixture offset must be within 0..0.06m')
    config = calibration(dock, tag_lateral_offset)
    if not math.isfinite(light_scale) or not .1 <= light_scale <= 1.:
        raise ValueError('camera light scale must be within .1..1')
    config['light_scale'] = float(light_scale)
    ET.SubElement(car.find("body[@name='base_link']"), 'camera', name=CAMERA_NAME,
                  pos='-.06 0 .168', xyaxes='0 1 0 0 0 1', fovy='55', resolution='640 480')
    texture = Path(asset_dir).resolve()/'station-tag36h11-id0.png'
    code = ('import cv2,sys; a=cv2.aruco; d=a.getPredefinedDictionary(a.DICT_APRILTAG_36h11);'
            'm=a.drawMarker(d,0,256,borderBits=1); '
            'm=cv2.copyMakeBorder(m,32,32,32,32,cv2.BORDER_CONSTANT,value=255); '
            'assert cv2.imwrite(sys.argv[1],m)')
    subprocess.run(['/usr/bin/python3', '-B', '-c', code, str(texture)],
                            env=system_vision_environment(), check=True, capture_output=True,
                            text=True, timeout=15)
    asset = root.find('asset')
    ET.SubElement(asset, 'texture', name='station_tag_texture', type='2d', file=str(texture))
    ET.SubElement(asset, 'material', name='station_tag_material', texture='station_tag_texture',
                  texuniform='false', texrepeat='1 1', rgba='1 1 1 1', emission='0', specular='0')
    vertices = [(-.075, -.075, 0.), (.075, -.075, 0.), (.075, .075, 0.), (-.075, .075, 0.),
                (-.075, -.075, -.0005), (.075, -.075, -.0005), (.075, .075, -.0005), (-.075, .075, -.0005)]
    ET.SubElement(asset, 'mesh', name='station_tag_mesh',
                  vertex=' '.join(str(value) for vertex in vertices for value in vertex),
                  texcoord='0 1 1 1 1 0 0 0 0 1 1 1 1 0 0 0',
                  face='0 1 2 0 2 3 4 6 5 4 7 6 0 4 5 0 5 1 1 5 6 1 6 2 2 6 7 2 7 3 3 7 4 3 4 0')
    world = root.find('worldbody')
    x, y, z = config['tag_world_position']
    ET.SubElement(world, 'geom', name='station_tag_plate', type='mesh', mesh='station_tag_mesh',
                  pos=f'{x:.12g} {y:.12g} {z:.12g}',
                  quat='.5 .5 .5 .5', contype='0', conaffinity='0', group='0',
                  material='station_tag_material')
    ET.SubElement(world, 'geom', name='station_tag_occluder', type='box',
                  pos=f'{x+.002:.12g} {y:.12g} {z:.12g}', size='.0003 .09 .09',
                  contype='0', conaffinity='0', group='0', rgba='.15 .15 .15 0')
    import hashlib
    config['tag_texture_file'], config['tag_texture_sha256'] = str(texture), hashlib.sha256(texture.read_bytes()).hexdigest()
    return config


class LatestCameraSnapshot:
    """One replaceable frame; reset fences in-flight rendering and detection."""
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = None
        self.episode_id = None
        self.overwritten = 0
        self.last_stamp = -math.inf

    def offer(self, snapshot):
        with self.lock:
            if snapshot['stamp'] <= self.last_stamp:
                return False
            if snapshot['episode_id'] != self.episode_id:
                self.episode_id = snapshot['episode_id']
                self.pending = None
            self.last_stamp = snapshot['stamp']
            self.overwritten += self.pending is not None
            self.pending = snapshot
            return True

    def take(self):
        with self.lock:
            snapshot, self.pending = self.pending, None
            return snapshot

    def current(self, episode_id):
        with self.lock:
            return episode_id == self.episode_id

    def fence(self, episode_id):
        with self.lock:
            self.episode_id, self.pending = episode_id, None


def downsample_camera_rgb(pixels, config):
    """Use the same BOX sensor sampling in runtime and finite calibration."""
    import numpy as np
    from PIL import Image
    factor = config['supersample_factor']
    if pixels.shape != (config['height']*factor, config['width']*factor, 3):
        raise ValueError('render dimensions do not match the frozen sensor sampling')
    return np.asarray(Image.fromarray(pixels).resize((config['width'], config['height']),
                                                    Image.Resampling.BOX)).copy()


def frame_messages(pixels, snapshot, config):
    from sensor_msgs.msg import Image, CameraInfo
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    image, info, metadata = Image(), CameraInfo(), DiagnosticArray()
    seconds, nanoseconds = divmod(int(round(snapshot['stamp']*1e9)), 1_000_000_000)
    for message in (image, info, metadata):
        message.header.frame_id = config['frame_id']
        message.header.stamp.sec, message.header.stamp.nanosec = seconds, nanoseconds
    image.width, image.height = config['width'], config['height']
    image.encoding, image.step = 'rgb8', image.width*3
    image.data = pixels.tobytes()
    info.width, info.height = image.width, image.height
    info.distortion_model, info.k, info.d = 'plumb_bob', config['k'], config['d']
    info.r = [1., 0., 0., 0., 1., 0., 0., 0., 1.]
    info.p = [info.k[0], 0., info.k[2], 0., 0., info.k[4], info.k[5], 0., 0., 0., 1., 0.]
    status = DiagnosticStatus()
    status.name, status.hardware_id = 'cooperation_camera_frame', config['name']
    status.level, status.message = DiagnosticStatus.OK, 'captured'
    fields = ('scene_sha256', 'manifest_sha256', 'episode_id', 'sequence', 'capture_steady_ns', 'render_duration_s', 'fault_started')
    status.values = [KeyValue(key=key, value=str(snapshot[key]).lower() if isinstance(snapshot[key], bool) else str(snapshot[key])) for key in fields]
    metadata.status = [status]
    return image, info, metadata


class CameraRenderer:
    """Reuse the independent MuJoCo renderer; never block the physics owner."""
    def __init__(self, physics, directory, publish):
        self.physics, self.config, self.publish = physics, physics.identity['manifest']['station_camera'], publish
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.slot = LatestCameraSnapshot()
        self.stop_event = threading.Event()
        self.error, self.rendered = None, 0
        self.thread = threading.Thread(target=self.run, name='cooperation-camera', daemon=True)
        self.thread.start()

    def offer(self):
        moving = False
        if hasattr(self.physics, 'observation_faults'):
            velocity = self.physics.body_velocity(self.physics.car_body)
            moving = math.hypot(*velocity[3:5]) > .005 or abs(velocity[2]) > .005
        occluded = self.physics.observation_faults.occlusion_active(
            wall_time=time.monotonic(), source_stamp=float(self.physics.data.time),
            episode_id=self.physics.episode_id, moving=moving) if hasattr(self.physics, 'observation_faults') else False
        self.slot.offer({'qpos': self.physics.data.qpos.copy(), 'stamp': float(self.physics.data.time),
                         'episode_id': self.physics.episode_id, 'sequence': self.physics.state_sequence,
                         'capture_steady_ns': time.monotonic_ns(), 'occluded': occluded,
                         'fault_started': getattr(self.physics.observation_faults, 'start_wall', None) is not None,
                         'scene_sha256': self.physics.identity['scene_sha256'],
                         'manifest_sha256': self.physics.identity['manifest_sha256']})

    def run(self):
        try:
            import mujoco
            import hashlib
            if hashlib.sha256(Path(self.config['tag_texture_file']).read_bytes()).hexdigest() != self.config['tag_texture_sha256']:
                raise ValueError('station tag texture changed after its frozen calibration')
            model = mujoco.MjModel.from_xml_path(str(self.physics.scene))
            model.light_diffuse[:] *= self.config['light_scale']
            model.light_ambient[:] *= self.config['light_scale']
            model.light_specular[:] *= self.config['light_scale']
            model.vis.headlight.diffuse[:] *= self.config['light_scale']
            model.vis.headlight.ambient[:] *= self.config['light_scale']
            model.vis.headlight.specular[:] *= self.config['light_scale']
            data, options = mujoco.MjData(model), mujoco.MjvOption()
            options.geomgroup[:] = 1
            options.sitegroup[:] = 0
            options.flags[mujoco.mjtVisFlag.mjVIS_RANGEFINDER] = False
            factor = self.config['supersample_factor']
            with mujoco.Renderer(model, height=self.config['height']*factor, width=self.config['width']*factor) as renderer:
                while not self.stop_event.wait(1./self.config['render_hz_wall_cap']):
                    snapshot = self.slot.take()
                    if snapshot is None:
                        continue
                    began = time.monotonic()
                    data.qpos[:], data.time = snapshot['qpos'], snapshot['stamp']
                    model.geom_rgba[model.geom('station_tag_occluder').id, 3] = 1. if snapshot['occluded'] else 0.
                    mujoco.mj_forward(model, data)
                    renderer.update_scene(data, camera=self.config['name'], scene_option=options)
                    renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = self.config['shadows_enabled']
                    pixels = downsample_camera_rgb(renderer.render(), self.config)
                    snapshot['render_duration_s'] = time.monotonic()-began
                    # Publishing and the episode fence share one lock. A reset
                    # cannot leave an old image under a new episode identity.
                    with self.slot.lock:
                        if snapshot['episode_id'] != self.slot.episode_id or snapshot['episode_id'] != self.physics.episode_id:
                            continue
                        self.publish(pixels, snapshot)
                        self.rendered += 1
                    evidence = {key: value for key, value in snapshot.items() if key != 'qpos'}
                    evidence.update(render_duration_s=time.monotonic()-began,
                                    overwritten_snapshots=self.slot.overwritten)
                    with (self.directory/'camera.jsonl').open('a') as stream:
                        stream.write(json.dumps(evidence)+'\n')
        except Exception as error:
            self.error = f'{type(error).__name__}: {error}'

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2.)
