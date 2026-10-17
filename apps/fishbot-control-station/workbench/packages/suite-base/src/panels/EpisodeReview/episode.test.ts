/* eslint-disable @lichtblick/license-header -- The upstream rule hardcodes BMW ownership; this project-authored file retains its own MPL notice. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0

// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/

import { parseEpisodeReview, simulationSecondsToTime, stageLabel } from "./episode";

function sample(): Record<string, unknown> {
  return {
    schema_version: 1,
    run_id: "fixture-only-not-acceptance",
    task: "固定方块抓放",
    source_kind: "simulation_recording",
    clock: "simulation_seconds_not_unix",
    timestamp: { sec: 12, nsec: 20_000_000 },
    sim_duration_s: 66.56,
    stage: "close",
    success: true,
    independent: { available: true, passed: true, return_max_error_rad: 0.0001 },
    metrics: {
      wall_s: 84,
      physical_lift_passed: true,
      place_verified: true,
      controller_done: true,
    },
    provenance: {
      trace_sha256: "a".repeat(64),
      report_sha256: "b".repeat(64),
      source_bound: true,
    },
    limitations: ["测试夹具，不代表机器人验收"],
    stage_events: [
      { stage: "approach", sim_time_s: 0.02 },
      { stage: "close", sim_time_s: 11.02 },
    ],
  };
}

describe("parseEpisodeReview", () => {
  it("preserves final result independently of the currently replayed stage", () => {
    const result = parseEpisodeReview(sample());
    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error);
    }
    expect(result.value.stage).toBe("close");
    expect(result.value.success).toBe(true);
    expect(result.value.timestamp).toEqual({ sec: 12, nsec: 20_000_000 });
  });

  it("does not promote an unbound source or missing independent acceptance to passed", () => {
    const value = sample();
    value.provenance = {
      trace_sha256: "a".repeat(64),
      report_sha256: "b".repeat(64),
      source_bound: false,
    };
    value.independent = { available: false };
    const result = parseEpisodeReview(value);
    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error);
    }
    expect(result.value.provenance.source_bound).toBe(false);
    expect(result.value.independent.passed).toBeUndefined();
  });

  it.each([undefined, null, [], "report"])("rejects a non-object %p", (value) => {
    expect(parseEpisodeReview(value).ok).toBe(false);
  });

  it.each([
    ["schema_version", 2],
    ["clock", "unix"],
    ["success", "true"],
    ["source_kind", "live_robot"],
    ["timestamp", { sec: 2, nsec: 1_000_000_000 }],
    ["sim_duration_s", Number.POSITIVE_INFINITY],
    ["independent", { available: true }],
    ["limitations", "all scenes"],
  ])("rejects invalid %s without coercion", (field, value) => {
    expect(parseEpisodeReview({ ...sample(), [field]: value }).ok).toBe(false);
  });

  it("rejects a malformed source fingerprint", () => {
    const value = sample();
    value.provenance = { trace_sha256: "short", report_sha256: "b".repeat(64), source_bound: true };
    expect(parseEpisodeReview(value).ok).toBe(false);
  });

  it("rejects non-finite metrics rather than rendering a false numeric result", () => {
    const value = sample();
    value.metrics = {
      wall_s: 84,
      physical_lift_passed: true,
      place_verified: true,
      controller_done: true,
      force_n: Number.NaN,
    };
    expect(parseEpisodeReview(value).ok).toBe(false);
  });

  it("accepts a failed physical result as a failed result", () => {
    const result = parseEpisodeReview({ ...sample(), success: false });
    if (!result.ok) {
      throw new Error(result.error);
    }
    expect(result.value.success).toBe(false);
  });

  it.each([
    { events: [{ stage: "close", sim_time_s: -1 }] },
    { events: [{ stage: "close", sim_time_s: 70 }] },
    {
      events: [
        { stage: "close", sim_time_s: 12 },
        { stage: "approach", sim_time_s: 1 },
      ],
    },
  ])("rejects invalid or unordered event times $events", ({ events }) => {
    expect(parseEpisodeReview({ ...sample(), stage_events: events }).ok).toBe(false);
  });

  it("rejects a missing stage event field from the versioned message", () => {
    const value = sample();
    delete value.stage_events;
    const result = parseEpisodeReview(value);
    expect(result.ok).toBe(false);
  });
});

describe("simulationSecondsToTime", () => {
  it("uses physical time directly, without subtracting the first 0.02-second sample", () => {
    expect(simulationSecondsToTime(0.02)).toEqual({ sec: 0, nsec: 20_000_000 });
    expect(simulationSecondsToTime(11.02)).toEqual({ sec: 11, nsec: 20_000_000 });
  });

  it("normalizes rounding across a nanosecond carry", () => {
    expect(simulationSecondsToTime(1.9999999996)).toEqual({ sec: 2, nsec: 0 });
  });

  it.each([
    -1,
    Number.NaN,
    Number.POSITIVE_INFINITY,
    Number.MAX_SAFE_INTEGER,
  ])("refuses invalid seek time %s", (seconds) => {
    expect(simulationSecondsToTime(seconds)).toBeUndefined();
  });
});

it("does not invent a translation for an unknown future stage", () => {
  expect(stageLabel("close")).toBe("闭爪");
  expect(stageLabel("unrecognized-stage")).toBe("unrecognized-stage");
});
