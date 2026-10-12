"""Exercise persistent ownership without ROS nodes or DDS participants."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'fishbot_passage_goal.py'
SPEC = importlib.util.spec_from_file_location('passage_goal_runtime', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def pose():
    return SimpleNamespace(header=SimpleNamespace(), pose=SimpleNamespace(
        position=SimpleNamespace(x=0., y=0., z=0.),
        orientation=SimpleNamespace(x=0., y=0., z=0., w=1.)))


class Future:
    def __init__(self, value=None, ready=True, error=None):
        self.value, self.ready, self.error = value, ready, error
        self.callbacks = []

    def done(self):
        return self.ready

    def result(self):
        if self.error:
            raise self.error
        return self.value

    def add_done_callback(self, callback):
        self.callbacks.append(callback)
        if self.ready:
            callback(self)

    def resolve(self, value):
        self.value, self.ready = value, True
        for callback in self.callbacks:
            callback(self)


class FakeROS:
    """Only the interfaces needed by the production goal path, with a fake clock."""
    def __init__(self, mode='success', odom_mode='fresh'):
        self.wall, self.mode, self.odom_mode = 100., mode, odom_mode
        self.inits = self.shutdowns = self.nodes = self.clients = self.sends = 0
        self.destroys = self.cancels = self.spin_count = 0
        self.events, self.subscriptions = [], {}
        self.last_send = None
        self.target = [0., 0., 0.]
        owner = self

        class Node:
            def __init__(self, *_args, **_kwargs):
                owner.nodes += 1

            def create_client(self, *_args):
                return SimpleNamespace(service_is_ready=lambda: True,
                    wait_for_service=lambda **_kwargs: True,
                    call_async=lambda _request: Future(SimpleNamespace(success=True)))

            def create_subscription(self, _type, topic, callback, _qos):
                owner.subscriptions[topic] = callback

            def get_clock(self):
                return SimpleNamespace(now=lambda: SimpleNamespace(
                    nanoseconds=round(owner.wall * 1e9), to_msg=owner.stamp))

            def get_publishers_info_by_topic(self, _topic):
                return [SimpleNamespace(node_name='fishbot_command_guard')]

            def get_subscriptions_info_by_topic(self, _topic):
                return [SimpleNamespace(node_name='diff_drive_controller')]

            def destroy_node(self):
                owner.destroys += 1

        class ActionClient:
            def __init__(self, *_args):
                owner.clients += 1

            def server_is_ready(self):
                return True

            def send_goal_async(self, goal, **_kwargs):
                owner.sends += 1
                if owner.mode == 'send_error':
                    raise RuntimeError('acceptance unknown')
                owner.target = [goal.pose.pose.position.x, goal.pose.pose.position.y, 0.]
                owner.last_send = Future(Handle(), ready=owner.mode != 'late_ack')
                return owner.last_send

        class Handle:
            accepted = True

            def __init__(self):
                self.response = SimpleNamespace(status=4, result=SimpleNamespace(error_code=0))
                self.future = Future(self.response,
                    error=RuntimeError('result unknown') if owner.mode == 'result_error' else None)

            def get_result_async(self):
                return self.future

            def cancel_goal_async(self):
                owner.cancels += 1
                self.response.status = 5
                return Future(SimpleNamespace(goals_canceling=[1]))

        class Buffer:
            def can_transform(self, *_args):
                return True

            def lookup_transform(self, *_args):
                return SimpleNamespace(header=SimpleNamespace(stamp=owner.stamp()),
                    transform=SimpleNamespace(translation=SimpleNamespace(
                        x=owner.target[0], y=owner.target[1]),
                        rotation=SimpleNamespace(x=0., y=0., z=0., w=1.)))

        self.rclpy = SimpleNamespace(init=self.init, shutdown=self.shutdown, spin_once=self.spin,
                                    time=SimpleNamespace(Time=lambda: None))
        action_type = SimpleNamespace(Goal=SimpleNamespace)
        self.modules = {
            'rclpy': self.rclpy,
            'rclpy.action': SimpleNamespace(ActionClient=ActionClient),
            'rclpy.node': SimpleNamespace(Node=Node),
            'rclpy.parameter': SimpleNamespace(Parameter=lambda *_args, **_kwargs: None),
            'rclpy.signals': SimpleNamespace(SignalHandlerOptions=SimpleNamespace(NO=0)),
            'rclpy.qos': SimpleNamespace(qos_profile_sensor_data=object()),
            'nav2_msgs.action': SimpleNamespace(NavigateToPose=action_type, NavigateThroughPoses=action_type),
            'geometry_msgs.msg': SimpleNamespace(PoseStamped=pose),
            'nav_msgs.msg': SimpleNamespace(Odometry=object),
            'diagnostic_msgs.msg': SimpleNamespace(DiagnosticArray=object),
            'std_srvs.srv': SimpleNamespace(Trigger=SimpleNamespace(Request=SimpleNamespace)),
            'tf2_ros': SimpleNamespace(Buffer=Buffer, TransformListener=lambda *_args: object()),
        }

    def stamp(self, offset=0.):
        now = self.wall + offset
        sec = int(now)
        return SimpleNamespace(sec=sec, nanosec=round((now-sec)*1e9))

    def init(self, **_kwargs):
        self.inits += 1

    def shutdown(self):
        self.shutdowns += 1

    def spin(self, _node, **_kwargs):
        self.events.append('spin')
        self.spin_count += 1
        self.wall += .05
        guard = SimpleNamespace(header=SimpleNamespace(stamp=self.stamp()), status=[
            SimpleNamespace(name='fishbot_command_guard', level=0, message='healthy', values=[
                SimpleNamespace(key='execute', value='true'),
                SimpleNamespace(key='profile', value='fishbot_passage')])])
        self.subscriptions['/fishbot_command_guard/diagnostics'](guard)
        if self.odom_mode != 'receipt_stale' or self.spin_count == 1:
            stamp = self.stamp(-1 if self.odom_mode == 'source_stale' else 0.)
            odom = SimpleNamespace(header=SimpleNamespace(stamp=stamp),
                twist=SimpleNamespace(twist=SimpleNamespace(
                    linear=SimpleNamespace(x=.02 if self.odom_mode == 'moving' else 0.),
                    angular=SimpleNamespace(z=0.))),
                pose=SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=0., y=0.))))
            self.subscriptions['/odom'](odom)

    def hook(self):
        self.events.append('hook')


class PersistentRuntimeTests(unittest.TestCase):
    @staticmethod
    def args(**changes):
        values = dict(domain=96, real=False, use_sim_time=True, timeout=5.,
                      distance=None, target=[1., 0., 0.], timing_profile='strict')
        values.update(changes)
        return SimpleNamespace(**values)

    def session(self, fake):
        self.enterContext(patch.dict('sys.modules', fake.modules))
        self.enterContext(patch.object(module.time, 'monotonic', lambda: fake.wall))
        self.enterContext(patch.dict(module.os.environ, {}, clear=False))
        runtime = module.PassageGoalRuntime(self.args())
        self.addCleanup(runtime.close)
        return runtime

    def test_two_goals_and_idle_reuse_one_node_client_and_context(self):
        fake = FakeROS()
        runtime = self.session(fake)
        first = module.run_goal(runtime, self.args(), on_spin=fake.hook)
        runtime.spin_for(1., on_spin=fake.hook)
        second = runtime.execute(self.args(target=[0., 0., 0.]), on_spin=fake.hook)
        for result in (first, second):
            self.assertTrue(result['completed'])
            self.assertTrue(result['stationary_feedback'])
            self.assertEqual(result['action_status'], 4)
            self.assertEqual(result['goal_send_count'], 1)
            self.assertNotIn('cleanup_errors', result)
        self.assertEqual((fake.inits, fake.nodes, fake.clients, fake.sends), (1, 1, 1, 2))
        self.assertEqual(fake.events, ['hook', 'spin'] * fake.spin_count)
        self.assertEqual((fake.destroys, fake.shutdowns), (0, 0))
        runtime.close(second)
        runtime.close(second)
        self.assertEqual((fake.destroys, fake.shutdowns), (1, 1))

    def test_failed_send_retains_ownership_and_never_resends(self):
        fake = FakeROS(mode='send_error')
        runtime = self.session(fake)
        result = module.run_goal(runtime, self.args())
        pending = runtime.pending
        self.assertIn('acceptance unknown', result['error'])
        self.assertIsNone(pending.send_future)
        self.assertIs(runtime.last_result, result)
        with self.assertRaisesRegex(RuntimeError, 'ownership is retained'):
            module.run_goal(runtime, self.args())
        self.assertIs(runtime.pending, pending)
        self.assertEqual(fake.sends, 1)

    def test_late_ack_keeps_cancel_intent_and_cannot_start_new_goal(self):
        fake = FakeROS(mode='late_ack')
        runtime = self.session(fake)
        result = module.run_goal(runtime, self.args())
        pending = runtime.pending
        self.assertFalse(result['completed'])
        self.assertTrue(pending.cancel_requested)
        self.assertTrue(result['goal_ack_pending'])
        fake.last_send.resolve(fake.last_send.value)
        pending.refresh()
        self.assertTrue(result['canceled'])
        self.assertEqual(fake.cancels, 1)
        with self.assertRaisesRegex(RuntimeError, 'ownership is retained'):
            runtime.execute(self.args())
        self.assertIs(runtime.pending, pending)
        self.assertEqual(fake.sends, 1)

    def test_unknown_result_retains_pending_and_blocks_new_goal(self):
        fake = FakeROS(mode='result_error')
        runtime = self.session(fake)
        result = module.run_goal(runtime, self.args())
        self.assertIn('result unknown', result['error'])
        self.assertTrue(result['cleanup_errors'])
        self.assertTrue(runtime.blocked)
        with self.assertRaises(RuntimeError):
            runtime.execute(self.args())
        self.assertEqual(fake.sends, 1)

    def test_success_with_moving_or_either_stale_age_blocks_next_goal(self):
        for mode in ('moving', 'receipt_stale', 'source_stale'):
            with self.subTest(mode=mode):
                fake = FakeROS(odom_mode=mode)
                runtime = self.session(fake)
                result = runtime.execute(self.args())
                self.assertTrue(result['completed'])
                self.assertFalse(result['stationary_feedback'])
                self.assertTrue(result['guard_stop_acknowledged'])
                with self.assertRaises(RuntimeError):
                    runtime.execute(self.args())
                self.assertEqual(fake.sends, 1)
                runtime.close()

    def test_shape_and_domain_cannot_change_without_dispatch(self):
        fake = FakeROS()
        runtime = self.session(fake)
        for args, route in ((self.args(domain=102), None),
                            (self.args(use_sim_time=False), None),
                            (self.args(), [[1., 0., 0.], [2., 0., 0.]])):
            with self.assertRaisesRegex(ValueError, 'remain fixed'):
                runtime.execute(args, route)
        self.assertEqual(fake.sends, 0)

    def test_close_error_is_recorded_and_does_not_skip_shutdown(self):
        fake = FakeROS()
        runtime = self.session(fake)
        result = runtime.execute(self.args())
        def fail_destroy():
            raise RuntimeError('destroy failure')
        runtime.node.destroy_node = fail_destroy
        runtime.close(result)
        self.assertEqual(fake.shutdowns, 1)
        self.assertEqual(result['cleanup_errors'], ['destroy node: destroy failure'])


if __name__ == '__main__':
    unittest.main()
