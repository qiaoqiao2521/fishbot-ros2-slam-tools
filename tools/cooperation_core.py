"""Small admission and physical-evidence helpers for the fixed-workcell demo."""
import math
import time
import uuid


ACTIVE = {'running', 'canceling', 'unknown'}


def within_station_capture(pose, dock):
    """Select native relative docking only inside its east-side approach tube."""
    x, y, yaw = finite_vector([pose[key] for key in ('x', 'y', 'yaw')], 3, '工位车体观测')
    dx, dy, heading = finite_vector(dock, 3, '工位停车位')
    c, s = math.cos(heading), math.sin(heading)
    along = (x-dx)*c+(y-dy)*s
    lateral = -(x-dx)*s+(y-dy)*c
    angle = math.atan2(math.sin(yaw-heading), math.cos(yaw-heading))
    return .2 <= along <= .9 and abs(lateral) <= .06 and abs(angle) <= .15


def finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label}须为有限数值')
    return value


def finite_vector(value, length, label):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f'{label}数组长度应为{length}')
    return [finite_number(item, label) for item in value]


def quaternion(value, label):
    values = finite_vector(value, 4, label)
    if abs(sum(item*item for item in values)-1.) > .002:
        raise ValueError(f'{label}不是单位四元数')
    return values


def validate_physics(raw, scene_sha, manifest_sha=None, expected_layout=(22, 20, 8)):
    """Admit only complete finite measurements from this compiled scene."""
    if not isinstance(raw, dict) or raw.get('schema') != 1 or raw.get('finite') is not True:
        raise ValueError('共享物理反馈schema或finite标志无效')
    source = raw.get('source')
    if not isinstance(source, dict) or source.get('scene_sha256') != scene_sha:
        raise ValueError('共享物理反馈场景SHA与当前manifest不匹配')
    if manifest_sha is not None and source.get('manifest_sha256') != manifest_sha:
        raise ValueError('共享物理反馈manifest SHA不匹配')
    if 'episode_id' in raw:
        try:
            if str(uuid.UUID(raw['episode_id'])) != raw['episode_id'] or source.get('episode_id') != raw['episode_id']:
                raise ValueError('共享物理反馈回合身份不一致')
        except (ValueError, TypeError, AttributeError):
            raise ValueError('共享物理反馈回合身份无效')
    for key in ('stamp', 'wall_time'):
        if finite_number(raw[key], key) < 0:
            raise ValueError(f'{key}不可为负数')
    nq, nv, nu = expected_layout
    finite_vector(raw['ctrl'], nu, 'ctrl')
    if abs(finite_number(raw['time_s'], 'time_s')-raw['stamp']) > 1e-9:
        raise ValueError('规划快照时间与物理反馈不一致')
    for key in ('sequence', 'physics_steps'):
        if type(raw[key]) is not int or raw[key] < 0:
            raise ValueError(f'{key}须为非负整数')
    if raw['physics_hz'] != 500:
        raise ValueError('共享场景物理频率不匹配')
    arrays = {key: finite_vector(raw[key], length, key) for key, length in
              (('q6', 6), ('qvel6', 6), ('qpos22', nq), ('qvel20', nv), ('arm_reference_q6', 6))}
    if arrays['q6'] != arrays['qpos22'][:6] or arrays['qvel6'] != arrays['qvel20'][:6]:
        raise ValueError('机械臂状态与完整物理状态不一致')
    for key in ('car_hold', 'cargo_tray_floor_contact'):
        if type(raw[key]) is not bool:
            raise ValueError(f'{key}须为布尔值')
    for body_name in ('car', 'cargo', 'tray'):
        body = raw[body_name]
        if not isinstance(body, dict):
            raise ValueError(f'{body_name}位姿无效')
        finite_vector(body['position'], 3, f'{body_name}.position')
        quaternion(body['quaternion_wxyz'], f'{body_name}.quaternion')
        finite_vector(body['velocity_world_angular_linear'], 6, f'{body_name}.velocity')
    if (any(abs(a-b)>1e-9 for a,b in zip(arrays['qpos22'][6:9], raw['cargo']['position']))
            or any(abs(a-b)>1e-9 for a,b in zip(arrays['qpos22'][13:16], raw['car']['position']))):
        raise ValueError('自由货物或车体位姿与qpos22不一致')
    quaternion(arrays['qpos22'][9:13], 'qpos22.cargo')
    quaternion(arrays['qpos22'][16:20], 'qpos22.car')
    if finite_number(raw['car']['speed'], 'car.speed') < 0:
        raise ValueError('车速不可为负数')
    finite_number(raw['car']['yaw_rate'], 'car.yaw_rate')
    if type(raw['car']['hold']) is not bool or raw['car']['hold'] != raw['car_hold']:
        raise ValueError('车体锁定反馈不一致')
    for key in ('position_relative_tray', 'velocity_relative_tray'):
        finite_vector(raw['cargo'][key], 3, f'cargo.{key}')
    finite_vector(raw['tray']['floor_top_world'], 3, 'tray.floor_top_world')
    rotation = raw['tray']['rotation_world']
    if not isinstance(rotation, list) or len(rotation) != 3:
        raise ValueError('托盘旋转矩阵格式无效')
    rotation = [finite_vector(row, 3, 'tray.rotation_world') for row in rotation]
    if any(abs(sum(rotation[k][i]*rotation[k][j] for k in range(3))-(1. if i == j else 0.)) > .002
           for i in range(3) for j in range(3)):
        raise ValueError('托盘旋转矩阵不是正交矩阵')
    determinant = sum(rotation[0][i]*(rotation[1][(i+1)%3]*rotation[2][(i+2)%3]
                      -rotation[1][(i+2)%3]*rotation[2][(i+1)%3]) for i in range(3))
    if abs(determinant-1.) > .002:
        raise ValueError('托盘旋转矩阵方向无效')
    for key in ('finger_normal_forces_n', 'finger_peak_normal_forces_n'):
        forces = raw[key]
        if not isinstance(forces, dict) or set(forces) != {'pad_gripper', 'pad_moving_jaw'}:
            raise ValueError('夹指接触反馈不完整')
        if any(finite_number(value, key) < 0 for value in forces.values()):
            raise ValueError('夹指接触力不可为负数')
    if finite_number(raw['cargo_tray_floor_normal_force_n'], 'cargo_tray_floor_normal_force_n') < 0:
        raise ValueError('托盘支撑力不可为负数')
    if type(raw['cargo_tray_floor_contacts']) is not int or raw['cargo_tray_floor_contacts'] < 0:
        raise ValueError('托盘接触数量无效')
    if raw['cargo_tray_floor_contact'] != (raw['cargo_tray_floor_contacts'] > 0):
        raise ValueError('托盘接触标志与数量不一致')
    for body in ('arm', 'car'):
        contacts = raw[f'{body}_forbidden_contacts']
        if not isinstance(contacts, list):
            raise ValueError('非预期接触反馈格式无效')
        for contact in contacts:
            if not isinstance(contact, dict) or not all(isinstance(contact[key], str) for key in ('geom1', 'geom2')):
                raise ValueError('非预期接触几何名称无效')
            if finite_number(contact['normal_force_n'], 'contact.force') < 0:
                raise ValueError('非预期接触力无效')
            finite_number(contact['distance_m'], 'contact.distance')
        for suffix in ('count', 'total', 'steps'):
            count = raw[f'{body}_forbidden_contact_{suffix}'] if suffix != 'steps' else raw[f'{body}_forbidden_contact_steps']
            if type(count) is not int or count < 0:
                raise ValueError('非预期接触计数无效')
        # The current forward-refreshed contacts may first appear between
        # integrated steps; totals count only steps, independently of this list.
        if raw[f'{body}_forbidden_contact_count'] != len(contacts):
            raise ValueError('非预期接触列表与数量不一致')
    return raw


