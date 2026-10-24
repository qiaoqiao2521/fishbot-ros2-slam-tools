# SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
# SPDX-License-Identifier: MPL-2.0
"""Keep recorded measurements, causal forecasts and handoff qualification apart."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np


TOOLS = Path(__file__).parents[1]/"workbench-tools"
spec = importlib.util.spec_from_file_location("handoff_pv", TOOLS/"drone-handoff-pv.py")
study = importlib.util.module_from_spec(spec); spec.loader.exec_module(study)
ROOT = Path.home()/"dev/ros2/projects/drone"


def state(stamp, available=None):
    return {"source_stamp_ns": str(round(stamp*1e9)), "source_sim_s": stamp,
        "available_by_sim_s": stamp if available is None else available,
        "epoch": 0, "frame_id": "world", "velocity_frame_id": "world",
        "position": [stamp-10.,0.,1.5], "velocity": [1.,0.,0.]}


def report():
    # Analytic reference fixture only: x=t on [0,1], then constant x=1.
    prefix={"duration":1.,"coefficients_descending":[[0.,0.,0.,0.,1.,0.],
        [0.,0.,0.,0.,0.,0.],[0.,0.,0.,0.,0.,1.5]]}
    tail=copy.deepcopy(prefix);tail["coefficients_descending"][0]=[0.,0.,0.,0.,0.,1.]
    candidate={"recorded_task_id":"fixture","start_sim_s":10.,"cut_sim_s":11.,
        "prefix_pieces":[prefix],"native":{"pieces":[tail]},"full_math_gate":{"passed":True}}
    return {"archive_task_id":"fixture","narrow_box_fixture":[[-10.,-10.,0.],[15.,2.03,2.2]],
        "limits":{"acceleration":1.},"rows":[{"variant_id":"analytic","status":"generated",
        "timing":{"relative_to_recorded_failure":"before"},
        "result":{"candidate":candidate,"narrow_box_gate":{"passed":True}}}]}


class HandoffPVTests(unittest.TestCase):
    def analyze(self, states, reports=None, epochs=1):
        return study.run(reports or [report()],states,epochs,ROOT,"fixture")

    def test_one_nanosecond_future_is_neither_exact_nor_available(self):
        result=study.select_inputs([state(11.+1e-9)],11_000_000_000)
        self.assertIsNone(result["exact"]);self.assertIsNone(result["anchor"])

    def test_late_exact_measurement_is_retrospective_only(self):
        old=state(10.9,10.95);late=state(11.,11.01)
        row=self.analyze([late,old])["rows"][0]
        self.assertEqual(row["exact_cut_retrospective"]["status"],"compared")
        self.assertFalse(row["exact_cut_retrospective"]["available_by_cut"])
        self.assertEqual(row["recorder_available_CV"]["source_state"]["source_stamp_ns"],old["source_stamp_ns"])

    def test_unknown_availability_wrong_frame_epoch_and_invalid_pv_do_not_enter_causal_branch(self):
        invalid=[{**state(10.9),"available_by_sim_s":None},
            {**state(10.9),"frame_id":"body"},{**state(10.9),"velocity_frame_id":"body"},
            {**state(10.9),"epoch":1},{**state(10.9),"velocity":[float('nan'),0.,0.]},None]
        result=study.select_inputs(invalid,11_000_000_000)
        self.assertIsNone(result["anchor"])
        self.assertEqual(study.select_inputs([state(11.)],11_000_000_000,False)["exact_reason"],"ambiguous_clock_epoch")

    def test_cv_integrates_from_source_and_is_unaffected_by_shuffled_future_outlier(self):
        old=state(10.8,10.95);future=state(11.1)
        future["position"]=[1e8]*3
        a=self.analyze([old])["rows"][0]["recorder_available_CV"]
        b=self.analyze([future,old])["rows"][0]["recorder_available_CV"]
        self.assertEqual(a,b)
        np.testing.assert_allclose(a["predicted_position"],[1.,0.,1.5],atol=1e-12)
        self.assertAlmostEqual(a["source_age_s"],.2)
        self.assertAlmostEqual(a["availability_age_s"],.05)

    def test_future_conflicting_duplicate_does_not_poison_past_causal_input(self):
        old=state(10.9,10.95);duplicate=copy.deepcopy(old)
        duplicate.update(available_by_sim_s=11.1,position=[99.,0.,1.5])
        selected=study.select_inputs([duplicate,old],11_000_000_000)
        self.assertEqual(selected["anchor"],old)
        selected=study.select_inputs([duplicate,old],10_900_000_000)
        self.assertEqual(selected["exact_reason"],"conflicting_source_stamp")

    def test_conflicting_latest_available_group_does_not_silently_fall_back(self):
        a=state(10.9);b={**a,"velocity":[2.,0.,0.]}
        selected=study.select_inputs([state(10.8),a,b],11_000_000_000)
        self.assertIsNone(selected["anchor"])
        self.assertEqual(selected["anchor_reason"],"conflicting_source_stamp")

    def test_identical_duplicates_choose_earliest_availability(self):
        early=state(10.9,10.91);late={**early,"available_by_sim_s":10.99}
        self.assertEqual(study.select_inputs([late,early],11_000_000_000)["anchor"],early)

    def test_numeric_pv_match_does_not_complete_unknown_vehicle_a_j(self):
        result=self.analyze([state(11.)]);row=result["rows"][0]
        self.assertTrue(row["exact_cut_retrospective"]["numeric_reference_PV_match"])
        self.assertTrue(row["recorder_available_CV"]["numeric_reference_PV_match"])
        self.assertEqual(result["summary"]["full_state_handoffs_qualified"],0)
        self.assertEqual(row["execution_admission"],"not_performed")
        for key in ("exact_cut_retrospective","recorder_available_CV"):
            self.assertIsNone(row[key]["vehicle_acceleration"]);self.assertIsNone(row[key]["vehicle_jerk"])
            self.assertEqual(row[key]["full_state_handoff"],"unqualified")

    def test_directional_margin_uses_signed_axis_not_position_norm(self):
        ref=np.array([[0.,0.],[0.,0.],[2.,0.]])
        row=study.branch([-.1,-.2,2.071],[0.,0.,0.],ref,[[-10.,-10.,0.],[15.,2.03,2.2]],
            {"acceleration":1.},[10.,10.,2.],[15.,.002,.002])
        faces={f["face"]:f for f in row["directional_margin_comparison"]}
        self.assertEqual(faces["y_upper"]["outward_cut_P_difference_m"],0.)
        self.assertFalse(faces["y_upper"]["difference_exceeds_nominal_margin"])
        self.assertTrue(faces["z_upper"]["difference_exceeds_nominal_margin"])
        self.assertAlmostEqual(faces["z_upper"]["outward_cut_P_difference_m"],.071)
        self.assertIn("not a translated trajectory",row["margin_scope"])
        self.assertEqual(row["necessary_reference_model"]["joint_viability"],"not_proven")

    def test_older_source_outside_prefix_is_not_extrapolated_backwards(self):
        row=self.analyze([state(9.9,10.9)])["rows"][0]["recorder_available_CV"]
        self.assertEqual(row["observed_same_source_stamp"]["status"],"unscored")
        self.assertEqual(row["status"],"compared_to_reference_not_oracle_accuracy")

    def test_optional_bad_reports_and_rows_do_not_crash_later_valid_report(self):
        broken=report();broken["rows"]=[None,{"status":"generated","result":None}]
        result=self.analyze([state(11.)],[None,[],{"rows":None},broken,report()])
        self.assertEqual(result["summary"]["compared"],1)
        self.assertTrue(result["warnings"])
        json.dumps(result,allow_nan=False)

    def test_candidate_identity_and_prefix_time_mismatch_are_unscored(self):
        for key,value in [("recorded_task_id","different"),("cut_sim_s",11.01)]:
            bad=report();bad["rows"][0]["result"]["candidate"][key]=value
            result=self.analyze([state(11.)],[bad,report()])
            self.assertEqual(result["rows"][0]["status"],"unscored")
            self.assertEqual(result["summary"]["compared"],1)

    def test_missing_pv_cannot_count_as_a_comparison(self):
        result=self.analyze([])
        self.assertEqual(result["rows"][0]["status"],"unscored")
        self.assertEqual(result["summary"]["compared"],0)
        self.assertEqual(result["summary"]["recorder_available_CV_compared"],0)

    def test_roundoff_future_source_float_does_not_crash_or_complete_forecast(self):
        sample=state(11.);sample["source_sim_s"]+=.4e-9
        sample["available_by_sim_s"]=sample["source_sim_s"]
        row=self.analyze([sample])["rows"][0]
        self.assertEqual(row["exact_cut_retrospective"]["status"],"compared")
        self.assertEqual(row["recorder_available_CV"]["status"],"unscored")
        self.assertEqual(row["recorder_available_CV"]["reason"],"source_float_time_after_cut")


if __name__=="__main__":unittest.main()
