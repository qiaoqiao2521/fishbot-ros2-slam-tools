"""Process identity and discovery only; this module never starts a task or ROS."""
import copy
import uuid


INSTANCE_HEADER = 'X-Fishbot-Instance'
RUNTIME_CHANGED = {'error': 'runtime_changed', 'outcome': 'rejected'}


def capability(identifier, submission, *, cancel=False, event_history='none'):
    """Current adapters cannot retrieve an arbitrary task by its UUID."""
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
