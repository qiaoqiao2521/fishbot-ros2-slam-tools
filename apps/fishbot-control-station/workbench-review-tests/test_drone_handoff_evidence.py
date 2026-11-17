# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Legacy sender references never establish downstream trajectory adoption."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


TOOLS = Path(__file__).parents[1]/"workbench-tools"
spec = importlib.util.spec_from_file_location("handoff_evidence", TOOLS/"drone-handoff-evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def curve(**changes):
    return {"task_id": "task", "goal_id": "goal-a", "trajectory_id": 3,
        "start_sim_s": 10., "received_sim_s": 10.1, "duration_s": 2., "source_line": 7, **changes}


def telemetry(**reference_changes):
    return {"simulation_s": 10.4, "source_line": 12,
        "reference": {"task_id": "task", "goal_id": "goal-a", "trajectory_id": 3,
            "mode": "position_velocity_acceleration", "simulation_s": 10.3,
            "command_stamp_sim_s": 10.2, "position": [1., 2., 1.5],
            "velocity": [.5, .2, 0.], "acceleration": [0., 0., 0.], **reference_changes}}


class HandoffEvidenceTests(unittest.TestCase):
    def analyze(self, curves=None, snapshots=None, request=None, report=None):
        return evidence.analyze({"id": "task"} if request is None else request,
            {"task_id": "task", "status": "completed"} if report is None else report,
            [curve()] if curves is None else curves,
            [telemetry()] if snapshots is None else snapshots)

    def assert_no_adoption(self, result):
        self.assertEqual(result["summary"]["candidate_adoptions_proven"], 0)
        self.assertEqual(result["execution_admission_in_this_audit"], "not_performed")
        self.assertEqual(result["dynamic_closed_loop"], "not_passed")
        for row in result["rows"]:
            self.assertEqual(row["candidate_adoption"], "unproven")
            for field in ("full_curve_audit_transaction", "px4_ingress_witness", "controller_consumption_witness"):
                self.assertEqual(row[field], "unrecorded_by_legacy_streams")

    def test_valid_sender_association_is_a_post_rpc_snapshot_without_adoption(self):
        result = self.analyze()
        self.assertEqual(result["summary"]["unique_task_attributed_curves"], 1)
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
        self.assertEqual(result["summary"]["unassociated_reference_reasons"], {})
        row = result["rows"][0]
        self.assertEqual(row["curve_source_line"], 7)
        reference = row["post_rpc_reference_snapshots"][0]
        self.assertEqual(reference["telemetry_source_line"], 12)
        self.assertEqual(reference["command_stamp_sim_s"], 10.2)
        self.assertEqual(reference["reference_sampled_sim_s"], 10.3)
        self.assertEqual(reference["recorded_sim_s"], 10.4)
        self.assertIn("not return time", reference["scope"])
        self.assertIn("not carried by native Bspline", row["curve_identity_scope"])
        self.assert_no_adoption(result)

    def test_same_trajectory_number_does_not_cross_task_or_goal(self):
        curves = [curve(), curve(task_id="another-task", source_line=8),
            curve(goal_id="goal-b", source_line=9)]
        snapshots = [telemetry(), telemetry(task_id="another-task"),
            telemetry(goal_id="missing-goal"), telemetry(goal_id="goal-b")]
        result = self.analyze(curves, snapshots)
        self.assertEqual([len(row["post_rpc_reference_snapshots"]) for row in result["rows"]], [1, 0, 1])
        self.assertEqual(result["rows"][1]["local_identity_issues"], ["curve_task_goal_identity_unattributed"])
        self.assertEqual(result["summary"]["unassociated_reference_reasons"], {
            "reference_task_unattributed": 1, "reference_curve_missing_or_ambiguous": 1})
        self.assert_no_adoption(result)

    def test_duplicate_curve_key_is_ambiguous_even_if_only_one_receipt_time_is_valid(self):
        for duplicate in (curve(source_line=8), curve(received_sim_s=99., source_line=8)):
            with self.subTest(duplicate=duplicate):
                result = self.analyze([duplicate, curve()])
                self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 0)
                self.assertEqual(result["summary"]["unique_task_attributed_curves"], 0)
                self.assertEqual(result["summary"]["unassociated_reference_reasons"], {"reference_curve_missing_or_ambiguous": 1})
                self.assertTrue(all(row["local_identity_issues"] == ["curve_identity_ambiguous"] for row in result["rows"]))
                self.assert_no_adoption(result)

    def test_trajectory_identity_requires_a_nonnegative_integer_without_backfill(self):
        for invalid in (None, "3", 3., True, -1):
            with self.subTest(trajectory_id=invalid):
                result = self.analyze(snapshots=[telemetry(trajectory_id=invalid), telemetry()])
                self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
                self.assertEqual(result["summary"]["unassociated_reference_reasons"], {"reference_identity_missing": 1})
        zero = self.analyze([curve(trajectory_id=0)], [telemetry(trajectory_id=0)])
        self.assertEqual(zero["summary"]["associated_PVA_reference_snapshots"], 1)

    def test_bad_identity_curve_does_not_poison_later_valid_curve(self):
        result = self.analyze([curve(goal_id=None, source_line=6), curve()], [telemetry()])
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
        self.assertTrue(result["rows"][0]["local_identity_issues"])
        self.assertEqual(result["rows"][0]["post_rpc_reference_snapshots"], [])
        self.assertEqual(len(result["rows"][1]["post_rpc_reference_snapshots"]), 1)

    def test_invalid_reference_order_receipt_and_curve_domain_only_reject_bad_snapshot(self):
        cases = []
        early_record = telemetry(); early_record["simulation_s"] = 10.25
        early_command_record = telemetry(command_stamp_sim_s=10.5)
        before_curve = telemetry(command_stamp_sim_s=9.99)
        before_receipt = telemetry(simulation_s=10.05, command_stamp_sim_s=10.)
        early_receipt_record = telemetry(simulation_s=10.03, command_stamp_sim_s=10.)
        early_receipt_record["simulation_s"] = 10.05
        at_end = telemetry(simulation_s=12., command_stamp_sim_s=11.9); at_end["simulation_s"] = 12.1
        after_end = telemetry(simulation_s=12.1, command_stamp_sim_s=12.); after_end["simulation_s"] = 12.2
        nan_record = telemetry(); nan_record["simulation_s"] = float("nan")
        cases.extend([early_record, early_command_record, before_curve, before_receipt, early_receipt_record,
            at_end, after_end, nan_record, telemetry(simulation_s=float("nan")),
            telemetry(command_stamp_sim_s=float("nan"))])
        for bad in cases:
            with self.subTest(bad=bad):
                result = self.analyze(snapshots=[bad, telemetry()])
                self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
                self.assertEqual(result["summary"]["unassociated_reference_reasons"], {"reference_time_unqualified": 1})
                self.assert_no_adoption(result)

    def test_nonfinite_or_invalid_curve_times_do_not_authorize_a_reference(self):
        for field, value in (("start_sim_s", float("nan")), ("received_sim_s", float("inf")),
                ("received_sim_s", 10.5), ("duration_s", 0.), ("duration_s", -1.), ("duration_s", None)):
            with self.subTest(field=field, value=value):
                result = self.analyze([curve(**{field: value})])
                self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 0)
                self.assertEqual(result["summary"]["unassociated_reference_reasons"], {"reference_time_unqualified": 1})
                self.assert_no_adoption(result)
                json.dumps(result, allow_nan=False)

    def test_nan_and_malformed_pva_are_local_rejections(self):
        for field, value in (("position", [float("nan"), 0., 0.]), ("velocity", [float("inf"), 0., 0.]),
                ("acceleration", [0., 0.]), ("acceleration", None), ("velocity", [True, 0., 0.]),
                ("position", ["1", 0., 0.]), ("position", (1., 2., 3.))):
            with self.subTest(field=field, value=value):
                result = self.analyze(snapshots=[telemetry(**{field: value}), telemetry()])
                self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
                self.assertEqual(result["summary"]["unassociated_reference_reasons"], {"reference_PVA_unqualified": 1})
                self.assert_no_adoption(result)
                json.dumps(result, allow_nan=False)

    def test_position_reference_does_not_become_pva_even_with_supplied_velocity(self):
        for mode in ("position", "velocity", "hold", None):
            with self.subTest(mode=mode):
                result = self.analyze(snapshots=[telemetry(mode=mode)])
                self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 0)
                self.assertEqual(result["summary"]["unassociated_reference_reasons"], {"reference_PVA_unqualified": 1})
                self.assert_no_adoption(result)

    def test_large_json_integer_is_a_local_gap_not_a_batch_failure(self):
        huge = 10**400
        for bad in (telemetry(simulation_s=huge), telemetry(trajectory_id=huge),
                telemetry(position=[huge, 0., 0.])):
            with self.subTest(bad=bad):
                result = self.analyze(snapshots=[bad, telemetry()])
                self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
                self.assertEqual(sum(result["summary"]["unassociated_reference_reasons"].values()), 1)
                json.dumps(result, allow_nan=False)
        result = self.analyze(curves=[curve(trajectory_id=huge), curve()])
        self.assertEqual(result["summary"]["unique_task_attributed_curves"], 1)
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)

    def test_malformed_historical_fields_do_not_break_json_or_turn_into_booleans(self):
        result = self.analyze(report={"task_id": "task", "status": float("nan"),
            "landed": [True], "disarmed": 1})
        self.assertEqual(result["historical_task_report"], {})
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
        json.dumps(result, allow_nan=False)

    def test_claimed_passed_adopted_and_ack_fields_do_not_upgrade_sender_evidence(self):
        claims = {"passed": True, "adopted": True, "ACK": True, "candidate_adoption": "adopted",
            "px4_ingress_witness": "ACK", "controller_consumption_witness": "ACK",
            "full_curve_audit_transaction": {"passed": True}}
        snapshot = telemetry(**claims)
        snapshot.update(claims)
        report = {"task_id": "task", "status": "passed", "landed": True, "disarmed": True,
            "candidate_adoptions_proven": 99, **claims}
        result = self.analyze([curve(**claims)], [snapshot], report=report)
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
        self.assertEqual(result["historical_task_report"], {"status": "passed", "landed": True, "disarmed": True})
        self.assert_no_adoption(result)

    def test_unmatched_historical_report_is_not_backfilled_from_request(self):
        result = self.analyze(report={"task_id": "other-task", "status": "passed", "landed": True})
        self.assertFalse(result["historical_report_identity_matched"])
        self.assertEqual(result["historical_task_report"], {})
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
        self.assert_no_adoption(result)

    def test_analyze_keeps_inputs_immutable_and_historical_output_detached(self):
        request = {"id": "task", "metadata": {"note": ["original"]}}
        report = {"task_id": "task", "status": "completed", "metadata": {"legacy": ["completed"]}}
        curves, snapshots = [curve()], [telemetry()]
        before = copy.deepcopy((request, report, curves, snapshots))
        result = evidence.analyze(request, report, curves, snapshots)
        self.assertEqual((request, report, curves, snapshots), before)
        result["historical_task_report"]["status"] = "output-only"
        result["rows"][0]["post_rpc_reference_snapshots"][0]["recorded_sim_s"] = 99.
        self.assertEqual((request, report, curves, snapshots), before)


