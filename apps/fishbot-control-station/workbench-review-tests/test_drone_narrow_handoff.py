# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Earlier reference cuts separate mathematical and historical eligibility."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from scipy.interpolate import BSpline

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("narrow_fixtures", HERE/"test_drone_reference_stops.py")
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
source, reference, geometry = fixture.source, fixture.study, fixture.geometry
study = source.load("drone-narrow-handoff")


def record(y=0., receipt=10.):
    return {"order": 3, "knots": [0.,0.,0.,0.,1.,1.,1.,1.],
        "control_points": [[0.,y,1.5],[0.,y,1.5],[0.,y,1.5],[0.,y+.0001 if y else .05,1.5]],
        "start_sim_s": 10., "received_sim_s": receipt, "task_id": "fixture", "trajectory_id": 1}


def dataset(raw=None, next_received=10.3):
    raw = raw or record()
    window = source.primitives.restrict(raw, .8, source.curve, source.audit, source.LIMITS)
    window["source_curve"] = raw
    return {"archive_task_id": "fixture", "clock": "sim", "limits": source.LIMITS,
        "windows": [window, {"trajectory_id": 99, "received_sim_s": next_received}]}


def failure(at=10.4):
    return {"task_id": "fixture", "mode": "simulation", "failure_events": [{"simulation_s": at}]}


class NarrowHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = dataset()
        cls.result = study.run(cls.data, failure(), source.ROOT, fixture.NATIVE,
            trajectory_ids=[1], horizons=[.1,.2], max_iterations=1)

    def test_variant_identity_and_each_cut_preserves_its_own_reference_pvaj(self):
        rows = self.result["rows"]
        self.assertNotEqual(rows[0]["variant_id"], rows[1]["variant_id"])
        self.assertNotEqual(rows[0]["window"]["terminal_pvaj_xyz_columns"], rows[1]["window"]["terminal_pvaj_xyz_columns"])
        for row in rows:
            self.assertEqual(row["status"], "generated")
            candidate = row["result"]["candidate"]
            expected = np.asarray(row["window"]["terminal_pvaj_xyz_columns"])
            np.testing.assert_array_equal(candidate["request"]["initial_pva"], expected[:,:3])
            np.testing.assert_array_equal(candidate["request"]["initial_jerk"], expected[:,3])
            self.assertEqual(candidate["prefix_pieces"], row["window"]["pieces"])
            self.assertTrue(candidate["cut_c3_passed"])
            first = row["counterfactual_replay"]["scenarios"][0]["events"][0]["result"]
            self.assertEqual(first["plan_id"], row["variant_id"])
        optional=copy.deepcopy(rows[0]["result"]["candidate"]);optional["candidate_id"]=None
        fallback=reference.replay_cases(optional,self.result["context"],source.LIMITS,fixture.replay,
            source.audit,source.handoff,box=reference.NARROW_BOX)
        self.assertEqual(fallback["scenarios"][0]["events"][0]["result"]["plan_id"],str(optional["trajectory_id"]))

    def test_before_at_after_and_unknown_are_distinct(self):
        self.assertEqual([study.relative_to(t,10.) for t in [9.,10.,11.]], ["before","at","after"])
        self.assertEqual(study.relative_to(10.,None), "unknown")
        self.assertEqual(self.result["rows"][0]["timing"]["next_curve_received_sim_s"],10.3)
        self.assertEqual(self.result["rows"][0]["timing"]["relative_to_recorded_failure"],"before")
        self.assertIn("unverified",self.result["rows"][0]["timing"]["online_admission"])

    def test_failure_report_missing_or_partial_never_invents_a_boundary(self):
        for report in [{}, {**failure(),"failure_events":None}, {**failure(),"task_id":"other"},
            {**failure(),"failure_events":[None,{"simulation_s":10.4}]}]:
            result = study.failure_evidence(report, "fixture")
            self.assertEqual(result["status"],"unverified")
            self.assertIsNone(result["simulation_s"])

    def test_receipt_phase_and_actual_truncated_duration(self):
        data = dataset(record(receipt=10.8),next_received=11.1)
        result = study.run(data,failure(11.2),source.ROOT,fixture.NATIVE,
            trajectory_ids=[1],horizons=[.8],max_iterations=1)
        window = result["rows"][0]["window"]
        self.assertAlmostEqual(window["duration_s"],.2)
        self.assertAlmostEqual(window["window_end_sim_s"],11.)
        self.assertAlmostEqual(result["rows"][0]["timing"]["cut_sim_s"],11.)

    def test_cut_at_original_cubic_knot_keeps_left_limit_jerk(self):
        knots=[-3.,-2.,-1.,0.,1.,2.,3.,4.,5.]
        points=[[0.,0.,1.],[.1,.01,1.],[.3,.01,1.],[.31,-.01,1.],[.6,0.,1.]]
        raw={"order":3,"knots":knots,"control_points":points,"start_sim_s":20.,"received_sim_s":20.75,
             "task_id":"fixture","trajectory_id":1}
        window=source.primitives.restrict(raw,.25,source.curve,source.audit,source.LIMITS)
        spline=BSpline(knots,points,3)
        left=np.asarray(window["terminal_pvaj_xyz_columns"])[:,3]
        np.testing.assert_allclose(left,spline(.875,nu=3),atol=1e-12)
        self.assertGreater(np.linalg.norm(left-spline(1.,nu=3)),.1)

    def test_optimistic_necessary_boundary_and_outside_are_not_joint_viability(self):
        box=[[-10.,-10.,0.],[15.,2.,2.2]]
        for y,status in [(1.5,"not_ruled_out"),(1.50001,"necessary_reject"),(2.01,"necessary_reject")]:
            result=geometry.tracking.stopping_necessary([0.,y,1.5],[0.,1.,0.],box,1.)
            self.assertEqual(result["status"],status)
            self.assertEqual(result["joint_viability"],"not_proven")

    def test_narrow_replay_uses_explicit_box_for_complete_prefix(self):
        row=fixture.ReferenceStopTests().candidate()
        context={"task_id":"fixture","scene_revision":"static-test","clock_id":"sim","frame_id":"scene_enu_m"}
        # Tail X starts inside, historical prefix X starts outside this box.
        box=[[.02,-10.,0.],[15.,10.,2.2]]
        report=reference.replay_cases(row,context,source.LIMITS,fixture.replay,source.audit,source.handoff,box=box)
        first=report["scenarios"][0]["events"][0]["result"]
        self.assertEqual(report["box_fixture"],box)
        self.assertFalse(first["candidate_accepted"])
        self.assertIsNone(first["selected_reference_pva"])

    def test_planning_inset_limit_is_not_reported_as_hard_box_necessity(self):
        result=study.run(dataset(record(y=2.029)),failure(),source.ROOT,fixture.NATIVE,
            trajectory_ids=[1],horizons=[.1],max_iterations=1)
        row=result["rows"][0]
        self.assertEqual(row["necessary"]["status"],"not_ruled_out")
        self.assertEqual(row["reason"],"input_outside_planning_box")

    def test_bad_optional_horizon_and_bad_source_item_skip_only_their_rows(self):
        data=copy.deepcopy(self.data);data["windows"].append(None)
        result=study.run(data,{},source.ROOT,fixture.NATIVE,trajectory_ids=[999,1],
            horizons=[float('nan'),-.1,.1],max_iterations=1)
        self.assertEqual(result["rows"][-1]["status"],"generated")
        self.assertEqual(result["rows"][-1]["timing"]["relative_to_recorded_failure"],"unknown")
        json.dumps(result,allow_nan=False)

    def test_narrow_box_alone_cannot_count_a_failed_full_contract_as_passed(self):
        names=("drone-trajectory-primitives","drone-reference-stops","drone-stop-geometry",
               "drone-stop-candidates","drone-stop-time-study","drone-committed-replay")
        modules={name:study.load(name) for name in names}
        original=modules["drone-stop-time-study"].compose
        def failed_contract(*args,**kwargs):
            result=original(*args,**kwargs)
            result["candidate"]["full_math_gate"].update(passed=False,failed_checks=["tail_axis_knots"])
            return result
        with patch.object(study,"load",side_effect=lambda name:modules[name]), \
                patch.object(modules["drone-stop-time-study"],"compose",side_effect=failed_contract):
            result=study.run(self.data,failure(),source.ROOT,fixture.NATIVE,
                trajectory_ids=[1],horizons=[.1],max_iterations=1)
        self.assertTrue(result["rows"][0]["result"]["narrow_box_gate"]["passed"])
        self.assertEqual(result["summary"]["narrow_math_passed"],0)
        self.assertEqual(result["summary"]["narrow_passed_before_both_recorded_events"],0)


if __name__ == "__main__":
    unittest.main()
