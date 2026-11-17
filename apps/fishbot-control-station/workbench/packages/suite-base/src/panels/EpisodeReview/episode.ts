/* eslint-disable @lichtblick/license-header -- The upstream rule hardcodes BMW ownership; this project-authored file retains its own MPL notice. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0

// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/

export const EPISODE_TOPIC = "/so101/episode";
export const EPISODE_SCHEMA = "so101.EpisodeReview";

export type EpisodeTime = { sec: number; nsec: number };
export type EpisodeEvent = { stage: string; sim_time_s: number };
export type EpisodeReviewData = {
  schema_version: 1;
  run_id: string;
  task: string;
  source_kind: "simulation_recording";
  clock: "simulation_seconds_not_unix";
  timestamp: EpisodeTime;
  sim_duration_s: number;
  stage: string;
  success: boolean;
  independent: { available: boolean; passed?: boolean; return_max_error_rad?: number };
  metrics: {
    wall_s: number;
    physical_lift_passed: boolean;
    place_verified: boolean;
    controller_done: boolean;
    [name: string]: number | boolean;
  };
  provenance: { trace_sha256: string; report_sha256: string; source_bound: boolean };
  limitations: string[];
  stage_events: EpisodeEvent[];
};

export type EpisodeParseResult =
  | { ok: true; value: EpisodeReviewData }
  | { ok: false; error: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value != undefined && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isNonnegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isTime(value: unknown): value is EpisodeTime {
  return (
    isRecord(value) &&
    typeof value.sec === "number" &&
    Number.isSafeInteger(value.sec) &&
    value.sec >= 0 &&
    typeof value.nsec === "number" &&
    Number.isInteger(value.nsec) &&
    value.nsec >= 0 &&
    value.nsec < 1_000_000_000
  );
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

/** Validate decoded MCAP messages without coercing missing facts into success. */
export function parseEpisodeReview(value: unknown): EpisodeParseResult {
  const fail = (error: string): EpisodeParseResult => ({ ok: false, error });
  if (!isRecord(value)) {
    return fail("回合消息必须是对象。");
  }
  if (value.schema_version !== 1 || value.clock !== "simulation_seconds_not_unix") {
    return fail("回合版本或物理时钟约定不匹配。");
  }
  if (!isText(value.run_id) || !isText(value.task) || !isText(value.stage)) {
    return fail("回合、任务或阶段字段缺失。");
  }
  if (value.source_kind !== "simulation_recording") {
    return fail("此面板只支持已录制的仿真回合。");
  }
  if (
    !isTime(value.timestamp) ||
    !isNonnegativeNumber(value.sim_duration_s) ||
    value.sim_duration_s === 0 ||
    value.timestamp.sec + value.timestamp.nsec / 1_000_000_000 > value.sim_duration_s + 1e-8
  ) {
    return fail("物理时间或回合时长无效。");
  }
  if (typeof value.success !== "boolean") {
    return fail("回合最终结果必须是明确的布尔值。");
  }

  const independent = value.independent;
  if (
    !isRecord(independent) ||
    typeof independent.available !== "boolean" ||
    (independent.passed != undefined && typeof independent.passed !== "boolean") ||
    (independent.available && typeof independent.passed !== "boolean") ||
    (independent.return_max_error_rad != undefined &&
      !isNonnegativeNumber(independent.return_max_error_rad))
  ) {
    return fail("独立验收字段无效；无报告时不能推定通过。");
  }

  const metrics = value.metrics;
  if (
    !isRecord(metrics) ||
    !isNonnegativeNumber(metrics.wall_s) ||
    typeof metrics.physical_lift_passed !== "boolean" ||
    typeof metrics.place_verified !== "boolean" ||
    typeof metrics.controller_done !== "boolean"
  ) {
    return fail("物理指标缺失或类型无效。");
  }
  const parsedMetrics: Record<string, number | boolean> = {};
  for (const [name, metric] of Object.entries(metrics)) {
    if (typeof metric !== "boolean" && !(typeof metric === "number" && Number.isFinite(metric))) {
      return fail(`物理指标 ${name} 不是有限数值或布尔值。`);
    }
    parsedMetrics[name] = metric;
  }

  const provenance = value.provenance;
  if (
    !isRecord(provenance) ||
    !isSha256(provenance.trace_sha256) ||
    !isSha256(provenance.report_sha256) ||
    typeof provenance.source_bound !== "boolean"
  ) {
    return fail("来源指纹或绑定状态无效。");
  }
  if (!Array.isArray(value.limitations) || !value.limitations.every(isText)) {
    return fail("回合适用范围必须是文本列表。");
  }

  const stageEvents: EpisodeEvent[] = [];
  if (!Array.isArray(value.stage_events)) {
    return fail("阶段事件必须是列表。");
  }
  for (const event of value.stage_events) {
    if (
      !isRecord(event) ||
      !isText(event.stage) ||
      !isNonnegativeNumber(event.sim_time_s) ||
      event.sim_time_s > value.sim_duration_s + 1e-8
    ) {
      return fail("阶段事件时间超出回合或字段无效。");
    }
    const previous = stageEvents.at(-1);
    if (previous && event.sim_time_s < previous.sim_time_s) {
      return fail("阶段事件必须按物理时间排序。");
    }
    stageEvents.push({ stage: event.stage, sim_time_s: event.sim_time_s });
  }

  return {
    ok: true,
    value: {
      schema_version: value.schema_version,
      run_id: value.run_id,
      task: value.task,
      source_kind: value.source_kind,
      clock: value.clock,
      timestamp: { sec: value.timestamp.sec, nsec: value.timestamp.nsec },
      sim_duration_s: value.sim_duration_s,
      stage: value.stage,
      success: value.success,
      independent: {
        available: independent.available,
        passed: independent.passed as boolean | undefined,
        return_max_error_rad: independent.return_max_error_rad as number | undefined,
      },
      metrics: {
        ...parsedMetrics,
        wall_s: metrics.wall_s,
        physical_lift_passed: metrics.physical_lift_passed,
        place_verified: metrics.place_verified,
        controller_done: metrics.controller_done,
      },
      provenance: {
        trace_sha256: provenance.trace_sha256,
        report_sha256: provenance.report_sha256,
        source_bound: provenance.source_bound,
      },
      limitations: [...value.limitations],
      stage_events: stageEvents,
    },
  };
}

/** This recording uses physical simulation seconds, not wall time or a frame index. */
export function simulationSecondsToTime(seconds: number): EpisodeTime | undefined {
  if (!isNonnegativeNumber(seconds) || seconds * 1_000_000_000 > Number.MAX_SAFE_INTEGER) {
    return undefined;
  }
  const nanoseconds = Math.round(seconds * 1_000_000_000);
  return {
    sec: Math.floor(nanoseconds / 1_000_000_000),
    nsec: nanoseconds % 1_000_000_000,
  };
}

const STAGE_LABELS: Readonly<Record<string, string>> = {
  ready: "就绪",
  approach: "接近",
  descend: "下降",
  close: "闭爪",
  lift: "抬起",
  hold: "持物",
  transport: "搬运",
  lower: "入盘",
  release: "释放",
  separate: "脱离",
  retreat: "回位",
  settle: "落定",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}
