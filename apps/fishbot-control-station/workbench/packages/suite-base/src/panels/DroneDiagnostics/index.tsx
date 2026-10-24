/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import { Alert, Button, Chip, Divider, MenuItem, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { makeStyles } from "tss-react/mui";

import { toSec } from "@lichtblick/rostime";
import { useMessagesByTopic } from "@lichtblick/suite-base/PanelAPI";
import EmptyState from "@lichtblick/suite-base/components/EmptyState";
import {
  MessagePipelineContext,
  useMessagePipeline,
} from "@lichtblick/suite-base/components/MessagePipeline";
import Panel from "@lichtblick/suite-base/components/Panel";
import PanelToolbar from "@lichtblick/suite-base/components/PanelToolbar";
import Stack from "@lichtblick/suite-base/components/Stack";

import { CandidateComparison } from "./CandidateComparison";
import { SparseObservation } from "./SparseObservation";

type Event = {
  id: string;
  kind: string;
  time_s?: number;
  label: string;
  detail?: string;
  source: string;
};
type Diagnostics = {
  schema_version: number;
  task_id: string;
  task_name: string;
  clock: string;
  status: string;
  passed?: boolean;
  function_verdict: string;
  safety: Record<string, boolean | undefined>;
  landed?: boolean;
  disarmed?: boolean;
  maximum_altitude_m?: number;
  altitude_limit_m?: number;
  primary_failure?: { error: string; simulation_s: number };
  actual_source: string;
  nominal_count: number;
  backup_available: boolean;
  perception_samples: number;
  unaligned_events: number;
  events: Event[];
  limitations: string[];
  warnings: string[];
  current?: { phase: string; pose_age_s?: number; nominal_id?: number; reference_age_s?: number };
};
const TOPICS = ["/drone/diagnostics", "/drone/sparse", "/drone/candidates"];
const selectId = (context: MessagePipelineContext) => context.playerState.playerId;
const selectData = (context: MessagePipelineContext) => context.playerState.activeData;
const selectSeek = (context: MessagePipelineContext) => context.seekPlayback;
const booleanLabel = (value: unknown) => (value === true ? "是" : value === false ? "否" : "未知");
const phaseLabel: Record<string, string> = {
  connecting: "连接",
  taking_off: "起飞",
  waypoint: "巡航",
  recovery_hover: "恢复悬停",
  recovery_backtrack: "历史路径退回",
  landing: "降落",
  landed: "落地",
  error: "失败",
};
const useStyles = makeStyles()((theme) => ({
  content: { padding: theme.spacing(1.5), gap: theme.spacing(1.25), minHeight: 0 },
  row: { display: "flex", flexWrap: "wrap", gap: theme.spacing(1), alignItems: "center" },
  numbers: { fontVariantNumeric: "tabular-nums" },
  events: {
    display: "flex",
    flexDirection: "column",
    gap: theme.spacing(0.75),
    maxHeight: 360,
    overflowY: "auto",
  },
  event: { paddingBottom: theme.spacing(0.75), borderBottom: `1px solid ${theme.palette.divider}` },
  wrap: { overflowWrap: "anywhere", minWidth: 0 },
  list: { margin: 0, paddingLeft: theme.spacing(2) },
}));

function DiagnosticContent(): React.JSX.Element {
  const { classes } = useStyles();
  const active = useMessagePipeline(selectData);
  const seek = useMessagePipeline(selectSeek);
  const messages = useMessagesByTopic({ topics: TOPICS, historySize: 1 });
  const message = messages[TOPICS[0]!]?.at(-1);
  const sparseMessage = messages[TOPICS[1]!]?.at(-1);
  const candidateMessage = messages[TOPICS[2]!]?.at(-1);
  const [filter, setFilter] = useState("all");
  const [history, setHistory] = useState<
    { id: string; name: string; status: string; url: string }[]
  >([]);
  const [historyError, setHistoryError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/drone/diagnostics", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`历史列表读取失败（HTTP ${response.status}）`);
        }
        const value = (await response.json()) as { tasks?: typeof history };
        setHistory(value.tasks ?? []);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHistoryError(error instanceof Error ? error.message : "历史列表读取失败");
        }
      });
    return () => {
      controller.abort();
    };
  }, []);
  if (!active || !message || toSec(message.receiveTime) > toSec(active.currentTime)) {
    return <EmptyState>打开无人机诊断 MCAP，查看同一时刻的轨迹、事件与原报告。</EmptyState>;
  }
  const data = message.message as Diagnostics | undefined;
  if (
    message.schemaName !== "drone.Diagnostics" ||
    data?.schema_version !== 1 ||
    data.clock !== "simulation_seconds_not_unix" ||
    !Array.isArray(data.events) ||
    !data.current
  ) {
    return <Alert severity="warning">当前记录不含可读的无人机诊断通道。原三维回放仍可使用。</Alert>;
  }
  const current = toSec(active.currentTime);
  const start = toSec(active.startTime),
    end = toSec(active.endTime);
  const jump = (seconds: number) => {
    if (!Number.isFinite(seconds) || seconds < start || seconds > end) {
      return;
    }
    const sec = Math.floor(seconds),
      nsec = Math.round((seconds - sec) * 1e9);
    seek?.(nsec === 1e9 ? { sec: sec + 1, nsec: 0 } : { sec, nsec });
  };
  const events = data.events.filter((event) => filter === "all" || event.kind === filter);
  return (
    <Stack className={classes.content} overflowY="auto" fullHeight>
      <Typography variant="subtitle1">{data.task_name}</Typography>
      <Typography variant="caption" className={classes.wrap}>
        原任务 ID：{data.task_id}
      </Typography>
      <TextField
        select
        size="small"
        label="历史诊断"
        value={history.some((item) => item.id === data.task_id) ? data.task_id : ""}
        onChange={(event) => {
          const item = history.find((value) => value.id === event.target.value);
          if (item) {
            window.location.assign(
              `/drone-diagnostics?taskId=${encodeURIComponent(item.id)}${window.innerWidth < 600 ? "&mobile=1" : ""}`,
            );
          }
        }}
      >
        <MenuItem value="">选择已保存回合</MenuItem>
        {history.map((item) => (
          <MenuItem key={item.id} value={item.id}>
            {item.status} · {item.name}
          </MenuItem>
        ))}
      </TextField>
      {historyError && <Alert severity="warning">{historyError}</Alert>}
      <Alert severity="info">历史记录只读回放。定位事件只移动播放时间，不发送飞行命令。</Alert>
      <div className={classes.row}>
        <Chip size="small" label={phaseLabel[data.current.phase] ?? data.current.phase} />
        <Typography variant="body2" className={classes.numbers}>
          仿真时间 {current.toFixed(3)} s
        </Typography>
      </div>
      <Typography variant="caption" color="text.secondary">
        黄：当时收到的名义曲线 #{data.current.nominal_id ?? "无有效记录"}；
        {data.actual_source === "Gazebo" ? "绿：Gazebo实际轨迹" : "橙：MAVSDK估计轨迹"}
        ；青：备份未记录。
      </Typography>
      <Typography variant="caption" color="text.secondary">
        当前位姿样本年龄：{data.current.pose_age_s?.toFixed(3) ?? "未知"} s； 参考年龄：
        {data.current.reference_age_s?.toFixed(3) ?? "未知"} s。
      </Typography>
      <Divider />
      <CandidateComparison
        value={candidateMessage?.schemaName === "drone.StopCandidates" ? candidateMessage.message : undefined}
        taskId={data.task_id}
      />
      <Divider />
      <SparseObservation
        value={
          sparseMessage?.schemaName === "drone.SparseObservation"
            ? sparseMessage.message
            : undefined
        }
        taskId={data.task_id}
        seconds={current}
      />
      <Divider />
      <Typography variant="subtitle2">整回合结果</Typography>
      <Typography variant="caption" color="text.secondary">
        以下为原报告终态，不随播放指针改判。
      </Typography>
      <Alert
        severity={data.passed === false ? "error" : data.passed === true ? "success" : "warning"}
      >
        原任务：{data.passed === false ? "未通过" : data.passed === true ? "通过" : "未评分"}；
        落地：{booleanLabel(data.landed)}；解除电机：{booleanLabel(data.disarmed)}。
      </Alert>
      <Typography variant="body2">
        高度最高 {data.maximum_altitude_m?.toFixed(6) ?? "未知"} m / 上界{" "}
        {data.altitude_limit_m?.toFixed(2) ?? "未知"} m。 净空：
        {booleanLabel(data.safety.clearance_ok)}；速度：{booleanLabel(data.safety.speed_ok)}
        ；无碰撞：{booleanLabel(data.safety.collision_free)}。
      </Typography>
      {data.primary_failure && (
        <Button
          variant="outlined"
          color="error"
          size="small"
          disabled={
            !seek ||
            data.primary_failure.simulation_s < start ||
            data.primary_failure.simulation_s > end
          }
          onClick={() => {
            jump(data.primary_failure!.simulation_s);
          }}
        >
          定位首发故障 {data.primary_failure.simulation_s.toFixed(3)} s
        </Button>
      )}
      {data.primary_failure && (
        <Typography variant="body2" className={classes.wrap}>
          {data.primary_failure.error}
        </Typography>
      )}
      <Divider />
      <div className={classes.row}>
        <Typography variant="subtitle2">事件与诊断见证</Typography>
        <TextField
          select
          size="small"
          label="筛选事件"
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value);
          }}
        >
          {[
            ["all", "全部"],
            ["failure", "任务故障"],
            ["phase", "飞行阶段"],
            ["perception", "感知失流"],
            ["candidate", "候选界"],
            ["collision", "候选碰撞"],
            ["curve", "名义曲线"],
          ].map(([value, label]) => (
            <MenuItem key={value} value={value}>
              {label}
            </MenuItem>
          ))}
        </TextField>
      </div>
      <Typography variant="caption" color="text.secondary">
        {data.nominal_count} 条名义曲线；{data.perception_samples} 条感知时序见证；
        {data.unaligned_events} 条事件缺绝对时刻。日志症状不等同根因。
      </Typography>
      <div className={classes.events} aria-label="历史诊断事件">
        {events.length === 0 && <Typography variant="body2">原记录没有此类事件。</Typography>}
        {events.map((event) => (
          <div key={event.id} className={classes.event}>
            <Button
              size="small"
              color={event.kind === "failure" || event.kind === "collision" ? "error" : "primary"}
              disabled={
                !seek || event.time_s == undefined || event.time_s < start || event.time_s > end
              }
              onClick={() => {
                if (event.time_s != undefined) {
                  jump(event.time_s);
                }
              }}
            >
              {event.time_s?.toFixed(3) ?? "无绝对时刻"}{" "}
              {event.time_s != undefined ? "s · " : " · "}
              {phaseLabel[event.label] ?? event.label}
            </Button>
            {event.detail && (
              <Typography variant="caption" display="block" className={classes.wrap}>
                {event.detail}
              </Typography>
            )}
            <Typography variant="caption" display="block" color="text.secondary">
              {event.source}
            </Typography>
          </div>
        ))}
      </div>
      <details>
        <summary>通道与证据边界</summary>
        <ul className={classes.list}>
          {[...data.limitations, ...data.warnings].map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </details>
    </Stack>
  );
}

function DroneDiagnostics(): React.JSX.Element {
  const playerId = useMessagePipeline(selectId);
  return (
    <>
      <PanelToolbar />
      <DiagnosticContent key={playerId} />
    </>
  );
}
DroneDiagnostics.panelType = "DroneDiagnostics";
DroneDiagnostics.defaultConfig = {};
export default Panel(DroneDiagnostics);
