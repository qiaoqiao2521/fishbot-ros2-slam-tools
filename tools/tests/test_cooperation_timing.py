"""Behavioral fixtures for historical timing import; no ROS or physical execution."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.cooperation_timing import import_run, public_report


class TimingImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / "raw"
        self.output = self.root / "derived"
        (self.run / "order-1/observer").mkdir(parents=True)
        (self.run / "runtime").mkdir()
        self.write("declaration.json", {"scene_profile": {"vehicle": "jackal_j100", "sensors": "lidar3d"}, "task_timeout_wall_s": 360})
        self.write("manifest-used.json", {"station_perception": {"mode": "ideal"}, "private": "/home/example/secret"})
        self.write("result.json", {"run_id": "run", "passed": False, "orders": [{
            "id": "B", "task_id": "task", "episode_id": "episode", "task_verdict": "failed",
            "original_score_passed": False, "original_k_passed": False, "failure_reason": "original failure stays",
            "carrying_nav_uuid": "delivery", "native_route": [
                {"uuid": "egress", "label": "DriveOnHeading", "active_wall_time": 101, "success_wall_time": 110, "terminal_status": 4},
                {"uuid": "delivery", "label": "Nav2", "active_wall_time": 112, "success_wall_time": 120, "terminal_status": 4}],
            "delivery_route_budget": {"receipt": {"started_wall_time": 111, "finished_wall_time": 122, "elapsed_wall_s": 11.01,
                "remaining_wall_s": 108.99, "budget_wall_s": 120, "clock": "monotonic_wall", "boundary": "after_egress", "within_budget": True}},
            "metrics": {"elapsed_wall_s": 25}}]})
        self.write("order-1/markers.json", {"events": [
            {"kind": "full_started", "wall_time": 100, "task_id": "task", "episode_id": "episode"},
            {"kind": "full_finished", "wall_time": 125, "task_id": "task", "episode_id": "episode"}]})
        self.write("runtime/loop-timing.json", {"stages": {"mj_step": {"count": 8, "max_s": .02}}})

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, data):
        (self.run / name).write_text(json.dumps(data))

    def http(self, wall, stage, task="task", episode="episode"):
        return {"topic": "http_state", "received_wall_time": wall, "received_monotonic": wall - 80,
                "payload": {"task": {"id": task, "stage": stage, "message": "not a stage timestamp"},
                            "episode_id": episode, "physics": {"stamp": wall - 90}}}

    def physics(self, wall, stamp, seq, episode="episode"):
        return {"topic": "physics", "received_wall_time": wall, "payload": {
            "episode_id": episode, "stamp": stamp, "sequence": seq, "physics_hz": 50, "car_hold": True,
            "car": {"position": [1, 2, 0], "quaternion_wxyz": [1, 0, 0, 0]}, "cargo": {"position": [1, 2, .2]}}}

    def rows(self, items):
        path = self.run / "order-1/observer/observer.jsonl"
        path.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in items) + "\n")
        return path

    def test_keeps_original_verdict_and_separates_route_from_egress(self):
        self.rows([self.http(100, "arm_load"), self.http(110, "egress"), self.http(122, "done")])
        report = import_run(self.run, self.output)
        case = report["cases"][0]
        self.assertFalse(report["new_execution"])
        self.assertFalse(report["rescored"])
        self.assertFalse(report["original_run_passed"])
        self.assertEqual(case["original_verdict"]["failure_reason"], "original failure stays")
        native = [s for s in case["spans"] if s["layer"] == "native"]
        self.assertIsNone(native[0]["parent_id"])
        self.assertEqual(native[1]["parent_id"], "route")
        route = next(s for s in case["spans"] if s["id"] == "route")
        self.assertEqual(route["duration_s"], 11.01)  # Original monotonic value, not wall subtraction.
        self.assertFalse(native[1]["consumption_ack"])
        self.assertEqual(sum(s["duration_s"] for s in case["spans"] if s.get("parent_id") == "route"), 11)

    def test_report_label_comes_from_selected_chassis_and_executed_orders(self):
        self.rows([])
        self.write('declaration.json', {'scene_id': 'f1-line-side-open', 'scene_profile': {'vehicle': 'robot_base_mecanum', 'sensors': 'planar'}})
        report = import_run(self.run, self.output)
        self.assertEqual(report['label'], '配送记录 · 麦克纳姆 B')
        self.assertFalse(report['original_run_passed'])
        self.assertNotIn('J100', public_report(report)['label'])
        self.assertEqual(public_report(report)['cases'][0]['scene_id'], 'f1-line-side-open')

    def test_http_boundaries_are_uncertain_and_last_span_censored(self):
        self.rows([self.http(100, "load"), self.http(104, "load"), self.http(105, "egress"),
                   self.http(109, "egress"), self.http(108, "wrong_out_of_order"), self.http(110, "other", task="other")])
        case = import_run(self.run, self.output)["cases"][0]
        phases = [s for s in case["spans"] if s["layer"] == "observed_stage"]
        self.assertEqual([s["label"] for s in phases], ["load", "egress"])
        self.assertEqual(phases[0]["end_boundary_wall_s"], [104, 105])
        self.assertEqual(phases[1]["start_boundary_wall_s"], [104, 105])
        self.assertEqual(phases[1]["start_monotonic_s"], 25)
        self.assertEqual(phases[1]["end_wall_s"], 109)
        self.assertTrue(phases[1]["right_censored"])
        self.assertEqual(case["import_status"], "partial")

    def test_sequence_gaps_survive_downsampling_without_cross_episode_join(self):
        self.rows([self.http(100, "load"), self.physics(100, 10, 1), self.physics(100.02, 10.02, 2),
                   self.physics(100.03, 0, 1, episode="foreign"), self.physics(100.08, 10.08, 5),
                   self.physics(100.1, 10.1, 6), self.physics(100.12, 10.12, 7)])
        case = import_run(self.run, self.output)["cases"][0]
        self.assertEqual(case["sampling"]["missing_samples"], 2)
        self.assertEqual(case["sampling"]["foreign_episode_records"], 1)
        points = [json.loads(line) for line in (self.output / case["trajectory"]["stream_ref"]).read_text().splitlines()]
        self.assertEqual([p["sequence"] for p in points], [1, 5, 6])
        self.assertTrue(points[1]["gap_before"])
        self.assertFalse(case["trajectory"]["score_input"])

    def test_integration_frequency_is_not_observer_publication_frequency(self):
        rows = [self.physics(100 + i * .02, 10 + i * .02, i + 1) for i in range(6)]
        for row in rows:
            row["payload"]["physics_hz"] = 2500
        self.rows(rows)
        case = import_run(self.run, self.output)["cases"][0]
        self.assertEqual(case["sampling"]["gaps"], [])
        self.assertEqual(case["trajectory"]["sample_count"], 2)

    def test_bad_optional_records_do_not_erase_other_cases_or_originals(self):
        raw = self.rows(["broken json", self.http(100, "load"), self.physics(100, 10, 1),
                         self.physics(100.1, 10.1, 6)])
        before = raw.read_bytes()
        (self.run / "runtime/loop-timing.json").unlink()
        report = import_run(self.run, self.output)
        self.assertEqual(raw.read_bytes(), before)
        self.assertEqual(report["cases"][0]["sampling"]["malformed_records"], 1)
        self.assertEqual(report["cases"][0]["import_status"], "partial")
        self.assertTrue(report["warnings"])
        self.assertEqual(report["loop_diagnostics"]["stages"], {})

    def test_reimport_upserts_index_and_rebuilds_stream_without_duplicates(self):
        self.rows([self.http(100, "load"), self.physics(100, 10, 1)])
        import_run(self.run, self.output)
        self.rows([self.http(100, "edited_load"), self.physics(100, 10, 1), self.physics(100.1, 10.1, 6)])
        report = import_run(self.run, self.output)
        with sqlite3.connect(self.output / "timing.sqlite3") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM eval_runs").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT sample_count FROM eval_trajectories").fetchone()[0], 2)
            self.assertIn("edited_load", "".join(r[0] for r in db.execute("SELECT details_json FROM eval_stage_spans")))
        self.assertEqual(report["cases"][0]["trajectory"]["sample_count"], 2)

    def test_public_projection_keeps_verdict_but_excludes_paths_and_raw_errors(self):
        self.rows([self.http(100, "load"), self.physics(100, 10, 1)])
        report = import_run(self.run, self.output)
        report["cases"][0]["original_verdict"]["failure_reason"] = "/home/example/secret"
        report["cases"][0]["spans"][0]["goal_pose"] = {"path": "/home/example/secret"}
        report["cases"][0]["private_manifest"] = "/home/example/secret"
        public = public_report(report)
        self.assertNotIn("/home/", json.dumps(public))
        self.assertFalse(public["cases"][0]["original_verdict"]["original_score_passed"])
        self.assertEqual(public["cases"][0]["observation_mode"], "ideal")


if __name__ == "__main__":
    unittest.main()
