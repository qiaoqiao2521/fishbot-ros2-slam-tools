# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""A late curve keeps its original phase; wall timing includes owned lifecycle."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np


TOOLS=Path(__file__).parents[1]/"workbench-tools"
spec=importlib.util.spec_from_file_location("handoff_timing",TOOLS/"drone-handoff-timing.py")
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)
ROOT=Path.home()/"dev/ros2/projects/drone"
NATIVE=Path.home()/".cache/ros2-drone/minco-s4-knots/minco_s4_knots"
BOX=[[-10.,-10.,0.],[15.,2.03,2.2]]
LIMITS={"speed":1.8,"acceleration":1.,"ceiling":2.2,"local_target_tolerance":.3}


@unittest.skipUnless(NATIVE.exists(),"existing offline S4 inner-point executable unavailable")
class HandoffTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit,cls.handoff=study.reanchor.qualification.committed.reuse(ROOT)
        geometry=study.reanchor.geometry
        seed=study.reanchor.seed_request([1.,.04,1.5],[1.,.2,0.],study.reanchor.hypotheses()[0],BOX,cls.handoff)
        request=geometry.geometry_request(seed,[5.,2.,.4,.2,.5,.85],y_inner=True)
        cls.candidate=geometry.tracking.audit_axis_request(request,BOX,LIMITS,NATIVE,cls.audit)
        cls.candidate["axis_knot_contract"]=geometry.audit_axis_knots(cls.candidate["native"],request,cls.audit)
        cls.cases={c["name"]:c for c in study.late_submissions(cls.candidate,"fixture",30.,BOX,LIMITS,cls.audit,cls.handoff)["cases"]}

    def source(self):
        return {"archive_task_id":"fixture","rows":[{"variant_id":"reference-7-h0.05",
            "profile":{"name":"zero_A_J"},"conditional_math_passed":True,"boundary_request":self.candidate["request"],
            "hard_box":BOX,"hard_limits":LIMITS,"input":{"scope":"synthetic fixture only"},"start_sim_s":30.}]}

    def test_phase_matched_late_submission_preserves_original_start(self):
        self.assertTrue(self.candidate["audit"]["passed"])
        self.assertTrue(self.candidate["axis_knot_contract"]["passed"])
        correct=self.cases["late_current_phase"]
        self.assertTrue(correct["result"]["candidate_accepted"])
        self.assertEqual(correct["selected_original_start_sim_s"],30.)
        self.assertEqual(correct["original_start_sim_s"],30.)
        self.assertEqual(correct["now_sim_s"],30.2)
        stale=self.cases["late_old_head"]
        self.assertFalse(stale["result"]["candidate_accepted"])
        self.assertIn("handoff_state_mismatch",stale["result"]["candidate_rejections"])
        self.assertIsNone(stale["selected_original_start_sim_s"])

    def test_original_end_is_an_exclusive_admission_boundary(self):
        before=self.cases["before_original_end"]
        self.assertTrue(before["result"]["candidate_accepted"])
        end=30.+self.handoff.duration(self.candidate["native"])
        self.assertLess(before["now_sim_s"],end)
        for name in ("at_original_end","after_original_end"):
            row=self.cases[name]
            self.assertFalse(row["result"]["candidate_accepted"])
            self.assertIn("trajectory_not_current",row["result"]["candidate_rejections"])

    def test_wall_elapsed_does_not_advance_paused_sim_phase(self):
        row=self.cases["wall_elapsed_sim_paused"]
        self.assertEqual(row["offline_wall_elapsed_s"],100.)
        self.assertEqual(row["now_sim_s"],row["original_start_sim_s"])
        self.assertTrue(row["result"]["candidate_accepted"])
        np.testing.assert_allclose(row["result"]["selected_reference_pva"],self.handoff.pva(self.candidate["native"],0.),rtol=0,atol=1e-12)

    def test_causal_cv_propagation_is_not_substituted_for_curve_phase_or_measured_a(self):
        row=self.cases["late_CV_model"];head=np.asarray(self.candidate["request"]["initial_pva"])
        actual=np.asarray(row["observed_pva_fixture"])
        np.testing.assert_allclose(actual[:,0],head[:,0]+.2*head[:,1],atol=1e-12)
        np.testing.assert_array_equal(actual[:,1],head[:,1])
        np.testing.assert_array_equal(actual[:,2],[0.,0.,0.])
        self.assertIn("not measured",row["state_scope"])
        self.assertFalse(row["result"]["candidate_accepted"])
        self.assertIn("handoff_state_mismatch",row["result"]["candidate_rejections"])

    def test_late_input_and_map_gaps_are_separate_rejections(self):
        unknown=self.cases["late_A_unknown"]["result"]
        self.assertEqual(unknown["reason"],"invalid_clock_or_state")
        for name,reason in (("late_stale_map","map_stale_or_future"),
                ("late_terminal_window_missing","map_prediction_horizon_unverified")):
            result=self.cases[name]["result"]
            self.assertFalse(result["candidate_accepted"])
            self.assertIn(reason,result["candidate_rejections"])

    def test_benchmark_wall_includes_session_enter_and_close(self):
        clock=[0.]
        def search(*args,**kwargs):
            clock[0]+=2.
            return {"status":"audited","candidate":copy.deepcopy(self.candidate),"optimizer":{"success":True}}
        class Session:
            def __init__(self,*_):self.process=self
            def __enter__(self):clock[0]+=3.;return self
            def __exit__(self,*_):clock[0]+=4.
            def exchange(self,*_):raise RuntimeError("mock search should not invoke transport")
            def poll(self):return 0
        with patch.object(study.reanchor.geometry,"search",side_effect=search), \
                patch.object(study.session_module,"NativeSession",Session), \
                patch.object(study.time,"perf_counter",side_effect=lambda:clock[0]):
            result=study.run(self.source(),ROOT,NATIVE,repetitions=1)
        self.assertEqual([r["wall_s"] for r in result["rows"]],[2.,9.])
        self.assertTrue(all(result["rows"][1]["paired_equivalence"].values()))
        self.assertTrue(result["rows"][1]["owned_process_exited"])
        self.assertEqual(result["execution_admission"],"not_performed")

    def test_optional_session_failure_keeps_independent_oneshot_result(self):
        resolved={"status":"audited","candidate":copy.deepcopy(self.candidate),"optimizer":{"success":True}}
        with patch.object(study.reanchor.geometry,"search",return_value=resolved), \
                patch.object(study.session_module,"NativeSession",side_effect=ValueError("worker unavailable")):
            result=study.run(self.source(),ROOT,NATIVE,repetitions=2)
        self.assertEqual([r["status"] for r in result["rows"]],["audited","unscored","audited","unscored"])
        self.assertEqual(result["wall_summary"]["per_evaluation"]["samples"],2)
        self.assertNotIn("per_search",result["wall_summary"])
        self.assertNotIn("late_submissions",result)

    def test_missing_ambiguous_or_bad_source_is_unscored_without_taking_first(self):
        duplicate=self.source();duplicate["rows"]*=2
        for source in (None,{"rows":None},duplicate):
            result=study.run(source,ROOT,NATIVE,repetitions=1)
            self.assertEqual(result["status"],"unscored")
        source=self.source();source["rows"].insert(0,{"variant_id":"reference-7-h0.05","profile":None})
        with patch.object(study.reanchor.geometry,"search",return_value={"status":"unscored"}):
            result=study.run(source,ROOT,Path('/missing-native'),repetitions=1)
        self.assertEqual(len(result["rows"]),2)


if __name__=="__main__":unittest.main()
