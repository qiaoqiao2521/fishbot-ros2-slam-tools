"""Process identity and execution admission; this module never starts ROS tasks."""
import copy
import fcntl
import json
import os
from pathlib import Path
import stat
import uuid


INSTANCE_HEADER = 'X-Fishbot-Instance'
RUNTIME_CHANGED = {'error': 'runtime_changed', 'outcome': 'rejected'}


class ExecutionOwnerBusy(RuntimeError):
    pass


class DomainExecutionLock:
    """One participating execution process per local UID/domain, using flock.

    The namespace is independent of ports, working directories and task outputs.
    Existing unmodified processes and external ROS publishers do not use this lock.
    """
    def __init__(self, domain, owner, *, directory=None):
        if type(domain) is not int or not 1 <= domain <= 232:
            raise ValueError('Execution domain must be 1..232')
        if owner not in {'mission', 'cooperation'}:
            raise ValueError('Only native execution owners acquire a domain lock')
        self.domain, self.owner, self.stream = domain, owner, None
        # directory is an isolated fixture hook; launchers always use this default.
        self.directory = Path(directory) if directory is not None else Path('/tmp') / f'fishbot-execution-{os.getuid()}'

    def __enter__(self):
        if self.stream is not None:
            raise RuntimeError('Execution lock is already held by this handle')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError('Execution lock directory must be a private directory owned by this user')
        filename = self.directory / f'domain-{self.domain}.lock'
        descriptor = os.open(filename, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError('Execution lock must be a regular file owned by this user')
            self.stream = os.fdopen(descriptor, 'r+')
            descriptor = None
            try:
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ExecutionOwnerBusy(f'ROS domain {self.domain} already has an execution owner; '
                                         f'{self.owner} startup refused, existing owner unchanged') from None
            self.stream.seek(0)
            self.stream.truncate()
            json.dump({'domain': self.domain, 'owner': self.owner, 'pid': os.getpid()}, self.stream)
            self.stream.flush()
            return self
        except BaseException:
            self.close()
            if descriptor is not None:
                os.close(descriptor)
            raise

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def __exit__(self, *unused):
        self.close()  # Never unlink: competing open descriptors must share one inode.


def capability(identifier, submission, *, cancel=False, event_history='none'):
    """Default metadata; each owner declares any implemented task lookup."""
    return {'id': identifier, 'submission': submission, 'task_lookup': False,
            'cancel': cancel, 'event_history': event_history}


class RuntimeIdentity:
    """One UUID per server lifetime, independent of task and scene identities."""
    def __init__(self, service, mode, domain, capabilities, *, scene_id=None):
        if service not in {'mission', 'cooperation', 'voice', 'station'}:
            raise ValueError('Unknown runtime service')
        if mode not in {'simulation', 'offline', 'live', 'unknown'}:
            raise ValueError('Unknown runtime mode')
        if domain is not None and (type(domain) is not int or not 0 <= domain <= 232):
            raise ValueError('Runtime domain must be known or null')
        self.instance_id = str(uuid.uuid4())
        self._value = {'schema_version': 1, 'service': service, 'instance_id': self.instance_id,
                       'mode': mode, 'domain': domain, 'scene_id': scene_id,
                       'episode_id': None, 'capabilities': copy.deepcopy(capabilities)}

    def snapshot(self, *, episode_id=None):
        value = copy.deepcopy(self._value)
        value['episode_id'] = episode_id
        return value

    def accepts(self, headers):
        """Optional restart fence. Missing headers preserve legacy requests."""
        if hasattr(headers, 'get_all'):
            values = headers.get_all(INSTANCE_HEADER, [])
        else:
            value = headers.get(INSTANCE_HEADER)
            values = [] if value is None else [value]
        return not values or values == [self.instance_id]