def physical_quiet(raw):
    return stopped(raw) and max(abs(value) for value in raw['qvel6']) < .05


def dispatch_terminal(dispatch):
    """A completed RPC is not itself proof that this exact goal is terminal."""
    if not dispatch.get('received') or dispatch.get('error') is not None:
        return False
    handle = dispatch.get('handle')
    if handle is None or not handle.accepted:
        return True
    future = dispatch.get('result')
    if future is None or not future.done():
        return False
    try:
        return future.result().status in (4, 5, 6)
    except Exception:
        return False


class Rejected(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def request_identity(body, *, cancel=False, now=None, episode_id=None):
    expected = {'task_id', 'issued_at'}
    if episode_id is not None:
        expected.add('episode_id')
    if not cancel and isinstance(body, dict) and 'scope' in body:
        expected.add('scope')
        task_scope(body)
    if not cancel and isinstance(body, dict) and 'delivery_pose' in body:
        expected.add('delivery_pose')
        task_delivery_pose(body)
    if not cancel and isinstance(body, dict) and 'delivery_approach_poses' in body:
        expected.add('delivery_approach_poses')
        task_delivery_approaches(body)
    if not cancel and isinstance(body, dict) and 'business_delivery' in body:
        expected.add('business_delivery')
        if task_scope(body) != 'transport':
            raise Rejected('实体配送仅支持完整 transport 任务')
        task_business_delivery(body)
    if not isinstance(body, dict) or set(body) != expected:
        raise Rejected('请求须包含 task_id 和 issued_at')
    if episode_id is not None and body['episode_id'] != episode_id:
        raise Rejected('场景回合已变化，请读取最新状态后重新开始', 409)
    try:
        task_id = str(uuid.UUID(body['task_id']))
    except (ValueError, TypeError, AttributeError):
        raise Rejected('任务编号无效')
    issued = body['issued_at']
    if isinstance(issued, bool) or not isinstance(issued, (int, float)) or not math.isfinite(issued):
        raise Rejected('请求时间无效')
    now = time.time() if now is None else now
    if not -2 <= now-issued <= 5:
        raise Rejected('请求已过期，请确认当前状态后重新操作', 409)
    return task_id


def task_scope(body):
    """The legacy start request remains a complete transport task."""
    value = body.get('scope', 'transport') if isinstance(body, dict) else None
    if value not in ('dock', 'transport', 'route'):
        raise Rejected('任务范围须为 dock、transport 或已恢复分支的 route')
    return value


def task_business_delivery(body):
    if 'business_delivery' not in body:
        return None
    from cooperation_business import normalize_delivery
    try:
        return normalize_delivery(body['business_delivery'])
    except ValueError as error:
        raise Rejected(str(error), getattr(error,'status',400)) from error


def task_delivery_pose(body, default=None):
    """Freeze a finite per-task destination without rewriting its yaw identity."""
    if isinstance(body, dict) and 'delivery_pose' in body:
        value = body['delivery_pose']
    else:
        value = default if default is not None else {'x': 0., 'y': -2., 'yaw': 0.}
        if isinstance(value, (list, tuple)) and len(value) == 3:
            value = dict(zip(('x', 'y', 'yaw'), value))
    if not isinstance(value, dict) or set(value) != {'x', 'y', 'yaw'}:
        raise Rejected('交付点须包含 x、y、yaw 三个有限数值')
    try:
        return {key: float(finite_number(value[key], f'交付点{key}')) for key in ('x', 'y', 'yaw')}
    except ValueError as error:
        raise Rejected(str(error)) from error


def task_delivery_approaches(body):
    """Optional ordered map poses before the unchanged final delivery pose."""
    values = body.get('delivery_approach_poses', [])
    if not isinstance(values, list):
        raise Rejected('配送站进场姿态须为有序列表，每项包含 x、y、yaw')
    result = []
    for index, value in enumerate(values):
        try:
            result.append(task_delivery_pose({'delivery_pose': value}))
        except Rejected as error:
            raise Rejected(f'配送站进场点{index+1}：{error}') from error
    return result


def reset_request_identity(body, now=None):
    if not isinstance(body, dict) or set(body) != {'request_id', 'episode_id', 'issued_at'}:
        raise Rejected('重置请求须包含 request_id、episode_id 和 issued_at')
    try:
        episode = str(uuid.UUID(body['episode_id']))
    except (ValueError, TypeError, AttributeError):
        raise Rejected('场景回合编号无效')
    request = request_identity({'task_id': body['request_id'], 'issued_at': body['issued_at']}, now=now)
    return request, episode


def station_robot_pose(relative, station):
    """Localize from a known station and its measured base-frame pose."""
    x,y,heading=finite_vector(relative,3,'工位相对观测')
    sx,sy,station_heading=finite_vector(station,3,'已知工位坐标')
    yaw=math.atan2(math.sin(station_heading-heading),math.cos(station_heading-heading))
    return {'x':sx-math.cos(yaw)*x+math.sin(yaw)*y,
            'y':sy-math.sin(yaw)*x-math.cos(yaw)*y,'yaw':yaw}


class ContinuousEvidence:
    """Only new consecutive source samples can grow the accepted duration."""
    def __init__(self, duration, max_gap=.15):
        self.duration, self.max_gap = duration, max_gap
        self.started = self.last = None

    def update(self, stamp, valid):
        if not math.isfinite(stamp):
            self.started = self.last = None
            return False
        if self.last is not None and stamp == self.last:
            return False
        if self.last is not None and (stamp < self.last or stamp-self.last > self.max_gap):
            self.started = None
        self.last = stamp
        if not valid:
            self.started = None
            return False
        if self.started is None:
            self.started = stamp
        return stamp-self.started >= self.duration


def car_pose(raw):
    p, q = raw['car']['position'], raw['car']['quaternion_wxyz']
    return {'x': p[0], 'y': p[1],
            'yaw': math.atan2(2*(q[0]*q[3]+q[1]*q[2]), 1-2*(q[2]*q[2]+q[3]*q[3]))}


def stopped(raw):
    return raw['car']['speed'] < .01 and abs(raw['car']['yaw_rate']) < .01


def tip_forces(raw):
    return list(raw['finger_normal_forces_n'].values())


def cargo_footprint_inside(raw):
    """Keep every rotated cargo corner within the original tray boundary."""
    p = raw['cargo']['position_relative_tray']
    q = raw['cargo']['quaternion_wxyz']
    w, x, y, z = q
    rotation = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    tray = raw['tray']['rotation_world']
    extent = [sum(abs(sum(tray[k][axis]*rotation[k][j] for k in range(3)))*half
                  for j, half in enumerate((.009, .009, .008))) for axis in range(2)]
    return all(abs(p[i])+extent[i] <= .058 for i in range(2))


def settled_cargo(raw):
    """Full rotated box footprint, tray support, released tips and relative rest."""
    velocity = raw['cargo']['velocity_relative_tray']
    return (cargo_footprint_inside(raw)
            and raw['cargo_tray_floor_contact'] and max(tip_forces(raw)) < .02
            and math.sqrt(sum(v*v for v in velocity)) < .002)


def release_ready_for_retreat(raw):
    """The open moving jaw clears first; the fixed tip leaves on retreat.

    Match SO101's source release transition. Final handover still calls
    settled_cargo and requires both tip forces below the original threshold.
    """
    return (cargo_footprint_inside(raw) and raw['cargo_tray_floor_contact']
            and raw['q6'][5] > .45
            and raw['finger_normal_forces_n']['pad_moving_jaw'] < .02
            and math.sqrt(sum(v*v for v in raw['cargo']['velocity_relative_tray'])) < .002)


def cargo_retained(raw):
    p = raw['cargo']['position_relative_tray']
    return (abs(p[0]) <= .047 and abs(p[1]) <= .047 and -.002 <= p[2] <= .04
            and raw['cargo_tray_floor_contact'] and cargo_footprint_inside(raw))


def arm_home_quiet(raw, home):
    """Preserve the original six-joint home and velocity thresholds."""
    q = finite_vector(raw['q6'], 6, '机械臂交接关节位置')
    velocity = finite_vector(raw['qvel6'], 6, '机械臂交接关节速度')
    home = finite_vector(home, 6, '机械臂回位参考')
    return (max(abs(value-target) for value, target in zip(q, home)) < .02
            and math.sqrt(sum(value*value for value in velocity)) < .05)


def transport_handoff_ready(raw, home):
    """The completed placement must establish all transport preconditions."""
    return (raw['car_hold'] is True and stopped(raw) and arm_home_quiet(raw, home)
            and cargo_retained(raw) and settled_cargo(raw))
