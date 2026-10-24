/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import { Alert, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";

type Ray = {
  id: string;
  state: string;
  requested_yaw_deg?: number;
  range_m?: number;
  reason?: string;
};
type Stream = { source_stamp_s: number; available_sim_s: number; pose_state: string; rays: Ray[] };
type Sparse = {
  schema_version: number;
  available: boolean;
  task_id?: string;
  reason?: string;
  summary?: { frames: number; paired_poses: number };
  streams?: Record<string, Stream>;
  limitations?: string[];
};

export function SparseObservation({
  value,
  taskId,
  seconds,
}: {
  value: unknown;
  taskId: string;
  seconds: number;
}): React.JSX.Element {
  const data = value as Sparse | undefined;
  if (data?.schema_version !== 1 || !data.available || data.task_id !== taskId) {
    return (
      <Typography variant="caption" color="text.secondary">
        {data?.reason ?? "此回合未生成只读稀疏观测，原轨迹和报告仍可回放。"}
      </Typography>
    );
  }
  return (
    <details open>
      <summary>稀疏观测 · 只读旁路</summary>
      <Typography variant="caption" color="text.secondary">
        基线 EGO＋PX4；四束前视＋一束下视，不参与本次飞行控制。 紫线为源位姿上的新鲜射线，达到 0.25
        s 即隐藏。回放按原位姿帧显示，完整源帧保留在导出文件。
      </Typography>
      <Typography variant="caption" display="block">
        已抽取 {data.summary?.frames ?? "未知"} 帧；同源位姿配对{" "}
        {data.summary?.paired_poses ?? "未知"} 帧。
      </Typography>
      {Object.entries(data.streams ?? {}).length === 0 && (
        <Typography variant="body2">当前时刻尚无可用观测。</Typography>
      )}
      {Object.entries(data.streams ?? {}).map(([name, stream]) => {
        const age = seconds - stream.source_stamp_s;
        const fresh = age >= 0 && age < 0.25;
        return (
          <div key={name}>
            <Typography variant="subtitle2" style={{ marginTop: 8 }}>
              {name === "front" ? "前视固定像素" : "下视中心像素"} · {fresh ? "新鲜" : "已过期"} ·{" "}
              {age.toFixed(3)} s
            </Typography>
            <Typography variant="caption" color="text.secondary">
              源 {stream.source_stamp_s.toFixed(3)} s；可用上界 {stream.available_sim_s.toFixed(3)}{" "}
              s。
              {stream.pose_state !== "recorded_source_pose"
                ? "缺可信世界位姿，不画射线。"
                : "世界位姿来自原理想 Gazebo 定位。"}
            </Typography>
            <Table size="small" aria-label={`${name === "front" ? "前视" : "下视"}稀疏测距`}>
              <TableHead>
                <TableRow>
                  <TableCell>方向</TableCell>
                  <TableCell>回波</TableCell>
                  <TableCell align="right">斜距 m</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {stream.rays.map((ray) => (
                  <TableRow key={ray.id}>
                    <TableCell>
                      {name === "down"
                        ? "下方"
                        : `${(ray.requested_yaw_deg ?? 0) < 0 ? "右" : "左"} ${Math.abs(ray.requested_yaw_deg ?? 0)}°`}
                    </TableCell>
                    <TableCell title={ray.reason}>
                      {ray.state === "hit" ? "有效" : ray.state === "no_return" ? "无回波" : "无效"}
                    </TableCell>
                    <TableCell align="right">
                      {typeof ray.range_m === "number" ? ray.range_m.toFixed(3) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        );
      })}
      <Alert severity="info" style={{ marginTop: 8 }}>
        前视射线之间、侧方和后方仍有盲区；无回波不等于整条通道安全。
      </Alert>
      <details>
        <summary>观测来源与限制</summary>
        <ul>
          {data.limitations?.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </details>
    </details>
  );
}
