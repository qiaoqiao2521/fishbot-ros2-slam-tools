/* eslint-disable @lichtblick/license-header -- The upstream rule hardcodes BMW ownership; this project-authored file retains its own MPL notice. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0

// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/

import { Alert, Button, Chip, Divider, Typography } from "@mui/material";
import { Fragment, useMemo } from "react";
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

import {
  EPISODE_SCHEMA,
  EPISODE_TOPIC,
  EpisodeReviewData,
  parseEpisodeReview,
  simulationSecondsToTime,
  stageLabel,
} from "./episode";

const TOPICS = [EPISODE_TOPIC];
const selectPlayerId = (context: MessagePipelineContext) => context.playerState.playerId;
const selectActiveData = (context: MessagePipelineContext) => context.playerState.activeData;
const selectSeekPlayback = (context: MessagePipelineContext) => context.seekPlayback;

const useStyles = makeStyles()((theme) => ({
  content: { padding: theme.spacing(2), gap: theme.spacing(1.5), minHeight: 0 },
  row: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: theme.spacing(1) },
  numbers: { fontVariantNumeric: "tabular-nums" },
  metrics: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: theme.spacing(0.75, 1.5),
    margin: 0,
    "& dt": { color: theme.palette.text.secondary },
    "& dd": { margin: 0, fontVariantNumeric: "tabular-nums" },
  },
  hash: { wordBreak: "break-all", fontFamily: "monospace", fontSize: "0.75rem" },
  limitations: { margin: 0, paddingLeft: theme.spacing(2.5) },
}));

function ResultChip({ label, passed }: { label: string; passed: boolean | undefined }) {
  return (
    <Chip
      size="small"
      variant="outlined"
      color={passed == undefined ? "default" : passed ? "success" : "error"}
      label={`${label}：${passed == undefined ? "无报告" : passed ? "通过" : "未通过"}`}
    />
  );
}

const EXTRA_METRIC_LABELS: Readonly<Record<string, string>> = {
  settled_duration_s: "蓝盘静稳（s）",
  max_xy_drift_m: "最大平面漂移（m）",
  post_detach_peak_force_n: "脱离后再接触力（N）",
  return_max_error_rad: "回位最大关节误差（rad）",
};

function EpisodeMetrics({ episode }: { episode: EpisodeReviewData }) {
  const { classes } = useStyles();
  const extraMetrics = Object.entries(episode.metrics).filter(
    ([name]) => EXTRA_METRIC_LABELS[name] != undefined,
  );
  return (
    <dl className={classes.metrics}>
      <dt>真实夹起</dt>
      <dd>{episode.metrics.physical_lift_passed ? "通过" : "未通过"}</dd>
      <dt>放置验证</dt>
      <dd>{episode.metrics.place_verified ? "通过" : "未通过"}</dd>
      <dt>执行器完成</dt>
      <dd>{episode.metrics.controller_done ? "是" : "否"}</dd>
      <dt>回合仿真时长</dt>
      <dd>{episode.sim_duration_s.toFixed(2)} s</dd>
      <dt>原记录墙钟耗时</dt>
      <dd>{episode.metrics.wall_s.toFixed(3)} s</dd>
      {extraMetrics.map(([name, value]) => (
        <Fragment key={name}>
          <dt>{EXTRA_METRIC_LABELS[name]}</dt>
          <dd>
            {typeof value === "number" ? Number(value.toPrecision(6)).toString() : String(value)}
          </dd>
        </Fragment>
      ))}
      {episode.independent.return_max_error_rad != undefined && (
        <>
          <dt>独立回位误差</dt>
          <dd>{episode.independent.return_max_error_rad.toPrecision(6)} rad</dd>
        </>
      )}
    </dl>
  );
}

/** Source changes remount this reader; the upstream reducer clears messages on every seek. */
function EpisodeContent(): React.JSX.Element {
  const { classes } = useStyles();
  const activeData = useMessagePipeline(selectActiveData);
  const seekPlayback = useMessagePipeline(selectSeekPlayback);
  const messages = useMessagesByTopic({ topics: TOPICS, historySize: 1 });
  const message = messages[EPISODE_TOPIC]?.at(-1);
  const parsed = useMemo(() => parseEpisodeReview(message?.message), [message]);

  if (!activeData || !message) {
    return <EmptyState>打开 SO101 回合 MCAP，即可查看报告与回放阶段。</EmptyState>;
  }
  if (message.schemaName !== EPISODE_SCHEMA) {
    return <Alert severity="error">回合消息格式不匹配，未显示上一次报告。</Alert>;
  }
  if (!parsed.ok) {
    return <Alert severity="error">报告无法读取：{parsed.error}</Alert>;
  }
  if (toSec(message.receiveTime) > toSec(activeData.currentTime)) {
    return <EmptyState>正在定位当前回合…</EmptyState>;
  }

  const episode = parsed.value;
  const currentSeconds = toSec(activeData.currentTime);
  const canSeek = seekPlayback != undefined;
  const startSeconds = toSec(activeData.startTime);
  const endSeconds = toSec(activeData.endTime);

  return (
    <Stack className={classes.content} overflowY="auto" fullHeight>
      <Typography variant="subtitle1">{episode.task}</Typography>
      <Typography variant="body2" color="text.secondary">
        回合 {episode.run_id}
      </Typography>
      <Alert severity="info">仿真录制回放。阶段定位只移动播放时间，不发送机器人动作。</Alert>

      <div className={classes.row}>
        <Chip size="small" label={`当前阶段：${stageLabel(episode.stage)}`} />
        <Typography variant="body2" className={classes.numbers}>
          物理时间 {currentSeconds.toFixed(2)} / {episode.sim_duration_s.toFixed(2)} s
        </Typography>
      </div>

      <Divider />
      <Typography variant="subtitle2">回合最终结果</Typography>
      <Typography variant="caption" color="text.secondary">
        以下结论来自整回合报告，不表示播放指针已执行到终点。
      </Typography>
      <div className={classes.row}>
        <ResultChip label="原报告" passed={episode.success} />
        <ResultChip
          label="独立验收"
          passed={episode.independent.available ? episode.independent.passed : undefined}
        />
        <ResultChip label="来源绑定" passed={episode.provenance.source_bound} />
      </div>
      {!episode.provenance.source_bound && (
        <Alert severity="warning">报告与轨迹来源未绑定，不能据此确认本回合验收。</Alert>
      )}
      <EpisodeMetrics episode={episode} />

      <Divider />
      <Typography variant="subtitle2">阶段定位</Typography>
      {episode.stage_events.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          原记录未提供阶段时间。
        </Typography>
      ) : (
        <div className={classes.row}>
          {episode.stage_events.map((event, index) => {
            const time = simulationSecondsToTime(event.sim_time_s);
            const seekSeconds = time ? toSec(time) : undefined;
            const withinRecording =
              seekSeconds != undefined && seekSeconds >= startSeconds && seekSeconds <= endSeconds;
            return (
              <Button
                key={`${event.stage}-${index}`}
                size="small"
                variant={event.stage === episode.stage ? "contained" : "outlined"}
                disabled={!canSeek || time == undefined || !withinRecording}
                onClick={() => {
                  if (time) {
                    seekPlayback?.(time);
                  }
                }}
              >
                {stageLabel(event.stage)} {event.sim_time_s.toFixed(2)}s
              </Button>
            );
          })}
        </div>
      )}

      <Divider />
      <Typography variant="subtitle2">适用范围</Typography>
      <ul className={classes.limitations}>
        {episode.limitations.map((limitation, index) => (
          <li key={index}>{limitation}</li>
        ))}
      </ul>
      <details>
        <summary>来源指纹</summary>
        <Typography variant="caption">轨迹 SHA-256</Typography>
        <Typography className={classes.hash}>{episode.provenance.trace_sha256}</Typography>
        <Typography variant="caption">报告 SHA-256</Typography>
        <Typography className={classes.hash}>{episode.provenance.report_sha256}</Typography>
      </details>
    </Stack>
  );
}

function EpisodeReview(): React.JSX.Element {
  const playerId = useMessagePipeline(selectPlayerId);
  return (
    <>
      <PanelToolbar />
      <EpisodeContent key={playerId} />
    </>
  );
}

EpisodeReview.panelType = "EpisodeReview";
EpisodeReview.defaultConfig = {};

export default Panel(EpisodeReview);
