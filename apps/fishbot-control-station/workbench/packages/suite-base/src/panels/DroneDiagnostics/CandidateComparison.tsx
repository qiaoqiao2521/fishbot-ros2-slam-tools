/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import { Alert, Typography } from "@mui/material";

type Comparison = {
  available?: boolean;
  task_id?: string;
  state?: string;
  parent_id?: number;
  reason?: string;
  summary?: { generated: number; math_passed: number; cut_c3_passed: number };
  mathematical_passed?: boolean;
  failed_checks?: string[];
  speed_max?: number;
  acceleration_max?: number;
  height_max?: number;
  cut_sim_s?: number;
  offline_wall_ms?: { native_compute?: number };
};

export function CandidateComparison({
  value,
  taskId,
}: {
  value: unknown;
  taskId: string;
}): React.JSX.Element {
  const data = value as Comparison | undefined;
  if (data?.available !== true || data.task_id !== taskId) {
    return (
      <Typography variant="caption" color="text.secondary">
        {data?.reason ?? "此回合未生成离线刹停对照。"}
      </Typography>
    );
  }
  return (
    <details open>
      <summary>离线前缀＋MINCO刹停</summary>
      <Typography variant="caption" display="block">
        仅历史推演。紫线为数学判据通过，红线为拒绝；动态占据未验证，均未执行。
      </Typography>
      <Typography variant="caption" display="block">
        共 {data.summary?.generated ?? 0} 条；数学通过 {data.summary?.math_passed ?? 0} 条；切点 C3
        连续 {data.summary?.cut_c3_passed ?? 0} 条。原前缀整体仍为 C2。
      </Typography>
      {data.state === "offline_candidate" ? (
        <>
          <Alert severity={data.mathematical_passed === true ? "warning" : "error"} style={{ marginTop: 8 }}>
            曲线 #{data.parent_id}：
            {data.mathematical_passed === true ? "数学通过，占据未验证" : "数学拒绝（加速度等原判据）"}
          </Alert>
          <Typography variant="caption" display="block">
            峰速 {data.speed_max?.toFixed(3)} m/s；峰加速度 {data.acceleration_max?.toFixed(3)}
            {" m/s²；最高 "}
            {data.height_max?.toFixed(3)} m。切点 {data.cut_sim_s?.toFixed(3)} s。
          </Typography>
          <Typography variant="caption" display="block">
            {(data.failed_checks?.length ?? 0) > 0 ? `拒绝项：${data.failed_checks?.join("、")}。` : "原动力学界通过。"}
            原生生成 {data.offline_wall_ms?.native_compute?.toFixed(3)} ms，仅离线墙钟测量。
          </Typography>
        </>
      ) : (
        <Typography variant="caption" display="block">
          {data.reason === "source_task_identity_unrecorded"
            ? "当前原曲线缺任务身份，不派生候选。"
            : "当前参考没有可展示的离线候选，保留原回放。"}
        </Typography>
      )}
    </details>
  );
}
