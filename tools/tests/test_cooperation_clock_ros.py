"""Native TimeSource lifecycle with the bridge executor deliberately not spun."""
import ast
import copy
from pathlib import Path
import threading
import time
import unittest

try:
    import rclpy
    from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
    from rclpy.executors import SingleThreadedExecutor, MultiThreadedExecutor, ExternalShutdownException
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from rclpy.time_source import TimeSource
    from rosgraph_msgs.msg import Clock
except ImportError:
    rclpy = None


@unittest.skipIf(rclpy is None, 'source /opt/ros/jazzy/setup.bash for native ROS tests')
class ClockReceiverTests(unittest.TestCase):
    def test_configured_history_recovers_exact_pairs_after_a_dispatch_gap(self):
        from geometry_msgs.msg import PoseStamped
        from message_filters import Subscriber, TimeSynchronizer
        tree = ast.parse((Path(__file__).parents[1] / 'cooperation_bridge.py').read_text())
        depth = next(n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Attribute) and t.attr == 'depth'
                             and isinstance(t.value, ast.Name) and t.value.id == 'perception_qos'
                             for t in n.targets))
        rclpy.init()
        node = Node('test_station_pair_backlog'); executor = SingleThreadedExecutor()
        executor.add_node(node)
        try:
            results = {}
            for history in (1, depth):
                qos = QoSProfile(depth=history, reliability=ReliabilityPolicy.BEST_EFFORT)
                topics = [f'/pair_backlog_{history}/{side}' for side in ('pose', 'detection')]
                filters = [Subscriber(node, PoseStamped, topic, qos_profile=qos) for topic in topics]
                sync = TimeSynchronizer(filters, queue_size=5)
                pairs = []
                sync.registerCallback(lambda a, b: pairs.append((a.header.stamp.sec, b.header.stamp.sec)))
                publishers = [node.create_publisher(PoseStamped, topic, qos) for topic in topics]
                deadline = time.monotonic() + 3
                while not all(p.get_subscription_count() for p in publishers) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(all(p.get_subscription_count() for p in publishers))
                # Pause all takes while the two streams arrive one sample apart.
                for tick in range(5):
                    for publisher, stamp in zip(publishers, (tick+1, tick)):
                        message = PoseStamped(); message.header.stamp.sec = stamp
                        publisher.publish(message)
                    time.sleep(.01)
                deadline = time.monotonic() + .3
                while time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=.01)
                results[history] = pairs
                for sub in filters: node.destroy_subscription(sub.sub)
                for publisher in publishers: node.destroy_publisher(publisher)
            self.assertEqual(results[1], [])
            self.assertEqual(sorted(results[depth]), [(i, i) for i in range(1, 5)])
        finally:
            executor.shutdown(); node.destroy_node(); rclpy.shutdown()

    def test_physics_updates_while_control_executor_is_not_spun(self):
        from std_msgs.msg import String
        tree = ast.parse((Path(__file__).parents[1] / 'cooperation_bridge.py').read_text())
        bridge = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == 'Bridge')
        methods = [copy.deepcopy(n) for n in bridge.body if isinstance(n, ast.FunctionDef)
                   and n.name in ('create_subscription', 'destroy_subscription')]
        module = ast.Module(body=[ast.ClassDef(name='Probe', bases=[ast.Name(id='Node', ctx=ast.Load())],
                           keywords=[], body=methods, decorator_list=[])], type_ignores=[])
        namespace = dict(Node=Node, Clock=Clock, TimeSource=TimeSource)
        exec(compile(ast.fix_missing_locations(module), '<actual-physics-routing>', 'exec'), namespace)
        rclpy.init()
        receiver = Node('test_dedicated_physics_receiver')
        probe = namespace['Probe'].__new__(namespace['Probe'])
        probe.clock_receiver = receiver
        probe.clock_callbacks = MutuallyExclusiveCallbackGroup()
        Node.__init__(probe, 'test_unspun_physics_control')
        values = []
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        subscription = probe.create_subscription(String, '/cooperation/physics_state',
            lambda message: values.append(int(message.data)), qos,
            callback_group=MutuallyExclusiveCallbackGroup())
        publisher = receiver.create_publisher(String, '/cooperation/physics_state', qos)
        executor = SingleThreadedExecutor(); executor.add_node(receiver)
        thread = threading.Thread(target=executor.spin); thread.start()
        try:
            deadline = time.monotonic()+3.
            while not publisher.get_subscription_count() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(publisher.get_subscription_count())
            for sequence in range(40):
                publisher.publish(String(data=str(sequence)))
                time.sleep(.02)
            deadline = time.monotonic()+1.
            while (not values or values[-1] != 39) and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(values, 'Physics feedback starved with control executor paused')
            self.assertEqual(values[-1], 39)
            self.assertIn(subscription, receiver.subscriptions)
            self.assertTrue(probe.destroy_subscription(subscription))
            self.assertNotIn(subscription, receiver.subscriptions)
        finally:
            executor.shutdown(); thread.join()
            probe.destroy_node(); receiver.destroy_node(); rclpy.shutdown()

    def test_receiver_failure_propagates_to_native_owner_executor(self):
        tree = ast.parse((Path(__file__).parents[1] / 'cooperation_bridge.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'spin_clock_receiver')
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<actual-clock-worker>', 'exec'), namespace)
        rclpy.init()
        release = threading.Event()
        class DelayedOwner(MultiThreadedExecutor):
            def create_task(self, callback, *args, **kwargs):
                def delayed():
                    if not release.wait(3):
                        raise RuntimeError('test did not release owner task')
                    return callback(*args, **kwargs)
                return super().create_task(delayed)
        receiver = SingleThreadedExecutor(); owner = DelayedOwner(num_threads=2)
        error = RuntimeError('injected clock callback failure')
        def fail():
            raise error
        receiver.create_task(fail)
        try:
            namespace['spin_clock_receiver'](receiver, owner, ExternalShutdownException)
            owner.spin_once(timeout_sec=1)  # Submit, but prevent failure until the done scan finishes.
            release.set()
            with self.assertRaises(RuntimeError) as caught:
                owner.spin_once(timeout_sec=1)
            self.assertIs(caught.exception, error)
        finally:
            release.set()
            receiver.shutdown(); owner.shutdown(); rclpy.shutdown()

    def test_native_clock_updates_without_control_executor_and_survives_toggle_and_reset(self):
        tree = ast.parse((Path(__file__).parents[1] / 'cooperation_bridge.py').read_text())
        bridge = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == 'Bridge')
        methods = [copy.deepcopy(n) for n in bridge.body if isinstance(n, ast.FunctionDef)
                   and n.name in ('create_subscription', 'destroy_subscription')]
        module = ast.Module(body=[ast.ClassDef(name='Probe', bases=[ast.Name(id='Node', ctx=ast.Load())],
                           keywords=[], body=methods, decorator_list=[])], type_ignores=[])
        namespace = dict(Node=Node, Clock=Clock, TimeSource=TimeSource)
        exec(compile(ast.fix_missing_locations(module), '<actual-bridge-clock-routing>', 'exec'), namespace)
        rclpy.init()
        receiver = Node('test_dedicated_clock_receiver')
        probe = namespace['Probe'].__new__(namespace['Probe'])
        probe.clock_receiver = receiver
        probe.clock_callbacks = MutuallyExclusiveCallbackGroup()
        received = []
        def observe(message, info, callback):
            received.append(message.clock.sec)
            return callback(message)
        probe.observe_clock = observe
        Node.__init__(probe, 'test_unspun_control', parameter_overrides=[Parameter('use_sim_time', value=True)])
        publisher = receiver.create_publisher(Clock, '/clock', QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        executor = SingleThreadedExecutor()
        executor.add_node(receiver)
        thread = threading.Thread(target=executor.spin)
        thread.start()
        try:
            def advance(seconds):
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    message = Clock(); message.clock.sec = seconds
                    publisher.publish(message)
                    if probe.get_clock().now().nanoseconds == seconds * 1_000_000_000:
                        return
                    time.sleep(.01)
                self.fail(f'Unspun control node did not receive clock {seconds}')
            advance(100)
            self.assertEqual(sum(s.topic_name == '/clock' for s in receiver.subscriptions), 1)
            self.assertEqual(sum(s.topic_name == '/clock' for s in probe.subscriptions), 0)
            self.assertTrue(probe.set_parameters([Parameter('use_sim_time', value=False)])[0].successful)
            self.assertEqual(sum(s.topic_name == '/clock' for s in receiver.subscriptions), 0)
            self.assertTrue(probe.set_parameters([Parameter('use_sim_time', value=True)])[0].successful)
            advance(101)
            advance(3)  # A scene reset is a real backward clock jump.
            self.assertIn(3, received)
            self.assertEqual(sum(s.topic_name == '/clock' for s in receiver.subscriptions), 1)
        finally:
            executor.shutdown(); thread.join()
            probe.destroy_node(); receiver.destroy_node(); rclpy.shutdown()
