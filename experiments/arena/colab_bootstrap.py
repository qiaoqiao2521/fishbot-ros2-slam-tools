#!/usr/bin/env python3
"""Bounded Colab adapter; runs pinned official Arena after native graphics proof."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from zipfile import ZipFile, ZIP_DEFLATED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=2400)
    parser.add_argument('--accept-eula', action='store_true')
    args = parser.parse_args()
    if not args.accept_eula:
        parser.error('explicit human NVIDIA/Isaac license acceptance is required')
    if not 120 <= args.timeout <= 2640:
        parser.error('timeout must be 120..2640 seconds')
    work = args.work.resolve()
    if not work.is_relative_to(Path('/content')):
        parser.error('work must be a dedicated Colab /content directory')
    root = Path(__file__).resolve().parents[2]
    artifacts = work / 'artifacts'
    artifacts.mkdir(parents=True, exist_ok=False)
    logs = artifacts / 'logs'; logs.mkdir()
    started = time.monotonic(); deadline = started + args.timeout
    report = {'schema_version': 1, 'status': 'running', 'phase': 'hardware', 'phases': [],
              'timeout_s': args.timeout, 'human_eula_accepted': True,
              'kernel_driver_changed': False, 'graphics_verified': False,
              'arena_smoke_completed': False, 'pipeline_completed': False, 'policy_success': None}
    env = os.environ.copy()
    for key in ('UV_SYSTEM_PYTHON', 'UV_PYTHON', 'UV_PROJECT_ENVIRONMENT', 'VIRTUAL_ENV',
                'OMNI_KIT_ACCEPT_EULA', 'ACCEPT_EULA', 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
        env.pop(key, None)
    env.update(GIT_TERMINAL_PROMPT='0', MPLBACKEND='agg', PIP_DISABLE_PIP_VERSION_CHECK='1')

    def save():
        report['elapsed_wall_s'] = round(time.monotonic()-started, 3)
        path = artifacts / 'report.json'; temporary = artifacts / 'report.tmp'
        temporary.write_text(json.dumps(report, indent=2)); temporary.replace(path)

    def phase(name, command, limit, *, cwd=None, allow_failure=False):
        report['phase'] = name
        item = {'name': name, 'status': 'running'}; report['phases'].append(item); save()
        remaining = deadline-time.monotonic()-15
        if remaining <= 0: raise TimeoutError('bounded Colab deadline exhausted')
        output = artifacts / (name+'.json')
        with (logs/(name+'.log')).open('w') as stream, output.open('w') as stdout:
            process = subprocess.Popen(command, cwd=cwd or work, env=env, stdout=stdout,
                                       stderr=stream, start_new_session=True)
            try:
                code = process.wait(timeout=min(limit, remaining))
            except BaseException:
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
                item.update(status='interrupted'); save(); raise
        item.update(returncode=code, status='passed' if code == 0 else 'failed'); save()
        if code != 0 and not allow_failure:
            raise RuntimeError(name+' failed; native output and log retained')
        return output

    try:
        raw = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,driver_version',
                              '--format=csv,noheader,nounits'], capture_output=True, text=True,
                             check=True, timeout=15).stdout.strip()
        rows = [line.split(',') for line in raw.splitlines()]
        if len(rows) != 1 or len(rows[0]) != 3: raise RuntimeError('expected one GPU')
        name, memory, driver = [part.strip() for part in rows[0]]
        report['gpu'] = {'name': name, 'memory_mib': int(memory), 'driver': driver}; save()
        if 'L4' not in name or int(memory) < 16384:
            raise RuntimeError('expected the requested L4 with sufficient memory')
        if not re.fullmatch(r'\d+\.\d+\.\d+', driver): raise RuntimeError('invalid driver identity')
        preflight = root/'experiments/arena/colab_preflight.py'
        initial = artifacts/'native-before.json'
        phase('native_before', [sys.executable, str(preflight), '--output', str(initial)], 30,
              allow_failure=True)
        report['graphics_verified'] = json.loads(initial.read_text())['vulkan']['nvidia_verified']
        if not report['graphics_verified']:
            archive = work / ('NVIDIA-Linux-x86_64-'+driver+'.run')
            url = 'https://download.nvidia.com/XFree86/Linux-x86_64/'+driver+'/'+archive.name
            report['graphics_source'] = url; save()
            phase('graphics_download', ['curl', '--fail', '--location', '--retry', '0',
                                       '--max-time', '240', '--output', str(archive), url], 250)
            report['graphics_archive_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest(); save()
            phase('graphics_archive_check', ['sh', str(archive), '--check'], 60)
            extracted = work/'nvidia-graphics-source'
            phase('graphics_extract', ['sh', str(archive), '--extract-only', '--target', str(extracted)], 120)
            # Keep only 64-bit driver ELF libraries in a private search path.
            # No installer, system links, kernel modules or host configuration.
            libraries = work/'nvidia-graphics-lib'; libraries.mkdir()
            count = 0
            for path in extracted.rglob('*.so*'):
                if not path.is_file() or path.name.startswith(('libcuda.', 'libnvidia-ml.')): continue
                if not path.name.startswith(('libnvidia-', 'libEGL_nvidia.', 'libGLX_nvidia.')): continue
                with path.open('rb') as stream: header = stream.read(20)
                if len(header) < 20 or header[:5] != b'\x7fELF\x02' or header[18:20] != b'\x3e\x00': continue
                target = libraries/path.name
                if target.exists(): continue
                target.symlink_to(path)
                dynamic = subprocess.run(['readelf', '-d', str(path)], capture_output=True,
                                         text=True, check=True, timeout=8).stdout
                soname = re.search(r'\(SONAME\).*\[([^]]+)\]', dynamic)
                if soname:
                    link = libraries/soname.group(1)
                    if not link.exists(): link.symlink_to(path)
                count += 1
            egl = libraries/'libEGL_nvidia.so.0'
            if not egl.is_file(): raise RuntimeError('official archive missing NVIDIA EGL ICD library')
            icd = work/'nvidia_icd.json'
            definitions = list(extracted.rglob('nvidia_icd.json'))
            if len(definitions) != 1: raise RuntimeError('official NVIDIA ICD definition missing or ambiguous')
            definition = json.loads(definitions[0].read_text())
            definition['ICD']['library_path'] = str(egl)
            icd.write_text(json.dumps(definition))
            env['LD_LIBRARY_PATH'] = str(libraries)+os.pathsep+env.get('LD_LIBRARY_PATH','')
            env['VK_ICD_FILENAMES'] = str(icd); env['VK_DRIVER_FILES'] = str(icd)
            report['private_graphics_library_count'] = count
            report['private_icd'] = str(icd); save()
            final = artifacts/'native-after.json'
            phase('native_after', [sys.executable, str(preflight), '--output', str(final)], 45)
            report['graphics_verified'] = json.loads(final.read_text())['vulkan']['nvidia_verified']; save()
            if not report['graphics_verified']: raise RuntimeError('NVIDIA Vulkan/RT remained unverified')
        uv = work/'uv-tool'
        phase('uv_install', [sys.executable, '-m', 'pip', 'install', '--target', str(uv),
                             'uv==0.11.15'], 120)
        uv_binary = uv/'bin'/'uv'
        if not uv_binary.is_file() or not os.access(uv_binary, os.X_OK):
            raise RuntimeError('pinned uv standalone binary missing after installation')
        env['PATH'] = str(uv_binary.parent)+os.pathsep+env.get('PATH','')
        if not subprocess.run(['git', 'lfs', 'version'], env=env, capture_output=True).returncode == 0:
            phase('git_lfs_tools', ['bash','-c','apt-get update -qq && apt-get install -y -qq git-lfs'], 150)
        source = work/'IsaacLab-Arena'
        cli = [sys.executable, '-B', str(root/'tools/fishbot_arena.py')]
        phase('prepare', [*cli,'prepare','--source',str(source)], 300)
        phase('doctor', [*cli,'doctor','--source',str(source)], 30)
        phase('install', [*cli,'install','--source',str(source),'--accept-eula'], 1500)
        phase('smoke', [*cli,'smoke','--source',str(source),'--accept-eula'], 240)
        report['arena_smoke_completed'] = True; save()
        result = phase('evaluate', [*cli,'evaluate','--source',str(source),'--accept-eula',
                                   '--output',str(artifacts/'evaluation')], 360)
        receipt = json.loads(result.read_text())
        report['pipeline_completed'] = receipt.get('pipeline_completed') is True
        report['policy_success'] = receipt.get('policy_success')
        if not report['pipeline_completed']: raise RuntimeError('native two-Run evaluation incomplete')
        report['status'] = 'completed'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error))
    finally:
        save()
        bundle = work/'artifacts.zip'
        with ZipFile(bundle,'w',ZIP_DEFLATED) as archive:
            for path in artifacts.rglob('*'):
                if path.is_file() and path.suffix in ('.json','.jsonl','.log','.html','.csv'):
                    archive.write(path,path.relative_to(artifacts))
        print(json.dumps({'status':report['status'],'phase':report['phase'],
                          'pipeline_completed':report['pipeline_completed'],'bundle':str(bundle)}),flush=True)
    return 0 if report['pipeline_completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
