#!/usr/bin/env python3
"""One bounded L4 run through the existing private Colab CLI adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import time
import uuid
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[2]
INPUT_FILES = ('tools/fishbot_arena.py', 'experiments/arena/upstream.lock.json',
               'experiments/arena/evaluation.yaml', 'experiments/arena/colab_preflight.py',
               'experiments/arena/colab_bootstrap.py')
MAX_ARCHIVE_BYTES = 256 * 2**20
RECOVERY_SECONDS, CLEANUP_SECONDS, VERIFY_SECONDS = 180, 120, 60
WORK_RESERVE = RECOVERY_SECONDS + CLEANUP_SECONDS + VERIFY_SECONDS
BUNDLE_NAME = re.compile(r'artifacts(?:-[0-9a-f]{32})?\.zip')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    pending = path.with_suffix(path.suffix + '.partial')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    pending.replace(path)


def archive_members(archive):
    members = archive.infolist()
    names = [member.filename for member in members]
    if not 1 <= len(names) <= 4096 or len(set(names)) != len(names):
        raise ValueError('duplicate or excessive archive members')
    if sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES:
        raise ValueError('unpacked archive exceeds limit')
    for member in members:
        name = PurePosixPath(member.filename)
        mode = member.external_attr >> 16
        if (member.is_dir() or stat.S_ISLNK(mode) or name.is_absolute()
                or '..' in name.parts or '\\' in member.filename
                or name.as_posix() != member.filename
                or member.file_size > 64 * 2**20
                or name.suffix not in ('.json', '.jsonl', '.log', '.html', '.csv')):
            raise ValueError('unsafe or unexpected archive member')
    if 'report.json' not in names or archive.testzip() is not None:
        raise ValueError('missing report or failed archive CRC')
    return set(names)


def valid_identity(value):
    return (isinstance(value, dict) and type(value.get('size_bytes')) is int
            and 0 <= value['size_bytes'] <= MAX_ARCHIVE_BYTES
            and isinstance(value.get('sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', value['sha256']) is not None)


def recover(bundle, index, destination):
    """Read back the producer's exact archive; do not score policy outcomes."""
    identity = index.get('bundle', {}) if isinstance(index, dict) else {}
    if (not valid_identity(identity) or not isinstance(identity.get('name'), str)
            or BUNDLE_NAME.fullmatch(identity['name']) is None
            or bundle.stat().st_size != identity['size_bytes']
            or sha(bundle) != identity['sha256']):
        raise ValueError('archive identity differs from recovery index')
    with ZipFile(bundle) as archive:
        names = archive_members(archive)
        files = index.get('files')
        if not isinstance(files, dict) or set(files) != names:
            raise ValueError('manifest does not cover exact archive')
        for name, identity in files.items():
            if not valid_identity(identity):
                raise ValueError('invalid manifest identity')
            data = archive.read(name)
            if len(data) != identity['size_bytes'] or hashlib.sha256(data).hexdigest() != identity['sha256']:
                raise ValueError('artifact differs from manifest')
        report_data = archive.read('report.json')
        if hashlib.sha256(report_data).hexdigest() != index.get('report_sha256'):
            raise ValueError('report differs from recovery index')
        report = json.loads(report_data)
        if (not isinstance(report, dict) or report.get('report_final') is not True
                or index.get('report_final') is not True
                or report.get('status') not in ('completed', 'failed')
                or index.get('status') != report['status']):
            raise ValueError('recovery lacks matching final worker report')
        destination.mkdir(exist_ok=False)
        for name in names:
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(name))
    return report


class CommandFailed(RuntimeError):
    pass


def safe_result(value):
    """Retain the adapter's public receipt, never partial native output."""
    if not isinstance(value, dict):
        return {'exit_code': 1, 'error_type': 'InvalidSafeCLIResult'}
    result = {key: value[key] for key in ('exit_code', 'error_type', 'error_category',
              'unassign_completed', 'connection_verified', 'active_assignments') if key in value}
    failure = value.get('request_failure')
    if isinstance(failure, dict):
        result['request_failure'] = {key: failure[key] for key in
            ('host', 'method', 'phase', 'type', 'status_code', 'elapsed_s') if key in failure}
    return result