class HandoffEvidenceRunTests(unittest.TestCase):
    def contents(self, directory):
        return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*") if path.is_file()}

    def test_missing_optional_report_and_streams_warn_without_creating_or_changing_sources(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            (directory/"request.json").write_text(json.dumps({"id": "task"}))
            before = self.contents(directory)
            result = evidence.run(directory)
            self.assertEqual(self.contents(directory), before)
        self.assertEqual(result["summary"]["curve_records"], 0)
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 0)
        for filename in ("report.json", "trajectory-events.jsonl", "telemetry.jsonl"):
            self.assertTrue(any(filename in warning for warning in result["warnings"]))
        self.assertEqual(result["summary"]["candidate_adoptions_proven"], 0)

    def test_unreadable_utf8_stream_is_reported_without_losing_curve_inventory(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            (directory/"ego").mkdir()
            (directory/"request.json").write_text(json.dumps({"id": "task"}))
            (directory/"report.json").write_text(json.dumps({"task_id": "task", "status": "failed"}))
            (directory/"ego/trajectory-events.jsonl").write_text(json.dumps(curve())+"\n")
            (directory/"telemetry.jsonl").write_bytes(b"\xff\n")
            before = self.contents(directory)
            result = evidence.run(directory)
            self.assertEqual(self.contents(directory), before)
        self.assertEqual(result["summary"]["curve_records"], 1)
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 0)
        self.assertTrue(any("telemetry.jsonl" in warning for warning in result["warnings"]))

    def test_bad_json_and_nonobjects_are_skipped_and_later_pva_still_associates(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            (directory/"ego").mkdir()
            (directory/"request.json").write_text(json.dumps({"id": "task"}))
            (directory/"report.json").write_text("[]\n")
            curves = ["{broken", "[]", json.dumps({"trajectory_id": "3"}), json.dumps(curve(source_line=999))]
            snapshots = ["not-json", "null", json.dumps({"reference": "position"}),
                json.dumps(telemetry()), json.dumps(telemetry(mode="position"))]
            (directory/"ego/trajectory-events.jsonl").write_text("\n".join(curves)+"\n")
            (directory/"telemetry.jsonl").write_text("\n".join(snapshots)+"\n")
            before = self.contents(directory)
            result = evidence.run(directory)
            self.assertEqual(self.contents(directory), before)
        self.assertEqual(result["summary"]["curve_records"], 2)
        self.assertEqual(result["summary"]["unique_task_attributed_curves"], 1)
        self.assertEqual(result["summary"]["associated_PVA_reference_snapshots"], 1)
        self.assertEqual(result["summary"]["unassociated_reference_reasons"], {"reference_PVA_unqualified": 1})
        associated = result["rows"][1]["post_rpc_reference_snapshots"][0]
        self.assertEqual(result["rows"][1]["curve_source_line"], 4)
        self.assertEqual(associated["telemetry_source_line"], 4)
        self.assertEqual(len(result["warnings"]), 5)
        self.assertEqual(result["summary"]["candidate_adoptions_proven"], 0)
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
