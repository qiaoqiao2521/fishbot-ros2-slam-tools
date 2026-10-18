"""Check the thin existing-node attachment, including its actual message stamps."""
from concurrent.futures import Future
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fishbot_manual_ros import attach_manual


class Stamped:
    def __init__(self):
        self.header = SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=0), frame_id='')
        self.twist = SimpleNamespace(linear=SimpleNamespace(x=0.), angular=SimpleNamespace(z=0.))


class FakeNode:
    def __init__(self):
        self.publishers, self.clients, self.timers = {}, {}, []

    def create_publisher(self, kind, topic, depth):
        messages = []
        result = SimpleNamespace(publish=messages.append, messages=messages)
        self.publishers[topic] = result
        return result

    def create_client(self, kind, name):
        future = Future()
        result = SimpleNamespace(service_is_ready=lambda: True, call_async=lambda request: future)
        self.clients[name] = result
        return result

    def create_timer(self, period, callback, clock):
        timer = SimpleNamespace(period=period, callback=callback)
        self.timers.append(timer)
        return timer

    def get_clock(self):
        return SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=10_000_000_000))


class ManualRosTests(unittest.TestCase):
    def test_attachment_uses_only_upstream_topics_existing_guard_and_steady_timer(self):
        modules = {}
        for name in ('geometry_msgs.msg', 'rclpy.clock', 'std_msgs.msg', 'std_srvs.srv'):
            modules[name] = ModuleType(name)
        modules['geometry_msgs.msg'].TwistStamped = Stamped
        modules['rclpy.clock'].Clock = lambda **kwargs: kwargs
        modules['rclpy.clock'].ClockType = SimpleNamespace(STEADY_TIME='steady')
        modules['std_msgs.msg'].Bool = lambda **kwargs: SimpleNamespace(**kwargs)
        modules['std_srvs.srv'].Trigger = SimpleNamespace(Request=lambda: object())
        node = FakeNode()
        with patch.dict(sys.modules, modules):
            adapter = attach_manual(node, str(uuid.uuid4()), 'map-a', native_owner=lambda: {'status': 'idle'},
                                    cancel_native=lambda task_id: None, guard_available=lambda: True, enabled=True)
        self.assertEqual(set(node.publishers), {'/cmd_vel_manual', '/manual/nav_lock'})
        self.assertEqual(set(node.clients), {'/fishbot_command_guard/stop', '/fishbot_command_guard/reset'})
        self.assertEqual(node.timers[0].period, .02)
        adapter.controller.ports.publish_manual(-.03, .2, 9.8)
        message = node.publishers['/cmd_vel_manual'].messages[-1]
        self.assertEqual((message.header.stamp.sec, message.header.stamp.nanosec), (9, 800_000_000))
        self.assertEqual((message.twist.linear.x, message.twist.angular.z), (-.03, .2))
        self.assertTrue(adapter.controller.enabled)
        node.timers[0].callback()
        self.assertEqual(node.publishers['/cmd_vel_manual'].messages[-1].twist.linear.x, 0.)

    def test_disabled_profile_does_not_import_ros_or_create_any_ports(self):
        node = FakeNode()
        result = attach_manual(node, str(uuid.uuid4()), None, native_owner=lambda: {'status': 'idle'},
                               cancel_native=lambda task_id: None, guard_available=lambda: False)
        self.assertIsNone(result)
        self.assertEqual(node.publishers, {})
        self.assertEqual(node.timers, [])


if __name__ == '__main__':
    unittest.main()
