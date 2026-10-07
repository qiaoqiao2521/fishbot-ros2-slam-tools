"""Offline checks for real guarded-mapping validation functions; no ROS import.

Run: python3 -B tools/tests/test_guarded_mapping.py
"""

import ast
import argparse
import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "fishbot_guarded_mapping.py"
tree = ast.parse(SOURCE.read_text(), filename=str(SOURCE))
clearance_node = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "clearance")
segment_node = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "Segment")
fresh_node = next(node for node in segment_node.body
                  if isinstance(node, ast.FunctionDef) and node.name == "fresh")
namespace = {"math": math, "time": NS(time=lambda: 1000.0, monotonic=lambda: 100.0)}
exec(compile(ast.Module(body=[clearance_node, fresh_node], type_ignores=[]),
             str(SOURCE), "exec"), namespace)
clearance = namespace["clearance"]
fresh = namespace["fresh"]


def movement_fragment(mode, requested, angle=0.0, forward=0.0, profile="conservative",
                      lateral=0.0, hold_heading=False, scan=None, commands=None):
    """Exercise actual CLI and signed-motion statements without running main."""
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "main")
    statements = list(ast.walk(main))

    def assignment(name):
        return next(node for node in statements if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == name
                            for target in node.targets))

    validation = next(node for node in main.body if isinstance(node, ast.If)
                      and "args.execute" in ast.unparse(node.test))
    direction_guard = next(node for node in statements if isinstance(node, ast.If)
                           and ast.unparse(node.test) == "args.mode in ('advance', 'reverse')")
    movement_loop = next(node for node in statements if isinstance(node, ast.While)
                         and ast.unparse(node.test) == "not interrupted")
    completion_index = next(index for index, node in enumerate(movement_loop.body)
                            if isinstance(node, ast.If)
                            and ast.unparse(node.test) == "progress >= amount")

    def reject(message):
        raise ValueError(message)

    commands = [] if commands is None else commands
    context = {"math": math, "clearance": clearance,
               "args": NS(mode=mode, amount=requested, execute=True,
                                         profile=profile, hold_heading=hold_heading),
               "parser": NS(error=reject), "began": 100.0, "now": 100.1, "angle": angle,
               "forward": forward, "lateral": lateral, "distance": 0.0,
               "node": NS(command=lambda v, w: commands.append((v, w)),
                          scan=scan if scan is not None else make_scan())}
    nodes = [assignment("limit"), assignment("amount"), validation,
             assignment("turn_sign"), assignment("linear_sign"), assignment("half_width"),
             assignment("rotation_clearance"), assignment("speed"),
             assignment("result"), assignment("deadline"),
             assignment("turn_progress"), assignment("linear_progress"), direction_guard,
             assignment("progress")]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), context)
    context["result"]["samples"].append({"elapsed": 0.1})
    # Run the actual completion/timeout/publish tail once, preserving its break.
    once = ast.For(target=ast.Name(id="_step", ctx=ast.Store()),
                   iter=ast.Tuple(elts=[ast.Constant(value=0)], ctx=ast.Load()),
                   body=movement_loop.body[completion_index:], orelse=[])
    fragment = ast.fix_missing_locations(ast.Module(body=[once], type_ignores=[]))
    exec(compile(fragment, str(SOURCE), "exec"), context)
    return context, commands, context["result"]["completed"]


def configured_clearance(scan, profile, mode="turn"):
    """Exercise the actual profile assignments and main's live clearance call."""
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "main")
    statements = list(ast.walk(main))
    nodes = [next(node for node in statements if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == name
                          for target in node.targets))
             for name in ("half_width", "rotation_clearance", "reason")]
    context = {"args": NS(profile=profile, mode=mode), "clearance": clearance,
               "node": NS(scan=scan, fresh=lambda: None)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), context)
    return context["reason"]


