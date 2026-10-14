# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Pure verdict excerpt from Recursia; no framework/runtime dependencies.
# Source: cocacola-lab/Recursia, commit 56c902d95958041d231811d168008a2811933f65
# Original: recursia/real/cap/agent/rsi/recursia.py lines 181-193
# Source file SHA256: d5fc191fb848f23f1a6a1a11c026851ca4067dd5e250c11a6a80cdaf4311e3c0
# Original AST source segment SHA256: b50de7ad8fb9a7fb8d1b5e941c19f1133a76f4f0985e48140305a39164f380d9
# Indentation only was changed to expose the static method as a function.
# License and upstream notices: docs/licenses/Recursia-LICENSE.txt

def verdict(reference, records, failure_class=None):
    regressions = [key for key, old in reference.items() if old["success"] and not records[key]["success"]]
    gains = [key for key, old in reference.items() if not old["success"] and records[key]["success"]]
    affected = [key for key, old in reference.items() if not old["success"]
                and failure_class and old.get("failure_class") == failure_class]
    advanced = bool(affected) and all(records[key]["success"] or (
        records[key].get("failure_class") and records[key]["failure_class"] != failure_class
        and reference[key].get("progress") is not None and records[key].get("progress") is not None
        and records[key]["progress"] > reference[key]["progress"]) for key in affected)
    return {"accepted": not regressions and bool(gains or advanced), "gained_tasks": gains,
            "regressed_tasks": regressions, "failure_class_eliminated": failure_class if advanced else None,
            "reason": "regression" if regressions else "success_gain" if gains else
                      "failure_stage_advanced" if advanced else "no_measured_improvement"}
