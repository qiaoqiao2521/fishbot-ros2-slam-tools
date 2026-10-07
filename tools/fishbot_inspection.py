#!/usr/bin/python3
"""Simulation-only inspection: Nav2 arrival, fresh RGB evidence, and return."""
import argparse
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time

import numpy as np
from PIL import Image as PillowImage

from fishbot_inspection_vision import analyze_rgb, save_report
from fishbot_passage_goal import PendingGoal, heading_from_quaternion


def validate_environment(env):
    if (env.get('ROS_DOMAIN_ID') != '97'
            or env.get('FISHBOT_MUJOCO_DOMAIN_ID') != '97'
            or env.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'
            or env.get('ROS_STATIC_PEERS', '')):
        raise ValueError('Inspection requires isolated simulation domain 97 and loopback discovery')


def stamp_seconds(stamp):
    return stamp.sec + stamp.nanosec * 1e-9


def fresh(stamp, received, now, wall, limit=.6):
    return (all(math.isfinite(v) for v in (stamp, received, now, wall))
            and -.05 <= now-stamp <= limit and 0 <= wall-received <= limit)


def decode_rgb(message):
    """Respect Image.step and encoding; never interpret a padded row as pixels."""
    if message.encoding not in ('rgb8', 'bgr8'):
        raise ValueError('Camera requires rgb8 or bgr8')
    if not 1 <= message.width <= 4096 or not 1 <= message.height <= 4096:
        raise ValueError('Invalid camera dimensions')
    if message.step < message.width*3 or len(message.data) != message.step*message.height:
        raise ValueError('Malformed camera payload/stride')
    pixels = np.frombuffer(bytes(message.data), dtype=np.uint8).reshape(message.height, message.step)
    rgb = pixels[:, :message.width*3].reshape(message.height, message.width, 3)
    return (rgb[:, :, ::-1] if message.encoding == 'bgr8' else rgb).copy()


def pose_values(pose):
    p, q = pose.position, pose.orientation
    values = [p.x, p.y, heading_from_quaternion((q.x, q.y, q.z, q.w))]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Nonfinite pose')
    return values


def pose_error(actual, goal):
    return (math.dist(actual[:2], goal[:2]),
            abs(math.atan2(math.sin(actual[2]-goal[2]), math.cos(actual[2]-goal[2]))))


