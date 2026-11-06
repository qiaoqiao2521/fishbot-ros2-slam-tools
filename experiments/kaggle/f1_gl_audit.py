#!/usr/bin/env python3
"""Inspect existing EGL driver choices before restoring the visual task runtime."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

OUTPUT = Path('/kaggle/working/gl-audit')
WORK = Path('/tmp/f1-gl-audit')
MAGIC = b'FISHBOT-TAR-GZIP-1\n'

WORKER = r'''
import json,os,sys,time
from pathlib import Path
import mujoco,numpy as np
from PIL import Image
from cooperation_camera import downsample_camera_rgb,render_depth
manifest=json.loads(Path(sys.argv[1]).read_text()); snapshot=json.loads(Path(sys.argv[2]).read_text())
output=Path(sys.argv[3]);output.mkdir(parents=True,exist_ok=True)
config=manifest['station_camera'];model=mujoco.MjModel.from_xml_path(manifest['world_xml'])
for values in (model.light_diffuse,model.light_ambient,model.light_specular,
               model.vis.headlight.diffuse,model.vis.headlight.ambient,model.vis.headlight.specular):
 values[:]*=config['light_scale']
data=mujoco.MjData(model);data.qpos[:]=snapshot['qpos'];data.qvel[:]=snapshot['qvel'];data.time=snapshot['time']
options=mujoco.MjvOption();options.geomgroup[:]=1;options.sitegroup[:]=0
options.flags[mujoco.mjtVisFlag.mjVIS_RANGEFINDER]=False
report={'scope':'v4 recorded R0 query; zero mj_step/ROS nodes/goals',
 'source_sequence':snapshot['sequence'],'source_episode':snapshot['episode_id'],
 'gl_backend':os.environ.get('MUJOCO_GL'),'device':os.environ.get('MUJOCO_EGL_DEVICE_ID'),
 'vendor_json':os.environ.get('__EGL_VENDOR_LIBRARY_FILENAMES'),
 'rgb_resolution':[config['width']*config['supersample_factor'],config['height']*config['supersample_factor']],
 'depth_resolution':[config['width'],config['height']],
 'model':{'nq':model.nq,'nv':model.nv,'nbody':model.nbody,'ngeom':model.ngeom,'nmesh':model.nmesh},
 'timings':[],'task_acceptance':False}
try:
 from mujoco.egl import egl_ext as EGL
 devices=EGL.eglQueryDevicesEXT();report['egl_device_count']=len(devices)
 report['egl_devices']=[str(x)for x in devices]
except Exception as error:report['egl_query_error']=type(error).__name__+': '+str(error)
with mujoco.Renderer(model,height=config['height']*config['supersample_factor'],width=config['width']*config['supersample_factor']) as rgb_renderer:
 with mujoco.Renderer(model,height=config['height'],width=config['width']) as depth_renderer:
  depth_renderer.enable_depth_rendering()
  for index in range(3):
   begin=time.monotonic();mujoco.mj_forward(model,data);forward_done=time.monotonic()
   rgb_renderer.update_scene(data,camera=config['name'],scene_option=options)
   rgb_renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW]=config['shadows_enabled']
   updated=time.monotonic();pixels=rgb_renderer.render();color_done=time.monotonic()
   rgb=downsample_camera_rgb(pixels,config);downsample_done=time.monotonic()
   depth=render_depth(depth_renderer,model,data,config,options);end=time.monotonic()
   report['timings'].append({'index':index,'mj_forward_s':forward_done-begin,
    'update_scene_s':updated-forward_done,'rgb_render_readback_s':color_done-updated,
    'downsample_s':downsample_done-color_done,'depth_total_s':end-downsample_done,'total_s':end-begin})
   from OpenGL.GL import GL_RENDERER,GL_VENDOR,GL_VERSION,glGetString
   report['graphics']={name:(glGetString(key)or b'').decode('utf-8','replace')for name,key in [('vendor',GL_VENDOR),('renderer',GL_RENDERER),('version',GL_VERSION)]}
   if index==0:
    Image.fromarray(rgb).save(output/'rgb.png');np.save(output/'depth.npy',depth,allow_pickle=False)
report['hardware_nvidia']= 'NVIDIA' in report['graphics']['vendor'].upper()
(output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
'''


def execute(name, arguments, *, env=None, timeout=180, required=True):
    started = time.monotonic()
    with (OUTPUT/(name+'.log')).open('w') as stream:
        result = subprocess.run(arguments, stdout=stream, stderr=subprocess.STDOUT,
                                env=env, timeout=timeout)
    row = {'name': name, 'returncode': result.returncode,
           'elapsed_wall_s': time.monotonic()-started}
    print(json.dumps(row), flush=True)
    if required and result.returncode:
        raise RuntimeError(name+' failed; see its retained log')
    return row


def extract(path, destination, prefixed=False):
    with path.open('rb') as source:
        if prefixed:
            source.read(len(MAGIC))
        with tarfile.open(fileobj=source, mode='r|gz') as archive:
            archive.extractall(destination, filter='data')


def main():
    OUTPUT.mkdir(parents=True, exist_ok=False)
    WORK.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, OUTPUT/'audit-code.py')
    snapshots = list(Path('/kaggle/input').rglob('f1-visual-source.tar.gz.bin'))
    fixtures = list(Path('/kaggle/input').rglob('graphics-fixture.tar.gz.bin'))
    runtimes = list(Path('/kaggle/input').rglob('fishbot-runtime.tar.gz.bin'))
    if len(snapshots) != 1 or len(fixtures) != 1 or len(runtimes) != 1:
        raise RuntimeError('Attach the existing runtime and selected visual source/graphics fixture')
    extract(snapshots[0], WORK/'sources')
    extract(runtimes[0], WORK/'sources/fishbot', prefixed=True)
    fixture = WORK/'fixture'
    extract(fixtures[0], fixture)
    recorded = json.loads((fixture/'snapshot.json').read_text())
    old_runtime = Path(recorded['old_runtime_prefix'])
    old_runtime.mkdir(parents=True, exist_ok=True)
    for name in ['fishbot', 'so101']:
        (old_runtime/name).symlink_to(WORK/'sources'/name, target_is_directory=True)
    old_scene = Path(recorded['old_scene_prefix'])
    old_scene.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture/'scene', old_scene)
    shutil.copyfile(fixture/'snapshot.json', OUTPUT/'recorded-snapshot.json')
    execute('nvidia-smi', ['nvidia-smi'], timeout=30)
    execute('apt-index', ['apt-get', 'update'], timeout=120)
    execute('probe-dependencies', ['apt-get', 'install', '-y', '--no-install-recommends',
        'python3.12', 'python3.12-venv', 'libegl1', 'libgl1', 'libosmesa6'], timeout=180)
    python = str(WORK/'venv/bin/python')
    execute('probe-venv', ['/usr/bin/python3.12', '-m', 'venv', str(WORK/'venv')])
    execute('probe-mujoco', [python, '-m', 'pip', 'install', '--no-cache-dir',
        'mujoco==3.3.7', 'Pillow'], timeout=180)
    vendor_files = list(Path('/usr/share/glvnd/egl_vendor.d').glob('*.json')) + list(
        Path('/etc/glvnd/egl_vendor.d').glob('*.json'))
    vendors = {str(path): json.loads(path.read_text()) for path in vendor_files}
    loader = subprocess.run(['ldconfig', '-p'], capture_output=True, text=True)
    (OUTPUT/'graphics-libraries.log').write_text('\n'.join(line for line in loader.stdout.splitlines()
        if any(word in line.lower() for word in ['nvidia', 'libegl', 'libglx'])))
    libraries = []
    for directory in ['/usr/lib/x86_64-linux-gnu', '/usr/lib64-nvidia', '/usr/local/nvidia/lib64']:
        for pattern in ['libEGL_nvidia.so*', 'libnvidia-eglcore.so*', 'libnvidia-glsi.so*']:
            libraries.extend(str(path) for path in Path(directory).glob(pattern) if path.is_file())
    (OUTPUT/'driver-inventory.json').write_text(json.dumps({'vendor_json': vendors,
        'nvidia_graphics_files': sorted(set(libraries))}, indent=2)+'\n')
    runtime = WORK/'sources/fishbot/workspaces/fishbot_mujoco_ws/.runtime'
    base_env = dict(os.environ, MUJOCO_GL='egl', PYTHONPATH=str(WORK/'sources/fishbot/tools'),
        LD_LIBRARY_PATH=':'.join([str(runtime/'opt/ros/jazzy/lib'),
            str(runtime/'opt/ros/jazzy/opt/mujoco_vendor/lib'),
            str(runtime/'usr/lib/x86_64-linux-gnu'), os.environ.get('LD_LIBRARY_PATH', '')]))
    worker = WORK/'render_worker.py';worker.write_text(WORKER)
    choices = [('default-existing', {})]
    nvidia_vendors = [path for path, value in vendors.items() if 'nvidia' in json.dumps(value).lower()]
    nvidia_egl = [path for path in libraries if Path(path).name.startswith('libEGL_nvidia')]
    if not nvidia_vendors and nvidia_egl:
        private = WORK/'existing-nvidia-vendor.json'
        private.write_text(json.dumps({'file_format_version': '1.0.0',
            'ICD': {'library_path': nvidia_egl[0]}}))
        try:
            shutil.copyfile(private, OUTPUT/private.name)
        except OSError as error:
            print('WARNING: vendor config remains in the recorded temporary path:',
                  type(error).__name__, flush=True)
        nvidia_vendors.append(str(private))
    for vendor in nvidia_vendors:
        choices.append(('existing-nvidia-0', {'__EGL_VENDOR_LIBRARY_FILENAMES': vendor,
                                             'MUJOCO_EGL_DEVICE_ID': '0'}))
    report = {'scope': 'existing-driver path selection; no model inference or physical steps',
              'attempts': [], 'selected_environment': None, 'task_acceptance': False}
    began = time.monotonic()
    index = 0
    while index < len(choices) and time.monotonic()-began < 60:
        label, selected = choices[index];index += 1
        target = OUTPUT/label;target.mkdir(exist_ok=True)
        try:
            row = execute(label, [python, str(worker), str(old_scene/'scene-manifest.json'),
                str(fixture/'snapshot.json'), str(target)], env=dict(base_env, **selected),
                timeout=20, required=False)
        except subprocess.TimeoutExpired:
            row = {'name': label, 'returncode': 124}
        result_file = target/'report.json'
        details = json.loads(result_file.read_text()) if result_file.exists() else None
        report['attempts'].append({'execution': row, 'environment': selected, 'result': details})
        if details and details.get('hardware_nvidia'):
            report['selected_environment'] = selected
            break
        if details and details.get('egl_device_count', 0) > 1 and not selected:
            choices.append(('existing-device-1', {'MUJOCO_EGL_DEVICE_ID': '1'}))
    hardware = report['selected_environment'] is not None
    report['hardware_ready'] = hardware
    report['status'] = 'existing_hardware_renderer_selected' if hardware else 'no_existing_nvidia_hardware_renderer'
    (OUTPUT/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    if not hardware:
        print('No existing NVIDIA hardware render path; model download and Factory remain unexecuted.', flush=True)
        return
    os.environ.update(base_env)
    os.environ.update(report['selected_environment'])
    # This is the already verified v4 source entry, not a new task controller.
    source = WORK/'sources/fishbot/experiments/kaggle/f1_visual_recovery.py'
    spec = importlib.util.spec_from_file_location('visual_recovery', source)
    adapter = importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    adapter.cloud()


if __name__ == '__main__':
    main()
