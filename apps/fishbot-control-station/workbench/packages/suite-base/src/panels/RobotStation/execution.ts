/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import { stationRequestsCarryGate } from "./station";
import type { Platform, Station } from "./station";

export type SimulationTask = {
  id: string;
  status: string;
  phase?: string;
  message?: string;
  submittedAt?: string;
  simulation_s?: number;
  report?: Record<string, unknown>;
  skill_evidence?: Record<string, unknown>;
  carry_gate?: Record<string, unknown>;
  carryResumeRequested?: boolean;
  cancelRequested?: boolean;
  artifacts?: { video?: string; report?: string; mcap?: string };
  error?: string;
  station?: Station;
};

export type SimulationRuntime = {
  ready: boolean;
  message: string;
  capabilities?: string[];
  executor?: { planners?: string[] };
  resume_carry?: boolean;
};

export type DronePlanTask = Omit<SimulationTask, "report"> & {
  report?: {
    planner: string;
    flight_control: boolean;
    valid: boolean;
    points?: [number, number, number][];
    min_clearance_m?: number;
    reason?: string;
  };
};

export class TaskRequestError extends Error {
  public constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "TaskRequestError";
  }
}

export async function requestSimulation<T>(
  path: string,
  signal: AbortSignal,
  body?: unknown,
  platform: Platform = "so101",
): Promise<T> {
  const response = await fetch(
    `/api/${platform === "px4" ? "drone" : "so101"}${path}`,
    {
      method: body == undefined ? "GET" : "POST",
      signal,
      headers:
        body == undefined ? undefined : { "Content-Type": "application/json" },
      body: body == undefined ? undefined : JSON.stringify(body),
    },
  );
  const data: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const detail =
      data != undefined && typeof data === "object"
        ? (data as { error?: unknown; message?: unknown })
        : undefined;
    const message =
      typeof detail?.error === "string"
        ? detail.error
        : typeof detail?.message === "string"
          ? detail.message
          : `请求失败（HTTP ${response.status}）`;
    throw new TaskRequestError(message, response.status);
  }
  if (data == undefined) {
    throw new TaskRequestError(
      "服务返回了无法读取的结果，请查询原任务。",
      response.status,
    );
  }
  return data as T;
}

export function taskIsActive(task: SimulationTask | undefined): boolean {
  return (
    task != undefined &&
    !["succeeded", "failed", "cancelled"].includes(task.status)
  );
}

export function carryGateWaiting(task: SimulationTask | undefined): boolean {
  return taskIsActive(task) && task?.cancelRequested !== true && task?.station != undefined
    && stationRequestsCarryGate(task.station)
    && task.carry_gate?.mode === "hold-before-carry" && task.carry_gate.state === "waiting";
}

/** Show original monitor evidence separately from controller phases and task success. */
export function graspEvidenceLabel(task: SimulationTask | undefined): string | undefined {
  const value = task?.skill_evidence ?? task?.report?.skill_evidence;
  if (value == undefined || typeof value !== "object") {
    return undefined;
  }
  const source = value as Record<string, unknown>;
  if (source.schema !== "so101.physical-skill-evidence.v1" || source.scope !== "observation_only"
      || source.grasp == undefined || typeof source.grasp !== "object") {
    return undefined;
  }
  const grasp = source.grasp as Record<string, unknown>;
  if (grasp.postcondition_met !== true) {
    return "物理抓取证据：尚未确认；闭爪阶段不代表已抓住。";
  }
  const elapsed = grasp.first_met_elapsed_s;
  const when = typeof elapsed === "number" && Number.isFinite(elapsed)
    ? `在 ${elapsed.toFixed(2)} s ` : "";
  return `物理抓取证据：曾${when}确认持续持物；不代表本回合完成。`;
}

export function taskStatusLabel(status: string): string {
  return (
    (
      {
        submitting: "正在提交",
        pending: "等待执行",
        running: "正在运行",
        succeeded: "执行完成",
        failed: "执行失败",
        cancelled: "已取消",
        unknown: "状态未确认",
      } as Record<string, string>
    )[status] ?? status
  );
}

export function latestSimulationTask(
  tasks: readonly SimulationTask[],
): SimulationTask | undefined {
  return [...tasks].sort((a, b) =>
    (b.submittedAt ?? "").localeCompare(a.submittedAt ?? ""),
  )[0];
}

// Artifact links come from the local execution service; never accept executable URLs.
export function simulationArtifactUrl(
  value: string | undefined,
): string | undefined {
  if (value != undefined && value.startsWith("/") && !value.startsWith("//")) {
    return value;
  }
  return undefined;
}

/** Open a completed recording with Lichtblick's existing remote-file player. */
export function simulationReplayUrl(
  artifact: string | undefined,
  origin: string,
): string | undefined {
  const local = simulationArtifactUrl(artifact);
  if (!local) {
    return undefined;
  }
  const recording = new URL(local, origin);
  if (recording.origin !== new URL(origin).origin) {
    return undefined;
  }
  const query = new URLSearchParams({
    ds: "remote-file",
    "ds.url": recording.href,
    layoutUrl: new URL("/layouts/drone-review.json", origin).href,
  });
  return `/?${query}`;
}
