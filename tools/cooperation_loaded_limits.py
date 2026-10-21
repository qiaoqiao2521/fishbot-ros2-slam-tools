"""Task-scoped native velocity_smoother and RPP parameter services.

This adapter changes max_accel/max_decel and optional paired velocity bounds.
The caller retains motion ownership, hold, time budgets, cancellation and
cleanup. Each RPC is sent once.
"""
from __future__ import annotations

import copy
import math
import time
import warnings


NAMES = ('max_accel', 'max_decel')
VELOCITY_NAMES = ('max_velocity', 'min_velocity')
RPP_NAMES = ('FollowPath.desired_linear_vel',
             'FollowPath.regulated_linear_scaling_min_speed',
             'FollowPath.min_approach_linear_velocity',
             'FollowPath.rotate_to_heading_angular_vel')
PROGRESS_NAMES = ('progress_checker.required_movement_radius',
                  'progress_checker.required_movement_angle')
CONTROLLER_NAMES = RPP_NAMES + PROGRESS_NAMES


def limits(value):
    if not isinstance(value, dict) or not set(NAMES).issubset(value):
        raise ValueError('载货平滑参数必须包含 max_accel 和 max_decel')
    velocity_fields = set(value).intersection(VELOCITY_NAMES)
    if velocity_fields and velocity_fields != set(VELOCITY_NAMES):
        raise ValueError('max_velocity 和 min_velocity 必须成对声明')
    names = NAMES + (VELOCITY_NAMES if velocity_fields else ())
    extra = set(value)-set(names)
    if extra:
        warnings.warn(f'Ignoring loaded velocity metadata fields: {sorted(map(str, extra))}',
                      RuntimeWarning, stacklevel=2)
    result = {}
    for name in names:
        vector = value[name]
        if (not isinstance(vector, (list, tuple)) or len(vector) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in vector)):
            raise ValueError(f'{name} 必须是三个有限数值')
        if any(v < 0 if name in ('max_accel', 'max_velocity') else v > 0 for v in vector):
            raise ValueError(f'{name} 符号无效')
        result[name] = [float(v) for v in vector]
    if velocity_fields and any(low > high for low, high in zip(result['min_velocity'], result['max_velocity'])):
        raise ValueError('min_velocity 必须逐轴小于或等于 max_velocity')
    return result


def rpp_limits(value):
    if not isinstance(value, dict) or not any(name in value for name in CONTROLLER_NAMES):
        raise ValueError('载货控制器参数必须包含至少一个受支持的速度或进度参数')
    extra = set(value)-set(CONTROLLER_NAMES)
    if extra:
        warnings.warn(f'Ignoring loaded RPP metadata fields: {sorted(map(str, extra))}',
                      RuntimeWarning, stacklevel=2)
    result = {}
    for name in CONTROLLER_NAMES:
        if name not in value:
            continue
        scalar = value[name]
        if (isinstance(scalar, bool) or not isinstance(scalar, (int, float))
                or not math.isfinite(scalar) or scalar <= 0):
            raise ValueError(f'{name} 必须是正的有限 DOUBLE 数值')
        result[name] = float(scalar)
    return result


