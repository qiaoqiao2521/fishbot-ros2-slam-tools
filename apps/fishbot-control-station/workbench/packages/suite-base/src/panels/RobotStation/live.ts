/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import { requestSimulation } from "./execution";
import { stationPlatform } from "./station";
import type { Platform, Station } from "./station";

export type SceneMode = {
  mode: "draft" | "task";
  taskId?: string;
  phase?: string;
  status?: string;
  simulation_s?: number;
};

export async function previewStation(
  station: Station,
  signal: AbortSignal,
): Promise<SceneMode> {
  return await requestSimulation<SceneMode>(
    "/preview",
    signal,
    { station },
    stationPlatform(station),
  );
}

export async function selectScene(
  source:
    | { mode: "draft"; station: Station }
    | { mode: "task"; taskId: string },
  signal: AbortSignal,
  platform: Platform = source.mode === "draft"
    ? stationPlatform(source.station)
    : "so101",
): Promise<SceneMode> {
  return await requestSimulation<SceneMode>(
    "/scene-mode",
    signal,
    source,
    platform,
  );
}

export function sceneModeLabel(source: SceneMode | undefined): string {
  if (!source) {
    return "正在连接三维场景…";
  }
  if (source.mode === "draft") {
    return "编辑预览 · 纯几何，不推进仿真";
  }
  return `任务画面 · ${source.taskId ?? "任务 ID 待同步"}`;
}