class ColabRun:
    def __init__(self, args, *, root=ROOT, clock=None, sleep=None):
        if not args.accept_eula:
            raise ValueError('explicit --accept-eula is required')
        if not 600 <= args.budget_seconds <= 2700:
            raise ValueError('budget must be 600..2700 seconds')
        self.root = root
        self.clock, self.sleep = clock or time.monotonic, sleep or time.sleep
        self.started = self.clock()
        self.deadline = self.started + args.budget_seconds
        self.work_deadline = self.deadline - WORK_RESERVE
        self.output = args.output.expanduser().absolute()
        if self.output.exists() or self.output.is_symlink():
            raise ValueError('output must be a new private directory')
        safe_cli = args.safe_cli or root.parent/'so101/experiments/gr00t-libero/colab_safe_cli.py'
        python = args.colab_python or Path.home()/'.local/share/uv/tools/google-colab-cli/bin/python'
        if not Path(safe_cli).is_file() or not Path(python).is_file():
            raise ValueError('existing safe adapter and Colab CLI Python are required')
        self.output.mkdir(parents=True, mode=0o700, exist_ok=False)
        self.output.chmod(0o700)
        state = self.output/'private-session'; state.mkdir(mode=0o700)
        config = state/'sessions.json'
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('{}\n')
        self.prefix = [str(python), str(safe_cli), '--config', str(config)]
        self.identifier = str(uuid.uuid4())
        self.session = 'fishbot-arena-' + self.identifier
        self.remote = '/content/fishbot-arena-' + self.identifier
        self.owned, self.process = False, None
        self.report = {'schema_version': 1, 'session': self.session,
            'budget_seconds': args.budget_seconds, 'recovery_reserve_seconds': RECOVERY_SECONDS,
            'cleanup_reserve_seconds': CLEANUP_SECONDS, 'verify_reserve_seconds': VERIFY_SECONDS,
            'human_eula_accepted': True, 'status': 'running', 'successful': False,
            'remote_execution_attempted': False,
            'pipeline_completed': False, 'policy_success': None,
            'artifact_recovery_verified': False, 'checkpoint_recovered': False, 'recovery_incomplete': True,
            'runtime_released': False, 'connection_zero_verified': False, 'calls': []}
        self.save()

    def save(self):
        self.report['elapsed_wall_s'] = round(self.clock() - self.started, 3)
        write(self.output/'lifecycle.json', self.report)

    def call(self, *command, limit=60, until=None):
        timeout = min(limit, (until or self.work_deadline) - self.clock())
        if timeout <= 0:
            raise TimeoutError('bounded Colab phase deadline exhausted')
        began = self.clock()
        try:
            process = subprocess.run([*self.prefix, *map(str, command)], capture_output=True,
                                     text=True, timeout=timeout)
            try:
                result = safe_result(json.loads(process.stdout))
            except ValueError:
                result = {'exit_code': 1, 'error_type': 'InvalidSafeCLIResult'}
            success = process.returncode == 0 and type(result.get('exit_code')) is int and result['exit_code'] == 0
        except subprocess.TimeoutExpired:
            result = {'exit_code': 1, 'error_type': 'TimeoutExpired'}
            success = False
        self.report['calls'].append({'command': command[0], 'elapsed_s': round(self.clock()-began, 3),
                                     'result': result})
        self.save()
        if not success:
            raise CommandFailed('Colab ' + str(command[0]) + ' failed')
        return result

    def download(self, remote, target, *, until, attempts=3):
        # Only identical GETs are retried. Allocation and execution are single-shot.
        pending = target.with_suffix(target.suffix + '.partial')
        for attempt in range(attempts):
            try:
                pending.unlink(missing_ok=True)
                self.call('download', '-s', self.session, remote, pending, limit=40, until=until)
                if not pending.is_file() or pending.is_symlink():
                    raise CommandFailed('download did not produce a regular file')
                pending.replace(target)
                return
            except (CommandFailed, TimeoutError):
                if attempt + 1 == attempts or until - self.clock() <= 5:
                    raise
                self.sleep(min(2, max(0, until-self.clock())))

    def runtime_ready(self):
        for attempt in range(1, 4):
            try:
                self.call('ls', '-s', self.session, '/content', limit=40)
                self.report.update(runtime_contents_ready=True, readiness_attempts=attempt)
                self.save()
                return
            except (CommandFailed, TimeoutError):
                if attempt == 3 or self.work_deadline-self.clock() <= 5:
                    raise
                self.sleep(min(2, max(0, self.work_deadline-self.clock())))

    def upload_source(self, bundle, remote):
        identity = {'size_bytes': bundle.stat().st_size, 'sha256': sha(bundle)}
        self.report['upload_identity'] = identity
        for attempt in range(1, 4):
            self.report['upload_attempts'] = attempt
            self.save()
            if bundle.stat().st_size != identity['size_bytes'] or sha(bundle) != identity['sha256']:
                raise ValueError('source bundle changed; upload was not repeated')
            try:
                self.call('upload', '-s', self.session, bundle, remote, limit=120)
                self.report.update(upload_delivery='acknowledged', upload_attempts=attempt)
                self.save()
                return
            except CommandFailed:
                result = self.report['calls'][-1]['result']
                failure = result.get('request_failure') or {}
                if (result.get('error_category') != 'timeout'
                        and result.get('error_type') != 'TimeoutExpired'
                        and failure.get('type') not in ('ConnectTimeout', 'ReadTimeout')):
                    raise
            # PUT may have completed despite a lost acknowledgement. Read the
            # exact remote object before permitting another identical write.
            readback = self.output/f'upload-readback-{attempt}.zip'
            try:
                self.call('download', '-s', self.session, remote, readback, limit=40)
            except CommandFailed:
                failure = self.report['calls'][-1]['result'].get('request_failure') or {}
                if type(failure.get('status_code')) is not int or failure['status_code'] != 404:
                    raise CommandFailed('source upload remains unknown; execution was not started')
                if attempt == 3:
                    raise CommandFailed('source remains absent after three upload attempts')
                if self.work_deadline-self.clock() <= 5:
                    raise TimeoutError('no budget for confirmed-absent source upload')
                self.sleep(min(2, max(0, self.work_deadline-self.clock())))
                continue
            if (not readback.is_file() or readback.is_symlink()
                    or readback.stat().st_size != identity['size_bytes'] or sha(readback) != identity['sha256']):
                raise ValueError('source upload readback differs; execution was not started')
            self.report.update(upload_delivery='verified_after_timeout', upload_attempts=attempt,
                               upload_readback_sha256=sha(readback))
            self.save()
            return

    def launch(self):
        hashes = {name: sha(self.root/name) for name in INPUT_FILES}
        self.report['source_sha256'] = hashes
        bundle = self.output/'public-source.zip'
        with ZipFile(bundle, 'w') as archive:
            for name in INPUT_FILES:
                archive.write(self.root/name, name)
        self.save()
        self.owned = True  # The wrapper persists exact intent before its allocation POST.
        self.report['allocation_attempted'] = True; self.save()
        self.call('new', '-s', self.session, '--gpu', 'L4', limit=180)
        self.runtime_ready()
        self.upload_source(bundle, self.remote+'-source.zip')
        remaining = int(self.work_deadline-self.clock())
        if remaining < 120:
            raise TimeoutError('insufficient work budget; remote execution was not started')
        launch = self.output/'launch.py'
        launch.write_text(
            'import hashlib,subprocess,sys\nfrom pathlib import Path\nfrom zipfile import ZipFile\n'
            f'source=Path({self.remote!r})/"source";source.mkdir(parents=True,exist_ok=False)\n'
            f'expected={hashes!r}\n'
            f'with ZipFile({(self.remote+"-source.zip")!r}) as z:\n'
            ' assert len(z.namelist())==len(expected) and set(z.namelist())==set(expected)\n'
            ' for name,digest in expected.items():\n'
            '  data=z.read(name);assert hashlib.sha256(data).hexdigest()==digest\n'
            '  path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)\n'
            'subprocess.run([sys.executable,str(source/"experiments/arena/colab_bootstrap.py"),'
            f'"--work",{(self.remote+"/work")!r},"--timeout",{str(remaining)!r},"--accept-eula"],check=True)\n')
        self.process = subprocess.Popen([*self.prefix, 'exec', '-s', self.session, '-f', str(launch),
                                         '--timeout', str(remaining+30)],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.report['remote_execution_attempted'] = True; self.save()

    def poll(self):
        while self.clock() < self.work_deadline:
            try:
                self.download(self.remote+'/work/artifacts/report.json', self.output/'live.json',
                              until=self.work_deadline, attempts=1)
                remote = json.loads((self.output/'live.json').read_text())
                if not isinstance(remote, dict):
                    raise ValueError('invalid remote report')
                self.report['remote'] = remote; self.save()
                if remote.get('report_final') is True and remote.get('status') in ('completed', 'failed'):
                    return  # The local exec connection may still be pending.
            except (CommandFailed, ValueError, OSError):
                self.report['poll_failures'] = self.report.get('poll_failures', 0)+1; self.save()
                if self.process is not None and self.process.poll() is not None:
                    raise RuntimeError('exec ended without a readable final report')
            self.sleep(min(10, max(0, self.work_deadline-self.clock())))
        raise TimeoutError('work deadline reached; evidence recovery begins')

    def retrieve(self):
        until = min(self.clock()+RECOVERY_SECONDS, self.deadline-CLEANUP_SECONDS-VERIFY_SECONDS)
        attempts = self.output/'recovery-attempts'; attempts.mkdir()
        index_available = False
        checkpoints = []
        # Read the pointer and its immutable generation as a pair. A successful
        # GET can still contain an older checkpoint; only read operations retry.
        for number in range(1, 4):
            attempt = attempts/f'attempt-{number:02d}'; attempt.mkdir()
            index_path, bundle = attempt/'recovery-index.json', attempt/'artifacts.zip'
            try:
                self.download(self.remote+'/work/recovery-index.json', index_path,
                              until=until, attempts=1)
                index_available = True
                index = json.loads(index_path.read_text())
                identity = index.get('bundle', {}) if isinstance(index, dict) else {}
                name = identity.get('name')
                if not isinstance(name, str) or BUNDLE_NAME.fullmatch(name) is None:
                    raise ValueError('unsafe recovery bundle name')
                if not valid_identity(identity):
                    raise ValueError('invalid recovery bundle identity')
                self.download(self.remote+'/work/'+name, bundle, until=until, attempts=1)
                checkpoints.append(bundle)
                remote = recover(bundle, index, attempt/'recovered')
                index_path.replace(self.output/'recovery-index.json')
                bundle.replace(self.output/'artifacts.zip')
                (attempt/'recovered').replace(self.output/'recovered')
                self.report.update(remote=remote, artifact_recovery_verified=True, recovery_incomplete=False,
                    artifact_sha256=sha(self.output/'artifacts.zip'), recovered_generation=name,
                    recovery_attempts=number, pipeline_completed=remote.get('pipeline_completed') is True,
                    policy_success=remote.get('policy_success'))
                self.report.pop('recovery_error_type', None)
                break
            except (CommandFailed, TimeoutError, ValueError, OSError, BadZipFile) as error:
                self.report.setdefault('recovery_errors', []).append(
                    {'attempt': number, 'error_type': type(error).__name__})
                self.report['recovery_error_type'] = type(error).__name__
                self.save()
                if number == 3 or until-self.clock() <= 5:
                    break
                self.sleep(min(2, max(0, until-self.clock())))
        if not self.report['artifact_recovery_verified']:
            if not index_available:
                # The compatibility alias is only a fallback when no pointer was
                # retrieved. It never supplies final-generation verification.
                fallback = self.output/'artifacts.zip'
                try:
                    self.download(self.remote+'/work/artifacts.zip', fallback, until=until)
                    checkpoints.append(fallback)
                except (CommandFailed, TimeoutError) as error:
                    self.report.setdefault('recovery_errors', []).append(
                        {'file': 'artifacts.zip', 'error_type': type(error).__name__})
            for checkpoint in reversed(checkpoints):
                try:
                    with ZipFile(checkpoint) as archive:
                        archive_members(archive)
                    self.report.update(checkpoint_recovered=True, checkpoint_sha256=sha(checkpoint),
                        checkpoint_path=str(checkpoint.relative_to(self.output)), recovery_incomplete=True)
                    break
                except (ValueError, OSError, BadZipFile):
                    continue
        try:
            self.download(self.remote+'/work/artifacts/report.json', self.output/'live.json',
                          until=until, attempts=1)
        except (CommandFailed, TimeoutError) as error:
            self.report.setdefault('recovery_errors', []).append(
                {'file': 'live.json', 'error_type': type(error).__name__})
        self.save()

    def close_client(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
            self.report['local_exec_client_stopped'] = True
            # This is not a receipt that the remote worker or VM stopped.

    def run(self):
        previous = signal.getsignal(signal.SIGTERM)
        def terminate(signum, frame):
            raise KeyboardInterrupt('bounded job termination')
        signal.signal(signal.SIGTERM, terminate)
        try:
            connection = self.call('check-connection', limit=60)
            self.report['connection_before'] = connection
            if (connection.get('connection_verified') is not True
                    or type(connection.get('active_assignments')) is not int
                    or connection['active_assignments'] != 0):
                raise RuntimeError('account must have verified zero assignments before allocation')
            self.launch()
            self.poll()
        except BaseException as error:
            self.report.update(status='failed', error_type=type(error).__name__)
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:
                if self.owned:
                    if self.report['remote_execution_attempted'] is True:
                        try:
                            self.retrieve()
                        except BaseException as error:
                            self.report['recovery_error_type'] = type(error).__name__
                    else:
                        self.report.update(recovery_status='not_applicable', recovery_incomplete=False)
                    try:
                        self.close_client()
                    except BaseException as error:
                        self.report['local_client_error_type'] = type(error).__name__
                    try:
                        stopped = self.call('stop', '-s', self.session, limit=CLEANUP_SECONDS,
                            until=min(self.clock()+CLEANUP_SECONDS, self.deadline-VERIFY_SECONDS))
                        self.report['stop_receipt'] = stopped
                        self.report['runtime_released'] = stopped.get('unassign_completed') is True
                    except BaseException as error:
                        self.report['cleanup_error_type'] = type(error).__name__
                try:
                    connection = self.call('check-connection', limit=VERIFY_SECONDS, until=self.deadline)
                    self.report['connection_after'] = connection
                    self.report['connection_zero_verified'] = (connection.get('connection_verified') is True
                        and type(connection.get('active_assignments')) is int and connection['active_assignments'] == 0)
                except BaseException as error:
                    self.report['connection_after_error_type'] = type(error).__name__
                hashes = self.report.get('source_sha256', {})
                try:
                    self.report['source_unchanged'] = bool(hashes) and all(sha(self.root/name) == digest for name, digest in hashes.items())
                except OSError:
                    self.report['source_unchanged'] = False
                remote = self.report.get('remote', {})
                self.report['uploaded_inputs_verified'] = (bool(hashes)
                    and remote.get('input_sha256_before') == hashes
                    and remote.get('input_sha256_after') == hashes)
                self.report['successful'] = (self.report['artifact_recovery_verified']
                    and remote.get('status') == 'completed' and remote.get('report_final') is True
                    and remote.get('arena_smoke_completed') is True and remote.get('pipeline_completed') is True
                    and remote.get('inputs_unchanged') is True and self.report['source_unchanged']
                    and self.report['uploaded_inputs_verified']
                    and self.report['runtime_released'] and self.report['connection_zero_verified'])
                self.report['diagnostic_closure_verified'] = ((self.report['artifact_recovery_verified']
                    or (self.report['remote_execution_attempted'] is False
                        and self.report.get('recovery_status') == 'not_applicable'))
                    and self.report['runtime_released'] and self.report['connection_zero_verified'])
                self.report['status'] = 'completed' if self.report['successful'] else 'failed'
                self.save()
            finally:
                signal.signal(signal.SIGTERM, previous)
        return 0 if self.report['successful'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget-seconds', type=int, default=2700)
    parser.add_argument('--accept-eula', action='store_true')
    parser.add_argument('--safe-cli', type=Path)
    parser.add_argument('--colab-python', type=Path)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        job = ColabRun(args)
    except ValueError as error:
        parser.error(str(error))
    code = job.run()
    print(json.dumps({key: job.report[key] for key in ('status', 'successful',
        'artifact_recovery_verified', 'runtime_released', 'connection_zero_verified')}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