def startup_fragment(ready_at, odom_count=30, scan_count=15, fresh_reason=None):
    """Run the real startup wait and acceptance gate against virtual time."""
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "main")
    protected = next(node for node in main.body if isinstance(node, ast.Try))
    start = next(index for index, node in enumerate(protected.body)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "ready_until"
                         for target in node.targets))
    # Actual deadline assignment, waiting loop, and post-wait rejection gate.
    statements = protected.body[start:start + 3]
    clock = NS(ticks=0)
    node = NS(odom_count=0, scan_count=0, fresh=lambda: fresh_reason)

    def spin_once(target, timeout_sec):
        clock.ticks += 1
        if clock.ticks > 100:
            raise AssertionError("startup wait exceeded the bounded virtual-time budget")
        if clock.ticks / 10 >= ready_at:
            target.odom_count = odom_count
            target.scan_count = scan_count

    context = {"time": NS(monotonic=lambda: clock.ticks / 10),
               "rclpy": NS(spin_once=spin_once), "node": node, "interrupted": []}
    try:
        exec(compile(ast.Module(body=statements, type_ignores=[]),
                     str(SOURCE), "exec"), context)
    except RuntimeError as error:
        return clock.ticks / 10, str(error)
    return clock.ticks / 10, None


def make_scan():
    return NS(ranges=[2.0] * 361, angle_min=-math.pi,
              angle_increment=math.pi / 180, range_min=0.01, range_max=8.0)


def make_live_state():
    def header():
        return NS(stamp=NS(sec=1000, nanosec=0))

    odom = NS(header=header(),
              pose=NS(pose=NS(position=NS(x=0.0, y=0.0, z=0.0),
                              orientation=NS(x=0.0, y=0.0, z=0.0, w=1.0))),
              twist=NS(twist=NS(linear=NS(x=0.0), angular=NS(z=0.0))))
    return NS(odom=odom, scan=NS(header=header()),
              odom_at=100.0, scan_at=100.0, unwrapped_yaw=0.0)


