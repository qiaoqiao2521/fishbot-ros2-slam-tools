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
import uuid
from zipfile import ZipFile, ZIP_DEFLATED


INPUT_FILES = ('tools/fishbot_arena.py', 'experiments/arena/upstream.lock.json',
               'experiments/arena/evaluation.yaml', 'experiments/arena/colab_preflight.py',
               'experiments/arena/colab_bootstrap.py')


def input_hashes(root):
    result = {}
    for name in INPUT_FILES:
        try:
            result[name] = hashlib.sha256((root/name).read_bytes()).hexdigest()
        except OSError:
            result[name] = None
    return result


def checkpoint_artifacts(work, report):
    """Publish one atomic evidence snapshot, including interrupted phases."""
    artifacts = work/'artifacts'
    temporary = artifacts/'report.tmp'
    temporary.write_text(json.dumps(report, indent=2))
    temporary.replace(artifacts/'report.json')
    bundle = work/('artifacts-'+uuid.uuid4().hex+'.zip')
    pending = bundle.with_suffix('.zip.tmp')
    manifest = {}
    with ZipFile(pending, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(artifacts.rglob('*')):
            if path.is_symlink():
                continue
            if path.is_file() and path.suffix in ('.json', '.jsonl', '.log', '.html', '.csv'):
                name = str(path.relative_to(artifacts))
                payload = path.read_bytes()
                archive.writestr(name, payload)
                manifest[name] = {'size_bytes': len(payload),
                                  'sha256': hashlib.sha256(payload).hexdigest()}
    pending.replace(bundle)
    # Publish the index last. Report completion alone does not prove packaging.
    index = {'schema_version': 1, 'report_final': report.get('report_final') is True,
             'status': report.get('status'), 'files': manifest,
             'report_sha256': manifest['report.json']['sha256'],
             'bundle': {'name': bundle.name, 'size_bytes': bundle.stat().st_size,
                        'sha256': hashlib.sha256(bundle.read_bytes()).hexdigest()}}
    pending_index = work/'recovery-index.json.tmp'
    pending_index.write_text(json.dumps(index, indent=2))
    pending_index.replace(work/'recovery-index.json')
    # Keep the legacy checkpoint path for best-effort recovery without an index.
    alias = work/'artifacts.zip.tmp'
    alias.unlink(missing_ok=True)
    os.link(bundle, alias)
    alias.replace(work/'artifacts.zip')
    return bundle


def smoke_readback(receipt, log):
    """Verify native execution evidence, without scoring the policy."""
    if (type(receipt.get('returncode')) is not int or receipt['returncode'] != 0
            or receipt.get('source_unchanged') is not True
            or receipt.get('source_after', {}).get('verified') is not True):
        raise RuntimeError('native smoke lacks normal exit and unchanged source receipts')
    if not re.search(r'Steps:\s*100%[^\r\n]*\b20/20\b', log):
        raise RuntimeError('native smoke lacks the configured 20 completed steps')
    if ('SimulationContext cleared' not in log or 'SIGSEGV' in log
            or 'fast shutdown not supported with jupyter notebooks' in log):
        raise RuntimeError('native smoke shutdown evidence is incomplete or failed')
    return {'steps_completed': 20, 'returncode': 0, 'context_cleared': True,
            'log_sha256': hashlib.sha256(log.encode()).hexdigest()}


def stop_owned_group(process, grace=5):
    """Stop the new session created by this worker, including native descendants."""
    result = {'group_absent': False, 'sigkill_sent': False, 'leader_returncode': None}
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        result['group_absent'] = True
    deadline = time.monotonic()+grace
    while not result['group_absent'] and time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            result['group_absent'] = True
            break
        time.sleep(min(.05, max(0, deadline-time.monotonic())))
    if not result['group_absent']:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            result['sigkill_sent'] = True
        except ProcessLookupError:
            result['group_absent'] = True
    result['leader_returncode'] = process.wait(timeout=5)
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        result['group_absent'] = True
    return result


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
    closing = False
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def request_stop(signum, frame):
        nonlocal closing
        if closing:
            return
        closing = True
        raise InterruptedError('termination requested; preserving native evidence')

    signal.signal(signal.SIGTERM, request_stop)
    report = {'schema_version': 1, 'status': 'running', 'phase': 'hardware', 'phases': [],
              'timeout_s': args.timeout, 'human_eula_accepted': True,
              'kernel_driver_changed': False, 'graphics_verified': False,
              'arena_smoke_completed': False, 'pipeline_completed': False, 'policy_success': None,
              'report_final': False, 'input_sha256_before': input_hashes(root)}
    env = os.environ.copy()
    for key in ('UV_SYSTEM_PYTHON', 'UV_PYTHON', 'UV_PROJECT_ENVIRONMENT', 'VIRTUAL_ENV',
                'OMNI_KIT_ACCEPT_EULA', 'ACCEPT_EULA', 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
        env.pop(key, None)
    env.pop('ISAACLAB_ARENA_FORCE_EXIT_ON_COMPLETE', None)
    env.update(GIT_TERMINAL_PROMPT='0', MPLBACKEND='agg', PIP_DISABLE_PIP_VERSION_CHECK='1')

    def save(*, checkpoint=False):
        report['elapsed_wall_s'] = round(time.monotonic()-started, 3)
        path = artifacts / 'report.json'; temporary = artifacts / 'report.tmp'
        temporary.write_text(json.dumps(report, indent=2)); temporary.replace(path)
        if checkpoint:
            checkpoint_artifacts(work, report)

    def phase(name, command, limit, *, cwd=None, allow_failure=False):
        nonlocal closing
        report['phase'] = name
        item = {'name': name, 'status': 'running'}; report['phases'].append(item); save()
        remaining = deadline-time.monotonic()-45
        if remaining <= 0: raise TimeoutError('bounded Colab deadline exhausted')
        output = artifacts / (name+'.json')
        with (logs/(name+'.log')).open('w') as stream, output.open('w') as stdout:
            process = subprocess.Popen(command, cwd=cwd or work, env=env, stdout=stdout,
                                       stderr=stream, start_new_session=True)
            try:
                code = process.wait(timeout=min(limit, remaining))
            except BaseException:
                closing = True
                item['group_cleanup'] = stop_owned_group(process)
                item.update(status='interrupted'); save(checkpoint=True); raise
        item.update(returncode=code, status='passed' if code == 0 else 'failed'); save(checkpoint=True)
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
        smoke = phase('smoke', [*cli,'smoke','--source',str(source),'--accept-eula'], 240)
        report['smoke_evidence'] = smoke_readback(json.loads(smoke.read_text()),
                                                (logs/'smoke.log').read_text())
        report['arena_smoke_completed'] = True; save(checkpoint=True)
        result = phase('evaluate', [*cli,'evaluate','--source',str(source),'--accept-eula',
                                   '--output',str(artifacts/'evaluation')], 360)
        receipt = json.loads(result.read_text())
        report['pipeline_completed'] = receipt.get('pipeline_completed') is True
        report['policy_success'] = receipt.get('policy_success')
        if not report['pipeline_completed']: raise RuntimeError('native two-Run evaluation incomplete')
        report['status'] = 'completed'
    except BaseException as error:
        report.update(status='failed', pipeline_completed=False,
                      error_type=type(error).__name__, error=str(error))
    finally:
        closing = True
        report['input_sha256_after'] = input_hashes(root)
        report['inputs_unchanged'] = (report['input_sha256_before'] == report['input_sha256_after']
                                      and all(report['input_sha256_after'].values()))
        if not report['inputs_unchanged']:
            report.update(status='failed', pipeline_completed=False, error_type='SourceChanged',
                          error='uploaded inputs changed during execution')
        report['report_final'] = True
        save(checkpoint=True)
        index = json.loads((work/'recovery-index.json').read_text())
        bundle = work/index['bundle']['name']
        print(json.dumps({'status':report['status'],'phase':report['phase'],
                          'pipeline_completed':report['pipeline_completed'],'bundle':str(bundle)}),flush=True)
        signal.signal(signal.SIGTERM, previous_sigterm)
    return 0 if report['status'] == 'completed' and report['pipeline_completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
