"""Attach manual ports to an existing ROS owner node; never create an executor."""
from types import SimpleNamespace
from contextlib import nullcontext
import time

from fishbot_manual_lease import ManualLeaseController, TimePoint


def attach_manual(node, runtime_instance_id, map_id, *, native_owner, cancel_native,
                  guard_available, idle_guard_fault=None, enabled=False):
    """Only the existing execution owner may call this after its domain lock.

    ``guard_available`` must include the owner's fresh diagnostics/graph check.
    The caller feeds decoded source truth through ``controller.observe_truth``.
    Existing HTTP operations run on this same owner thread, not HTTP workers.
    """
    if not enabled:
        return None
    from geometry_msgs.msg import TwistStamped
    from rclpy.clock import Clock, ClockType
    from std_msgs.msg import Bool
    from std_srvs.srv import Trigger

    manual_pub = node.create_publisher(TwistStamped, '/cmd_vel_manual', 1)
    lock_pub = node.create_publisher(Bool, '/manual/nav_lock', 1)
    stop_client = node.create_client(Trigger, '/fishbot_command_guard/stop')
    reset_client = node.create_client(Trigger, '/fishbot_command_guard/reset')

    def now():
        return TimePoint(time.time_ns()//1_000_000, time.monotonic(),
                         node.get_clock().now().nanoseconds/1e9)

    def publish_manual(linear_x, angular_z, stamp):
        message = TwistStamped()
        nanoseconds = int(stamp*1e9)
        message.header.stamp.sec, message.header.stamp.nanosec = divmod(nanoseconds, 1_000_000_000)
        message.header.frame_id = 'base_footprint'
        message.twist.linear.x, message.twist.angular.z = float(linear_x), float(angular_z)
        manual_pub.publish(message)

    def call(client):
        if not client.service_is_ready():
            raise RuntimeError('guard service unavailable')
        return client.call_async(Trigger.Request())

    ports = SimpleNamespace(native_owner=native_owner, cancel_native=cancel_native,
        guard_available=lambda: bool(guard_available() and stop_client.service_is_ready()
                                      and reset_client.service_is_ready()),
        publish_manual=publish_manual, nav_lock=lambda locked: lock_pub.publish(Bool(data=locked)),
        guard_stop=lambda: call(stop_client), guard_reset=lambda: call(reset_client),
        idle_guard_fault=idle_guard_fault)
    controller = ManualLeaseController(runtime_instance_id, map_id, ports, enabled=enabled)
    def tick():
        with getattr(node, 'lock', nullcontext()):
            controller.tick(now())
    timer = node.create_timer(.02, tick,
                              clock=Clock(clock_type=ClockType.STEADY_TIME))
    return SimpleNamespace(controller=controller, now=now, timer=timer,
                           publishers=(manual_pub, lock_pub), clients=(stop_client, reset_client))