class LoadedVelocityLimits:
    node_name = '/velocity_smoother'
    parameter_kind = 8  # rcl_interfaces/ParameterType.PARAMETER_DOUBLE_ARRAY
    parameter_kind_name = 'DOUBLE_ARRAY'
    normalize = staticmethod(limits)
    evidence_scope = 'native_parameter_ACK_and_readback_not_physical_acceleration_measurement'

    def __init__(self, desired, parameter_client, lifecycle_query, parameter_factory):
        self.desired = self.normalize(desired)
        self.names = tuple(self.desired)
        self.client = parameter_client
        self.lifecycle_query = lifecycle_query
        self.parameter_factory = parameter_factory
        self.baseline = None
        self.actual = None
        self.dirty = False
        self.phase = 'not_applied'
        self.error = None
        self.requests = {}

    def new_task(self):
        return type(self)(self.desired, self.client, self.lifecycle_query, self.parameter_factory)

    def snapshot(self):
        requests = {key: {name: value for name, value in record.items() if name != 'future'}
                    for key, record in list(self.requests.items())}
        return copy.deepcopy({'node': self.node_name, 'phase': self.phase,
            'desired': self.desired, 'baseline': self.baseline, 'actual': self.actual,
            'restoration_required': self.dirty, 'error': self.error, 'requests': requests,
            'scope': self.evidence_scope})

    def _rpc(self, name, create, wait):
        record = self.requests.get(name)
        if record is None:
            record = {'state': 'creating', 'created_monotonic': time.monotonic()}
            self.requests[name] = record
            try:
                record['future'] = create()
                record['state'] = 'pending'
            except Exception as error:
                record.update(state='unknown', error=str(error))
                raise RuntimeError(f'载货参数 {name} 请求结果未知，不自动重发：{error}') from error
        if 'future' not in record:
            raise RuntimeError(f'载货参数 {name} 请求结果未知，不自动重发')
        try:
            wait(record['future'])
            response = record['future'].result()
        except Exception as error:
            record.update(state='unknown', error=str(error))
            raise
        record['state'] = 'received'
        record.setdefault('received_monotonic', time.monotonic())
        return response

    def _active(self, name, wait):
        response = self._rpc(name, self.lifecycle_query, wait)
        if response.current_state.id != 3:
            raise RuntimeError(f'{self.node_name} 尚未 active，未确认载货参数生效')

    def decode(self, value):
        return list(value.double_array_value)

    def encode(self, value):
        return list(value)

    def _read(self, name, wait):
        response = self._rpc(name, lambda: self.client.get_parameters(list(self.names)), wait)
        if (len(response.values) != len(self.names)
                or any(value.type != self.parameter_kind for value in response.values)):
            raise RuntimeError(f'{self.node_name} 未返回声明的 {self.parameter_kind_name} 参数')
        return self.normalize({key: self.decode(value) for key, value in zip(self.names, response.values)})

    def _write(self, name, values, wait):
        response = self._rpc(name, lambda: self.client.set_parameters_atomically([
            self.parameter_factory(key, self.encode(values[key])) for key in self.names]), wait)
        if type(response.result.successful) is not bool:
            raise RuntimeError(f'载货参数 {name} 未返回明确服务结果')
        return response.result

    def apply(self, wait):
        if self.phase == 'applied':
            return self.snapshot()
        try:
            self.phase = 'checking'
            self._active('active_apply', wait)
            self.baseline = self._read('baseline', wait)
            # Native callbacks can mutate an earlier field even if a later
            # field is rejected. Restore after any acknowledged write attempt.
            self.dirty = True
            self.phase = 'applying'
            result = self._write('apply', self.desired, wait)
            if not result.successful:
                raise RuntimeError(f'载货参数被拒绝：{result.reason}')
            self.actual = self._read('readback_apply', wait)
            if self.actual != self.desired:
                raise RuntimeError('载货参数回读与请求不一致')
            self.phase = 'applied'
            return self.snapshot()
        except Exception as error:
            self.phase, self.error = 'apply_unconfirmed', str(error)
            raise

    def restore(self, wait):
        if not self.dirty:
            return self.snapshot()
        try:
            self.phase = 'restoring'
            # Reconcile the original write before restoring. A timed-out RPC
            # may still arrive; local Future cancellation cannot undo it.
            self._write('apply', self.desired, wait)
            self._active('active_restore', wait)
            result = self._write('restore', self.baseline, wait)
            if not result.successful:
                raise RuntimeError(f'原参数恢复被拒绝：{result.reason}')
            self.actual = self._read('readback_restore', wait)
            if self.actual != self.baseline:
                raise RuntimeError('原参数恢复回读不一致')
            self.dirty, self.phase, self.error = False, 'restored', None
            return self.snapshot()
        except Exception as error:
            self.phase, self.error = 'restore_unconfirmed', str(error)
            raise


class LoadedRppLimits(LoadedVelocityLimits):
    """Only the declared native RPP scalar speed parameters, under the same RPC lifecycle."""
    node_name = '/controller_server'
    parameter_kind = 3  # rcl_interfaces/ParameterType.PARAMETER_DOUBLE
    parameter_kind_name = 'DOUBLE'
    normalize = staticmethod(rpp_limits)
    evidence_scope = 'native_parameter_ACK_and_readback_not_controller_command_or_physical_measurement'

    def decode(self, value):
        return value.double_value

    def encode(self, value):
        return float(value)