class GuardedMappingTests(unittest.TestCase):
    def test_startup_exits_early_when_enough_fresh_samples_arrive(self):
        elapsed, error = startup_fragment(ready_at=0.3)
        self.assertIsNone(error)
        self.assertAlmostEqual(elapsed, 0.3)

    def test_startup_accepts_late_discovery_inside_eight_second_window(self):
        elapsed, error = startup_fragment(ready_at=6.2)
        self.assertIsNone(error)
        self.assertAlmostEqual(elapsed, 6.2)
        self.assertLess(elapsed, 8.0)

    def test_startup_still_rejects_stale_or_insufficient_samples_at_deadline(self):
        scenarios = (
            {"ready_at": 0.2, "fresh_reason": "scan timestamp outside freshness limit"},
            {"ready_at": 0.2, "odom_count": 29},
            {"ready_at": 0.2, "scan_count": 14},
            {"ready_at": 9.0},
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                elapsed, error = startup_fragment(**scenario)
                self.assertAlmostEqual(elapsed, 8.0)
                self.assertIsNotNone(error)

    def test_cli_profile_is_opt_in_and_evidence_records_effective_limits(self):
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "main")
        parser_statements = []
        for node in main.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                                                    and target.id == "args"
                                                    for target in node.targets):
                break
            parser_statements.append(node)
        context = {"argparse": argparse, "Path": Path, "__doc__": "test parser"}
        exec(compile(ast.Module(body=parser_statements, type_ignores=[]),
                     str(SOURCE), "exec"), context)
        argv = ["advance", "--amount", "0.1", "--execute", "--output", "unused.json"]
        self.assertEqual(context["parser"].parse_args(argv).profile, "conservative")
        self.assertEqual(context["parser"].parse_args(argv + ["--profile", "standard-model"]).profile,
                         "standard-model")
        self.assertEqual(context["parser"].parse_args(["reverse"] + argv[1:]).mode, "reverse")
        self.assertFalse(context["parser"].parse_args(argv).hold_heading)
        self.assertTrue(context["parser"].parse_args(argv + ["--hold-heading"]).hold_heading)
        for profile, half_width, speed in (("conservative", 0.27, 0.06),
                                           ("standard-model", 0.18, 0.03)):
            with self.subTest(profile=profile):
                state, commands, _ = movement_fragment("advance", 0.10, profile=profile)
                self.assertEqual(commands, [(speed, 0.0)])
                self.assertEqual((state["result"]["profile"], state["result"]["half_width"],
                                  state["result"]["speed"]), (profile, half_width, speed))
                if profile == "standard-model":
                    self.assertIn("not measured", state["result"]["model_assumption"])
                    self.assertEqual(state["result"]["rotation_clearance"], 0.20)
                else:
                    self.assertIsNone(state["result"]["model_assumption"])
                    self.assertEqual(state["result"]["rotation_clearance"], 0.25)
                state, commands, _ = movement_fragment("turn", -0.75, profile=profile)
                self.assertEqual(commands, [(0.0, -0.25)])
                self.assertEqual(state["result"]["speed"], -0.25)
                with self.assertRaises(ValueError):
                    movement_fragment("advance", 0.31, profile=profile)

    def test_model_corridor_allows_nineteen_cm_but_blocks_seventeen_cm_side_offset(self):
        for side_offset in (0.17, 0.19):
            with self.subTest(side_offset=side_offset):
                scene = make_scan()
                # A 45-degree return has equal forward and lateral coordinates.
                scene.ranges[225] = side_offset * math.sqrt(2)
                self.assertIsNotNone(clearance(scene, "advance"))
                if side_offset < 0.18:
                    self.assertIsNotNone(clearance(scene, "advance", half_width=0.18))
                else:
                    self.assertIsNone(clearance(scene, "advance", half_width=0.18))

    def test_forward_length_and_implicit_rotation_default_are_preserved(self):
        for width in (0.27, 0.18):
            for distance, blocked in ((0.33, True), (0.35, False)):
                with self.subTest(width=width, forward=distance):
                    scene = make_scan()
                    scene.ranges[180] = distance
                    self.assertEqual(clearance(scene, "advance", half_width=width) is not None,
                                     blocked)
            for distance, blocked in ((0.24, True), (0.26, False)):
                with self.subTest(width=width, rotation=distance):
                    scene = make_scan()
                    scene.ranges[270] = distance
                    self.assertEqual(clearance(scene, "turn", half_width=width) is not None,
                                     blocked)

    def test_actual_model_profile_rotation_allows_twenty_one_cm_but_blocks_nineteen_cm(self):
        for distance in (0.19, 0.21):
            with self.subTest(distance=distance):
                scene = make_scan()
                scene.ranges[270] = distance
                self.assertIsNotNone(clearance(scene, "turn"))
                self.assertIsNotNone(configured_clearance(scene, "conservative"))
                self.assertEqual(configured_clearance(scene, "standard-model") is not None,
                                 distance < 0.20)
                self.assertEqual(clearance(scene, "turn", rotation_clearance=0.20) is not None,
                                 distance < 0.20)

    def test_model_rotation_clearance_still_rejects_missing_coverage(self):
        for profile in ("conservative", "standard-model"):
            for missing in ("all", "front"):
                with self.subTest(profile=profile, missing=missing):
                    scene = make_scan()
                    if missing == "all":
                        scene.ranges = [math.inf] * 361
                    else:
                        scene.ranges[145:216] = [math.inf] * 71
                    self.assertEqual(configured_clearance(scene, profile),
                                     "insufficient scan coverage")

    def test_positive_and_negative_turns_publish_correct_sign_and_measure_progress(self):
        for sign in (1.0, -1.0):
            with self.subTest(sign=sign):
                state, commands, completed = movement_fragment("turn", sign * 0.75,
                                                               angle=sign * 0.30)
                self.assertEqual(commands, [(0.0, sign * 0.25)])
                self.assertAlmostEqual(state["progress"], 0.30)
                self.assertAlmostEqual(state["deadline"], 108.0)
                self.assertFalse(completed)
                _, _, completed = movement_fragment("turn", sign * 0.75,
                                                      angle=sign * 0.76)
                self.assertTrue(completed)

    def test_opposite_turn_feedback_is_rejected_for_either_requested_sign(self):
        for sign in (1.0, -1.0):
            with self.subTest(sign=sign), self.assertRaisesRegex(RuntimeError, "rotation"):
                movement_fragment("turn", sign * 0.75, angle=-sign * 0.04)

    def test_terminal_turn_speed_decreases_with_remaining_angle_and_records_actual_commands(self):
        for sign in (1.0, -1.0):
            for remaining, expected in ((0.20, 0.25), (0.12, 0.24),
                                        (0.06, 0.12), (0.03, 0.06), (0.001, 0.06)):
                with self.subTest(sign=sign, remaining=remaining):
                    state, commands, completed = movement_fragment(
                        "turn", sign * 0.75, angle=sign * (0.75 - remaining))
                    self.assertFalse(completed)
                    self.assertEqual(commands[0][0], 0.0)
                    self.assertAlmostEqual(commands[0][1], sign * expected)
                    sample = state["result"]["samples"][-1]
                    self.assertEqual(sample["command_v"], commands[0][0])
                    self.assertEqual(sample["command_w"], commands[0][1])
                    self.assertEqual(sample["elapsed"], 0.1)
                    self.assertEqual(state["result"]["speed"], sign * 0.25)
                    self.assertIn("nominal maximum", state["result"]["speed_semantics"])
                    self.assertAlmostEqual(state["deadline"], 108.0)

    def test_turn_at_or_past_target_does_not_publish_another_motion_command(self):
        for sign in (1.0, -1.0):
            for progress in (0.75, 0.76):
                with self.subTest(sign=sign, progress=progress):
                    state, commands, completed = movement_fragment(
                        "turn", sign * 0.75, angle=sign * progress)
                    self.assertTrue(completed)
                    self.assertEqual(commands, [])
                    self.assertNotIn("command_w", state["result"]["samples"][-1])

    def test_near_target_advance_and_reverse_keep_their_existing_speeds(self):
        for profile, advance_speed in (("conservative", 0.06), ("standard-model", 0.03)):
            for mode, sign, speed in (("advance", 1, advance_speed), ("reverse", -1, 0.03)):
                with self.subTest(profile=profile, mode=mode):
                    state, commands, completed = movement_fragment(
                        mode, 0.10, forward=sign * 0.099, profile=profile)
                    self.assertFalse(completed)
                    self.assertEqual(commands, [(sign * speed, 0.0)])
                    self.assertEqual(state["result"]["samples"][-1]["command_v"], sign * speed)

    def test_heading_hold_corrects_opposite_to_yaw_drift_and_caps_rate(self):
        for profile, speed in (("conservative", 0.06), ("standard-model", 0.03)):
            for angle, expected_w in ((0.0, 0.0), (0.01, -0.04), (-0.01, 0.04),
                                      (0.025, -0.10), (-0.025, 0.10),
                                      (0.15, -0.10), (-0.15, 0.10)):
                with self.subTest(profile=profile, angle=angle):
                    state, commands, completed = movement_fragment(
                        "advance", 0.10, angle=angle, forward=0.02,
                        profile=profile, hold_heading=True)
                    self.assertFalse(completed)
                    self.assertEqual(commands[0][0], speed)
                    self.assertAlmostEqual(commands[0][1], expected_w)
                    evidence = state["result"]
                    self.assertTrue(evidence["hold_heading"])
                    self.assertEqual(evidence["heading_hold_gain"], 4.0)
                    self.assertEqual(evidence["heading_hold_rate_cap"], 0.10)
                    self.assertAlmostEqual(evidence["samples"][-1]["command_w"], expected_w)

    def test_heading_hold_is_opt_in_and_rejected_for_other_modes(self):
        for mode in ("advance", "reverse"):
            state, commands, _ = movement_fragment(mode, 0.10, angle=0.05)
            self.assertFalse(state["result"]["hold_heading"])
            self.assertEqual(commands[0][1], 0.0)
        for mode in ("reverse", "turn"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "only with advance"):
                movement_fragment(mode, 0.10, hold_heading=True)
        _, commands, _ = movement_fragment("turn", -0.75, angle=-0.10)
        self.assertEqual(commands, [(0.0, -0.25)])

    def test_heading_hold_preserves_direction_bounds_and_stops_at_target(self):
        for feedback in ({"angle": 0.201}, {"angle": -0.201},
                         {"lateral": 0.041}, {"forward": -0.011}):
            with self.subTest(feedback=feedback), self.assertRaisesRegex(RuntimeError, "direction"):
                movement_fragment("advance", 0.10, hold_heading=True, **feedback)
        _, commands, completed = movement_fragment("advance", 0.10, forward=0.10,
                                                    angle=0.05, hold_heading=True)
        self.assertTrue(completed)
        self.assertEqual(commands, [])

    def test_heading_correction_checks_rear_sweep_using_selected_profile_clearance(self):
        for profile, blocked_distance, safe_distance in (("conservative", 0.24, 0.26),
                                                         ("standard-model", 0.19, 0.21)):
            scene = make_scan()
            scene.ranges[0] = blocked_distance
            self.assertIsNone(configured_clearance(scene, profile, mode="advance"))
            for angle in (0.01, -0.01):
                with self.subTest(profile=profile, angle=angle):
                    commands = []
                    with self.assertRaisesRegex(RuntimeError,
                                                "heading correction unsafe: obstacle inside rotation clearance"):
                        movement_fragment("advance", 0.10, angle=angle, forward=0.02,
                                          profile=profile, hold_heading=True, scan=scene,
                                          commands=commands)
                    self.assertEqual(commands, [])
            _, commands, _ = movement_fragment("advance", 0.10, forward=0.02,
                                                profile=profile, hold_heading=True, scan=scene)
            self.assertEqual(commands[0][1], 0.0)
            scene.ranges[0] = safe_distance
            _, commands, _ = movement_fragment("advance", 0.10, angle=0.01, forward=0.02,
                                                profile=profile, hold_heading=True, scan=scene)
            self.assertAlmostEqual(commands[0][1], -0.04)

    def test_signed_turn_bounds_and_positive_only_advance_are_enforced(self):
        for mode, amount in (("advance", -0.1), ("advance", 0.31), ("advance", 0.0),
                             ("turn", 0.0), ("turn", 2 * math.pi + 0.01),
                             ("turn", -2 * math.pi - 0.01), ("turn", math.nan),
                             ("turn", math.inf)):
            with self.subTest(mode=mode, amount=amount), self.assertRaises(ValueError):
                movement_fragment(mode, amount)
        for amount in (-2 * math.pi, 2 * math.pi):
            movement_fragment("turn", amount)
        state, commands, completed = movement_fragment("advance", 0.30, forward=0.10)
        self.assertEqual(commands, [(0.06, 0.0)])
        self.assertAlmostEqual(state["progress"], 0.10)
        self.assertFalse(completed)

    def test_clear_scene_and_live_finite_state_are_accepted(self):
        self.assertIsNone(clearance(make_scan(), "advance"))
        self.assertIsNone(clearance(make_scan(), "turn"))
        self.assertIsNone(fresh(make_live_state()))

    def test_reverse_is_bounded_slow_and_measures_rearward_progress_for_both_profiles(self):
        for profile in ("conservative", "standard-model"):
            with self.subTest(profile=profile):
                state, commands, completed = movement_fragment("reverse", 0.10,
                                                               forward=-0.04, profile=profile)
                self.assertEqual(commands, [(-0.03, 0.0)])
                self.assertEqual(state["result"]["speed"], -0.03)
                self.assertAlmostEqual(state["progress"], 0.04)
                self.assertAlmostEqual(state["deadline"], 100 + 0.10 / 0.03 + 5)
                self.assertFalse(completed)
                _, _, completed = movement_fragment("reverse", 0.15, forward=-0.151,
                                                      profile=profile)
                self.assertTrue(completed)
                for amount in (-0.10, 0.0, 0.151, math.nan, math.inf):
                    with self.subTest(amount=amount), self.assertRaises(ValueError):
                        movement_fragment("reverse", amount, profile=profile)

    def test_reverse_rejects_forward_feedback_yaw_and_lateral_deviation(self):
        for feedback in ({"forward": 0.011}, {"forward": -0.02, "angle": 0.201},
                         {"forward": -0.02, "lateral": 0.041}):
            with self.subTest(feedback=feedback), self.assertRaisesRegex(RuntimeError, "direction"):
                movement_fragment("reverse", 0.10, **feedback)

    def test_reverse_checks_rear_corridor_with_unchanged_profile_width_and_length(self):
        scene = make_scan()
        scene.ranges[180] = 0.20
        self.assertIsNone(clearance(scene, "reverse"))
        for width in (0.27, 0.18):
            for distance, blocked in ((0.33, True), (0.35, False)):
                with self.subTest(width=width, distance=distance):
                    scene = make_scan()
                    scene.ranges[0] = distance
                    self.assertEqual(clearance(scene, "reverse", half_width=width) is not None,
                                     blocked)
        for side_offset in (0.17, 0.19):
            scene = make_scan()
            scene.ranges[315] = side_offset * math.sqrt(2)  # rear left, 135 degrees
            self.assertIsNotNone(clearance(scene, "reverse"))
            self.assertEqual(clearance(scene, "reverse", half_width=0.18) is not None,
                             side_offset < 0.18)

    def test_reverse_requires_twenty_rear_returns_and_one_hundred_total(self):
        scene = make_scan()
        scene.ranges = [math.inf] * 361
        scene.ranges[90:190] = [2.0] * 100
        scene.ranges[:19] = [2.0] * 19
        self.assertIsNotNone(clearance(scene, "reverse"))
        scene.ranges[19] = 2.0
        self.assertIsNone(clearance(scene, "reverse"))
        scene.ranges[90:111] = [math.inf] * 21  # 99 total, still 20 rear
        self.assertIsNotNone(clearance(scene, "reverse"))
        scene = make_scan()
        scene.ranges[:36] = [math.inf] * 36
        scene.ranges[325:] = [math.inf] * 36
        self.assertIsNone(clearance(scene, "advance"))
        self.assertIsNotNone(clearance(scene, "reverse"))
        scene = make_scan()
        scene.ranges[145:216] = [math.inf] * 71
        self.assertIsNone(clearance(scene, "reverse"))
        self.assertIsNotNone(clearance(scene, "advance"))

    def test_close_rear_obstacle_allows_forward_but_blocks_turn(self):
        scan = make_scan()
        scan.ranges[0] = 0.20  # -pi, behind the robot
        self.assertIsNone(clearance(scan, "advance"))
        self.assertIsNotNone(clearance(scan, "turn"))

    def test_close_front_obstacle_blocks_forward(self):
        scan = make_scan()
        scan.ranges[180] = 0.20  # zero radians, in front of the robot
        self.assertIsNotNone(clearance(scan, "advance"))

    def test_missing_finite_or_forward_returns_reject_motion(self):
        for scenario in ("all infinite", "all NaN", "front missing"):
            with self.subTest(scenario=scenario):
                scan = make_scan()
                if scenario == "all infinite":
                    scan.ranges = [math.inf] * 361
                elif scenario == "all NaN":
                    scan.ranges = [math.nan] * 361
                else:
                    scan.ranges[145:216] = [math.inf] * 71
                self.assertIsNotNone(clearance(scan, "advance"))
                self.assertIsNotNone(clearance(scan, "turn"))

    def test_old_or_future_message_timestamps_are_rejected(self):
        for sensor in ("odom", "scan"):
            for offset in (-1, 1):
                with self.subTest(sensor=sensor, seconds=offset):
                    state = make_live_state()
                    getattr(state, sensor).header.stamp.sec += offset
                    self.assertIsNotNone(fresh(state))

    def test_missing_or_unreceived_sensor_data_is_rejected(self):
        for sensor in ("odom", "scan"):
            with self.subTest(sensor=sensor, failure="missing"):
                state = make_live_state()
                setattr(state, sensor, None)
                self.assertIsNotNone(fresh(state))
            with self.subTest(sensor=sensor, failure="receive timeout"):
                state = make_live_state()
                setattr(state, sensor + "_at", 99.0)
                self.assertIsNotNone(fresh(state))

    def test_nonfinite_pose_and_velocity_are_rejected(self):
        fields = ("odom.pose.pose.position.x", "odom.pose.pose.position.y",
                  "unwrapped_yaw", "odom.pose.pose.orientation.z",
                  "odom.twist.twist.linear.x", "odom.twist.twist.angular.z")
        for field in fields:
            for invalid in (math.nan, math.inf):
                with self.subTest(field=field, invalid=invalid):
                    state = make_live_state()
                    target = state
                    parts = field.split(".")
                    for part in parts[:-1]:
                        target = getattr(target, part)
                    setattr(target, parts[-1], invalid)
                    self.assertIsNotNone(fresh(state))

    def test_invalid_quaternion_or_uninitialized_yaw_is_rejected(self):
        for quaternion in ((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 2.0)):
            with self.subTest(quaternion=quaternion):
                state = make_live_state()
                state.odom.pose.pose.orientation = NS(**dict(zip("xyzw", quaternion)))
                self.assertIsNotNone(fresh(state))
        state = make_live_state()
        state.unwrapped_yaw = None
        self.assertIsNotNone(fresh(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
