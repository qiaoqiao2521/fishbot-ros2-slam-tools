/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import type { Station } from "./station";

export type SimulationTask = {
  id: string;
  status: string;
  phase?: string;
  message?: string;
  submittedAt?: string;
  simulation_s?: number;
  report?: Record<string, unknown>;
  artifacts?: { video?: string; report?: string };
  error?: string;
  station?: Station;
};

export type SimulationRuntime = {
  ready: boolean;
  message: string;
  capabilities?: string[];
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
): Promise<T> {
  const response = await fetch(`/api/so101${path}`, {
    method: body == undefined ? "GET" : "POST",
    signal,
    headers:
      body == undefined ? undefined : { "Content-Type": "application/json" },
    body: body == undefined ? undefined : JSON.stringify(body),
  });
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