def validate_capture_pose(frame_id, image_stamp, truth_stamp, pose, velocity, goal):
    if frame_id != 'inspection_camera_optical_frame':
        raise ValueError('unexpected camera optical frame')
    if not all(math.isfinite(v) for v in [image_stamp, truth_stamp, *pose, *velocity, *goal]):
        raise ValueError('nonfinite capture pose/time')
    if abs(image_stamp-truth_stamp) > .12:
        raise ValueError('image has no time-aligned physical pose')
    if max(abs(v) for v in velocity) > .015:
        raise ValueError('robot was moving at image capture')
    xy, yaw = pose_error(pose, goal)
    if xy > .22 or yaw > .25:
        raise ValueError('image captured outside the requested observation pose')
    return {'pose': pose, 'truth_stamp': truth_stamp, 'time_error_s': abs(image_stamp-truth_stamp),
            'physical_error': {'xy_m': xy, 'yaw_rad': yaw}, 'velocity': velocity}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--goal-timeout', type=float, default=90.)
    parser.add_argument('--camera-topic', default='/inspection/camera/image_raw')
    args = parser.parse_args()
    validate_environment(os.environ)
    if not math.isfinite(args.goal_timeout) or not 1 <= args.goal_timeout <= 120:
        parser.error('goal timeout must be 1..120 wall seconds')
    route = json.loads(args.route.read_text())
    stations = route['stations']
    for station in [*stations, {'goal': route['home']}]:
        goal = station['goal']
        if len(goal) != 3 or not all(math.isfinite(v) and abs(v) <= 8 for v in goal):
            parser.error('invalid synthetic route pose')
    if len(stations) != 3:
        parser.error('this fixture requires three stations')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output/'report.json').exists():
        parser.error('report already exists; use a new output directory')

    import rclpy
    from rclpy.node import Node
    from rclpy.action import ActionClient
    from rclpy.parameter import Parameter
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.signals import SignalHandlerOptions
    from sensor_msgs.msg import Image, LaserScan
    from nav_msgs.msg import Odometry
    from nav2_msgs.action import NavigateToPose
    from mujoco_ros2_control_msgs.msg import FreeJointStateArray
    from tf2_ros import Buffer, TransformListener
    from lifecycle_msgs.srv import GetState

    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = Node('fishbot_visual_inspection', parameter_overrides=[Parameter('use_sim_time', value=True)])
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    action = ActionClient(node, NavigateToPose, '/navigate_to_pose')
    samples, trajectory, interrupts = {}, [], []
    truth_history = deque(maxlen=120)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: interrupts.append(signum))
    start = time.monotonic()
    report = {'schema_version': 1, 'environment': 'MuJoCo simulation', 'domain': 97,
              'overall_status': 'running', 'stations': [], 'return_home': {},
              'vision_method': 'RGB blue-panel and red/green indicator rules; synthetic fixture only',
              'camera_topic': args.camera_topic, 'trajectory': trajectory}
    pending = None

    def remember(name, message):
        samples[name] = (message, time.monotonic(), stamp_seconds(message.header.stamp))

    def truth_callback(message):
        for body in message.free_joints:
            if body.name == 'base_footprint':
                samples['truth'] = (body, time.monotonic(), stamp_seconds(message.header.stamp))
                truth_history.append((samples['truth'][2], body))
                if not trajectory or samples['truth'][2]-trajectory[-1][0] >= .2:
                    trajectory.append([samples['truth'][2], *pose_values(body.pose.pose)])

    node.create_subscription(Image, args.camera_topic, lambda m: remember('image', m), qos_profile_sensor_data)
    node.create_subscription(Odometry, '/odom', lambda m: remember('odom', m), qos_profile_sensor_data)
    node.create_subscription(LaserScan, '/scan', lambda m: remember('scan', m), qos_profile_sensor_data)
    node.create_subscription(FreeJointStateArray, '/ground_truth/free_joint_states', truth_callback, qos_profile_sensor_data)

    def now():
        return node.get_clock().now().nanoseconds*1e-9

    def sample(name):
        value = samples.get(name)
        if value is None or not fresh(value[2], value[1], now(), time.monotonic()):
            raise RuntimeError(f'{name} missing or stale in source/receive time')
        return value

    def spin(until, predicate, health=False, allow_interrupted=False):
        while time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=.025)
            if interrupts and not allow_interrupted:
                raise InterruptedError('inspection interrupted')
            if health:
                for name in ('odom', 'scan', 'truth'):
                    sample(name)
            if predicate():
                return
        raise TimeoutError('bounded inspection operation timed out')

    def wait_future(future, duration, health=False, allow_interrupted=False):
        spin(time.monotonic()+duration, future.done, health, allow_interrupted)
        return future.result()

    def stationary(duration=.6, allow_interrupted=False):
        stable_since, last_stamp, count = None, None, 0
        def settled():
            nonlocal stable_since, last_stamp, count
            body, _, stamp = sample('truth')
            odom = sample('odom')[0]
            values = []
            for twist in (body.twist.twist, odom.twist.twist):
                values.extend([twist.linear.x, twist.linear.y, twist.angular.z])
            if not all(math.isfinite(v) for v in values):
                raise RuntimeError('nonfinite stationary feedback')
            if max(abs(v) for v in values) > .015:
                stable_since, count = None, 0
                return False
            if stamp != last_stamp:
                count += 1
                last_stamp = stamp
                if stable_since is None:
                    stable_since = time.monotonic()
            return count >= 5 and time.monotonic()-stable_since >= duration
        spin(time.monotonic()+5, settled, allow_interrupted=allow_interrupted)
        return {'verified': True, 'truth': pose_values(sample('truth')[0].pose.pose),
                'stamp': sample('truth')[2], 'duration_s': duration, 'samples': count}

    def persist():
        report['elapsed_s'] = round(time.monotonic()-start, 3)
        temporary = output/'report.json.tmp'
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        temporary.replace(output/'report.json')
        save_report(report, output)

    def navigate(target, record):
        nonlocal pending
        record['goal'] = target
        evidence = record.setdefault('action', {})
        pending = PendingGoal(evidence)
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = node.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = target[:2]
        goal.pose.pose.orientation.z = math.sin(target[2]/2)
        goal.pose.pose.orientation.w = math.cos(target[2]/2)
        goal.behavior_tree = str(Path(__file__).parent/'config/fishbot_passage_tree.xml')
        began = time.monotonic()
        handle = wait_future(pending.track(action.send_goal_async(goal)), 8, health=True)
        if pending.handle is None:
            pending._accepted(pending.send_future)
        if not handle.accepted:
            raise RuntimeError('Nav2 rejected inspection goal')
        response = wait_future(pending.get_result(), args.goal_timeout, health=True)
        evidence.update(status=response.status, error_code=response.result.error_code,
                        elapsed_s=round(time.monotonic()-began, 3))
        if response.status != 4 or response.result.error_code != 0:
            raise RuntimeError('Nav2 goal failed')
        record['stationary'] = stationary()
        record['pose'] = pose_values(sample('truth')[0].pose.pose)
        xy, yaw = pose_error(record['pose'], target)
        record['physical_error'] = {'xy_m': xy, 'yaw_rad': yaw}
        if xy > .22 or yaw > .25:
            raise RuntimeError('Nav2 success did not meet independent physical pose tolerance')
        transform = buffer.lookup_transform('map', 'base_footprint', rclpy.time.Time())
        record['localization_stamp'] = stamp_seconds(transform.header.stamp)
        if abs(now()-record['localization_stamp']) > .8:
            raise RuntimeError('localization transform stale after arrival')
        pending = None

    def capture(record, index):
        after = now()
        frames = []
        last = after
        deadline = time.monotonic()+5
        while len(frames) < 3:
            def new_frame():
                value = samples.get('image')
                return value is not None and value[2] > last and fresh(value[2], value[1], now(), time.monotonic())
            spin(deadline, new_frame, health=True)
            message, _, stamp = sample('image')
            truth_stamp, body = min(truth_history, key=lambda value: abs(value[0]-stamp))
            twist = body.twist.twist
            binding = validate_capture_pose(message.header.frame_id, stamp, truth_stamp,
                pose_values(body.pose.pose), [twist.linear.x, twist.linear.y, twist.angular.z], record['goal'])
            rgb = decode_rgb(message)
            observation = analyze_rgb(rgb)
            photo = f'station-{index+1}-frame-{len(frames)+1}.png'
            path = output/photo
            PillowImage.fromarray(rgb).save(path)
            frames.append({'photo': photo, 'capture_stamp': stamp, 'frame_id': message.header.frame_id,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), **binding, **observation})
            last = stamp
        record['frames'] = frames
        record.update({key: frames[-1][key] for key in ('photo', 'capture_stamp', 'frame_id', 'evidence')})
        record['pose'] = frames[-1]['pose']
        states = [frame['state'] for frame in frames]
        record['state'] = states[0] if len(set(states)) == 1 else 'unknown'
        record['reason'] = frames[-1]['reason'] if len(set(states)) == 1 else 'three fresh frames disagree'
        record['post_capture_stationary'] = stationary(.3)
        print(json.dumps({'station': record['name'], 'state': record['state'], 'photo': str(output/record['photo'])}, ensure_ascii=False), flush=True)

    try:
        def ready():
            try:
                for name in ('image', 'odom', 'scan', 'truth'):
                    sample(name)
                return action.server_is_ready() and buffer.can_transform('map', 'base_footprint', rclpy.time.Time())
            except RuntimeError:
                return False
        spin(time.monotonic()+55, ready)
        for name in ('amcl', 'controller_server', 'bt_navigator', 'collision_monitor'):
            client = node.create_client(GetState, f'/{name}/get_state')
            try:
                deadline = time.monotonic()+30
                while time.monotonic() < deadline:
                    if client.wait_for_service(timeout_sec=.2):
                        state = wait_future(client.call_async(GetState.Request()), 3)
                        if state.current_state.id == 3:
                            break
                    rclpy.spin_once(node, timeout_sec=.1)
                else:
                    raise RuntimeError(f'{name} did not become ACTIVE')
            finally:
                node.destroy_client(client)
        publishers = sorted(p.node_name for p in node.get_publishers_info_by_topic('/cmd_vel'))
        subscribers = sorted(p.node_name for p in node.get_subscriptions_info_by_topic('/cmd_vel'))
        if publishers != ['collision_monitor'] or subscribers != ['diff_drive_controller']:
            raise RuntimeError(f'unexpected simulation command topology: {publishers} -> {subscribers}')
        report['command_chain'] = {'publishers': publishers, 'subscribers': subscribers}
        report['initial_stationary'] = stationary()
        for index, station in enumerate(stations):
            record = {'name': station['name'], 'question': station['question'], 'state': 'pending'}
            report['stations'].append(record)
            navigate(station['goal'], record)
            capture(record, index)
            persist()
        navigate(route['home'], report['return_home'])
        report['return_home']['completed'] = True
        report['overall_status'] = ('completed' if all(s['state'] != 'unknown' for s in report['stations'])
                                    else 'completed_with_unknown')
    except Exception as exc:
        report['overall_status'] = 'interrupted' if interrupts else 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if pending is not None:
            try:
                pending.cancel()
                spin(time.monotonic()+5,
                     lambda: pending.get_result() is not None and pending.get_result().done(),
                     allow_interrupted=True)
            except Exception as exc:
                report.setdefault('cleanup_errors', []).append('cancellation: '+str(exc))
            finally:
                try:
                    pending.refresh()
                except Exception as exc:
                    report.setdefault('cleanup_errors', []).append('cancellation evidence: '+str(exc))
        try:
            report['final_stationary'] = stationary(1., allow_interrupted=True)
        except Exception as exc:
            report['overall_status'] = 'failed'
            report.setdefault('cleanup_errors', []).append('stop feedback: '+str(exc))
        persist()
        node.destroy_node()
        rclpy.try_shutdown()
    print(json.dumps({'overall_status': report['overall_status'], 'report': str(output/'index.html'),
                      'elapsed_s': report['elapsed_s']}, ensure_ascii=False), flush=True)
    return 0 if report['overall_status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
