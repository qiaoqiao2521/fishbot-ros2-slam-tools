/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import {
  Alert,
  Button,
  Divider,
  MenuItem,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useMemo, useRef, useState } from "react";
import { makeStyles } from "tss-react/mui";

import Panel from "@lichtblick/suite-base/components/Panel";
import PanelToolbar from "@lichtblick/suite-base/components/PanelToolbar";
import {
  LayoutState,
  useCurrentLayoutSelector,
  useCurrentLayoutActions,
} from "@lichtblick/suite-base/context/CurrentLayoutContext";
import { useLayoutManager } from "@lichtblick/suite-base/context/LayoutManagerContext";
import { SaveConfig } from "@lichtblick/suite-base/types/panels";

import { clearDroneEditor, setDroneEditor } from "./droneEditor";
import {
  graspEvidenceLabel,
  latestSimulationTask,
  requestSimulation,
  simulationArtifactUrl,
  simulationReplayUrl,
  taskIsActive,
  TaskRequestError,
  taskStatusLabel,
} from "./execution";
import type {
  DronePlanTask,
  SimulationRuntime,
  SimulationTask,
} from "./execution";
import { previewStation, sceneModeLabel, selectScene } from "./live";
import type { SceneMode } from "./live";
import {
  ACTION_LABELS,
  actionNeedsTarget,
  copyStation,
  defaultStation,
  descendants,
  exportStation,
  exportStationRecipe,
  importStation,
  programWarnings,
  removeNode,
  reparent,
  stationActions,
  stationKindLabel,
  stationPlatform,
  transformObstacle,
  worldPosition,
  workspaceStationSample,
} from "./station";
import type { Instruction, Kind, Station, StationNode, Vec3 } from "./station";

type Config = {
  station?: Station;
  executionTaskId?: string;
  previewPlanId?: string;
  previewPlanStation?: Station;
};
const selectedLayoutIdSelector = (state: LayoutState) =>
  state.selectedLayout?.id;
const COLORS: Record<Kind, string> = {
  frame: "#688da8",
  robot: "#5f80b9",
  tool: "#8394a5",
  object: "#e4ac44",
  target: "#44bca7",
  obstacle: "#d97571",
};
const useStyles = makeStyles()((theme) => ({
  content: {
    padding: theme.spacing(1.5),
    overflow: "auto",
    height: "100%",
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    gap: theme.spacing(1.5),
  },
  row: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: theme.spacing(1),
  },
  workspace: {
    display: "grid",
    gridTemplateColumns: "minmax(130px, 1fr) minmax(180px, 1.6fr)",
    gap: theme.spacing(1),
    "@container (max-width: 450px)": { gridTemplateColumns: "1fr" },
  },
  tree: {
    maxHeight: 300,
    overflow: "auto",
    border: `1px solid ${theme.palette.divider}`,
    padding: theme.spacing(0.5),
  },
  object: {
    display: "block",
    width: "100%",
    textAlign: "left",
    border: 0,
    background: "transparent",
    color: theme.palette.text.primary,
    padding: "7px 5px",
    cursor: "pointer",
    borderRadius: 3,
    "&[aria-pressed=true]": { background: theme.palette.action.selected },
    "&:focus-visible": { outline: `2px solid ${theme.palette.primary.main}` },
  },
  plot: {
    width: "100%",
    maxHeight: 265,
    background: "#17232e",
    borderRadius: 4,
  },
  fields: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    gap: theme.spacing(1),
  },
  step: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: theme.spacing(0.5),
    padding: "6px 0",
  },
}));

function ScenePreview({
  station,
  selected,
  select,
}: {
  station: Station;
  selected: string;
  select: (id: string) => void;
}) {
  const { classes } = useStyles();
  const points = station.nodes
    .filter((node) => node.kind !== "tool")
    .map((node) => ({ node, xyz: worldPosition(node, station.nodes) }));
  const xs = points.map(({ xyz }) => xyz[0]);
  const ys = points.map(({ xyz }) => xyz[1]);
  const minX = Math.min(-0.05, ...xs);
  const maxX = Math.max(0.35, ...xs);
  const minY = Math.min(-0.2, ...ys);
  const maxY = Math.max(0.2, ...ys);
  const scale = Math.min(240 / (maxX - minX), 220 / (maxY - minY));
  const project = (p: Vec3) =>
    [30 + (p[0] - minX) * scale, 250 - (p[1] - minY) * scale] as const;
  const route = station.program
    .filter((step) => actionNeedsTarget(step.action))
    .map((step) => station.nodes.find((node) => node.id === step.target))
    .filter((node): node is StationNode => node != undefined)
    .map((node) => project(worldPosition(node, station.nodes)).join(","))
    .join(" ");
  return (
    <svg
      className={classes.plot}
      viewBox="0 0 300 280"
      role="group"
      aria-label="工作站俯视草图，虚线仅表示步骤顺序"
    >
      <text x="12" y="18" fill="#b9c9d7" fontSize="11">
        世界坐标 XY · 虚线为步骤顺序
      </text>
      <polyline
        points={route}
        fill="none"
        stroke="#44bca7"
        strokeDasharray="4 5"
        opacity="0.65"
      />
      {points.map(({ node, xyz }) => {
        const [x, y] = project(xyz);
        return (
          <g
            key={node.id}
            role="button"
            tabIndex={0}
            aria-label={`选择 ${node.name}`}
            aria-pressed={selected === node.id}
            onClick={() => {
              select(node.id);
            }}
            onKeyDown={(event) => {
              if (["Enter", " "].includes(event.key)) {
                event.preventDefault();
                select(node.id);
              }
            }}
            style={{ cursor: "pointer" }}
          >
            {selected === node.id && (
              <circle
                cx={x}
                cy={y}
                r="13"
                fill="none"
                stroke="white"
                strokeWidth="2"
              />
            )}
            {node.kind === "target" ? (
              <path
                d={`M ${x - 6} ${y} h 12 M ${x} ${y - 6} v 12`}
                stroke={COLORS[node.kind]}
                strokeWidth="3"
              />
            ) : (
              <rect
                x={x - 5}
                y={y - 5}
                width="10"
                height="10"
                rx={node.kind === "object" ? 0 : 3}
                fill={COLORS[node.kind]}
              />
            )}
            <title>{`${node.name}: ${xyz.map((value) => value.toFixed(3)).join(", ")} m`}</title>
            {(selected === node.id ||
              node.kind === "frame" ||
              node.kind === "robot") && (
              <text
                x={x + 9}
                y={selected === node.id ? y + 17 : y - 8}
                fill={COLORS[node.kind]}
                fontSize="10"
              >
                {node.name.slice(0, 9)}
              </text>
            )}
          </g>
        );
      })}
      <text x="12" y="274" fill="#b9c9d7" fontSize="10">
        X → Y ↑ 高度请看属性；未做碰撞或运动学计算
      </text>
    </svg>
  );
}

function RobotStation({
  config,
  saveConfig,
}: {
  config: Config;
  saveConfig: SaveConfig<Config>;
}): React.JSX.Element {
  const { classes } = useStyles();
  const station = useMemo(
    () => config.station ?? defaultStation(),
    [config.station],
  );
  const platform = stationPlatform(station);
  const drone = platform === "px4";
  const layoutManager = useLayoutManager();
  const { getCurrentLayoutState } = useCurrentLayoutActions();
  const layoutId = useCurrentLayoutSelector(selectedLayoutIdSelector);
  const [selected, setSelected] = useState(drone ? "takeoff" : "cube");
  const [boxEditMode, setBoxEditMode] = useState<"translate" | "scale">(
    "translate",
  );
  const editorOwner = useRef({});
  const [past, setPast] = useState<Station[]>([]);
  const [future, setFuture] = useState<Station[]>([]);
  const [notice, setNotice] = useState("");
  const [runtime, setRuntime] = useState<SimulationRuntime>();
  const [runtimeError, setRuntimeError] = useState("");
  const [taskId, setTaskId] = useState(config.executionTaskId ?? "");
  const [task, setTask] = useState<SimulationTask>();
  const [taskHistory, setTaskHistory] = useState<SimulationTask[]>([]);
  const [planTask, setPlanTask] = useState<DronePlanTask>();
  const [planSubmitting, setPlanSubmitting] = useState(false);
  const [planError, setPlanError] = useState("");
  const planController = useRef<AbortController>();
  const [historyError, setHistoryError] = useState("");
  const [checkingTask, setCheckingTask] = useState(true);
  const [executionError, setExecutionError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [sceneSource, setSceneSource] = useState<SceneMode>();
  const [sceneError, setSceneError] = useState("");
  const [sceneStatusError, setSceneStatusError] = useState("");
  const [switchingScene, setSwitchingScene] = useState(false);
  const sceneController = useRef<AbortController>();
  const sceneRevision = useRef(0);
  const submissionController = useRef<AbortController>();
  const cancellationController = useRef<AbortController>();
  const rejectedTaskId = useRef("");
  const fileInput = useRef<HTMLInputElement>(null);
  const latestTaskForImport = useRef({ taskId, task, checkingTask, submitting, cancelling });
  latestTaskForImport.current = { taskId, task, checkingTask, submitting, cancelling };
  const planCurrent =
    config.previewPlanId != undefined &&
    JSON.stringify(config.previewPlanStation) === JSON.stringify(station);
  const planValid =
    planCurrent &&
    planTask != undefined &&
    planTask.id === config.previewPlanId &&
    planTask.status === "succeeded" &&
    planTask.report?.valid === true &&
    !planTask.report.flight_control;
  const egoNeedsPreview = drone && station.flight?.planner === "ego";
  const previewPlanId =
    planCurrent &&
    planTask != undefined &&
    planTask.id === config.previewPlanId &&
    !taskIsActive(planTask) &&
    planTask.report?.flight_control === false
      ? config.previewPlanId
      : undefined;
  useEffect(() => {
    if (!drone || !config.previewPlanId || planSubmitting) {
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const lookup = async () => {
      try {
        const current = await requestSimulation<DronePlanTask>(
          `/plans/${encodeURIComponent(config.previewPlanId!)}`,
          controller.signal,
          undefined,
          "px4",
        );
        if (!controller.signal.aborted) {
          if (current.id !== config.previewPlanId) {
            throw new TaskRequestError("预演查询返回的 ID 不一致，请查询原预演。");
          }
          setPlanTask(current);
          setPlanError("");
          if (taskIsActive(current)) {
            timer = setTimeout(() => void lookup(), 1000);
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setPlanError(
            `预演状态未确认：${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }
    };
    void lookup();
    return () => {
      controller.abort();
      if (timer != undefined) {
        clearTimeout(timer);
      }
    };
  }, [drone, config.previewPlanId, planSubmitting, refresh]);
  useEffect(() => {
    if (!drone) {
      return;
    }
    const owner = editorOwner.current;
    setDroneEditor({
      owner,
      station,
      selectedId: selected,
      mode: boxEditMode,
      setMode: setBoxEditMode,
      enabled:
        sceneSource?.mode === "draft" &&
        !switchingScene &&
        !submitting &&
        !taskIsActive(task),
      select: setSelected,
      transform: (id, position, size) => {
        const next = transformObstacle(station, id, position, size);
        if (next === station) {
          return;
        }
        setPast((history) => [...history, station]);
        setFuture([]);
        setNotice("三维变换已写入草稿，可撤销或保存。");
        saveConfig({ station: next });
      },
    });
    return () => {
      clearDroneEditor(owner);
    };
  }, [
    drone,
    station,
    selected,
    boxEditMode,
    sceneSource?.mode,
    switchingScene,
    submitting,
    task,
    saveConfig,
  ]);
  useEffect(() => {
    const restoredId = config.executionTaskId ?? "";
    setTaskId(restoredId);
    setTask((previous) => (previous?.id === restoredId ? previous : undefined));
  }, [config.executionTaskId]);
  useEffect(() => {
    const controller = new AbortController();
    void requestSimulation<SimulationRuntime>(
      "/runtime",
      controller.signal,
      undefined,
      platform,
    ).then(
      (value) => {
        if (!controller.signal.aborted) {
          setRuntime(value);
          setRuntimeError("");
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setRuntime(undefined);
          setRuntimeError(
            error instanceof Error ? error.message : String(error),
          );
        }
      },
    );
    return () => {
      controller.abort();
    };
  }, [refresh, platform]);
  useEffect(() => {
    if (!drone) {
      return;
    }
    const controller = new AbortController();
    void requestSimulation<{ tasks: SimulationTask[] }>(
      "/tasks",
      controller.signal,
      undefined,
      platform,
    ).then(
      (result) => {
        if (!controller.signal.aborted) {
          setTaskHistory(result.tasks);
          setHistoryError("");
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setHistoryError(
            `历史记录暂不可用：${error instanceof Error ? error.message : String(error)}`,
          );
        }
      },
    );
    return () => {
      controller.abort();
    };
  }, [drone, platform, refresh, task?.status]);
  useEffect(() => {
    if (submitting || (taskId !== "" && rejectedTaskId.current === taskId)) {
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const lookup = async () => {
      setCheckingTask(true);
      try {
        if (!taskId) {
          // Only a document without an execution selection restores the latest history.
          // A cleared ID is an explicit new draft, including while saveConfig updates.
          if (config.executionTaskId != undefined) {
            return;
          }
          const result = await requestSimulation<{ tasks: SimulationTask[] }>(
            "/tasks",
            controller.signal,
            undefined,
            platform,
          );
          if (controller.signal.aborted) {
            return;
          }
          const latest = latestSimulationTask(result.tasks);
          if (latest) {
            setTask(latest);
            setTaskId(latest.id);
            saveConfig({ executionTaskId: latest.id });
          }
          return;
        }
        const result = await requestSimulation<SimulationTask>(
          `/tasks/${encodeURIComponent(taskId)}`,
          controller.signal,
          undefined,
          platform,
        );
        if (controller.signal.aborted) {
          return;
        }
        if (result.id !== taskId) {
          throw new TaskRequestError(
            "查询返回的任务 ID 不一致，请保留原 ID 再查询。",
          );
        }
        setTask(result);
        setExecutionError("");
        if (taskIsActive(result)) {
          timer = setTimeout(() => {
            void lookup();
          }, 1500);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          const message =
            error instanceof Error ? error.message : String(error);
          setExecutionError(message);
          if (
            taskId &&
            error instanceof TaskRequestError &&
            error.status === 404
          ) {
            setTask({
              id: taskId,
              status: "failed",
              message: "服务端未找到原任务。可以显式发起一次新运行。",
              error: message,
            });
          } else if (taskId) {
            setTask(
              (previous) =>
                previous ?? {
                  id: taskId,
                  status: "unknown",
                  message: "状态未确认，请查询原任务。",
                },
            );
          }
        }
      } finally {
        if (!controller.signal.aborted) {
          setCheckingTask(false);
        }
      }
    };
    void lookup();
    return () => {
      controller.abort();
      if (timer != undefined) {
        clearTimeout(timer);
      }
    };
  }, [
    taskId,
    config.executionTaskId,
    submitting,
    refresh,
    saveConfig,
    platform,
  ]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const lookup = async () => {
      const revision = sceneRevision.current;
      try {
        const source = await requestSimulation<SceneMode>(
          "/scene-mode",
          controller.signal,
          undefined,
          platform,
        );
        if (
          !controller.signal.aborted &&
          revision === sceneRevision.current &&
          !sceneController.current
        ) {
          setSceneSource(source);
          setSceneStatusError("");
        }
      } catch (error) {
        if (!controller.signal.aborted && revision === sceneRevision.current) {
          setSceneStatusError(
            `三维状态暂未确认：${error instanceof Error ? error.message : String(error)}`,
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(() => {
            void lookup();
          }, 1500);
        }
      }
    };
    void lookup();
    return () => {
      controller.abort();
      if (timer != undefined) {
        clearTimeout(timer);
      }
    };
  }, [refresh, platform]);
  useEffect(() => {
    if (sceneSource?.mode !== "draft" || switchingScene) {
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void previewStation(station, controller.signal, previewPlanId).then(
        () => {
          if (!controller.signal.aborted) {
            setSceneError("");
          }
        },
        (error: unknown) => {
          if (!controller.signal.aborted) {
            setSceneError(
              `预览保留上次有效场景，草稿仍可继续编辑：${error instanceof Error ? error.message : String(error)}`,
            );
          }
        },
      );
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [station, sceneSource?.mode, switchingScene, previewPlanId]);
  const changeScene = async (
    mode: "draft" | "task",
    draft = station,
    selectedTaskId = taskId,
  ) => {
    sceneController.current?.abort();
    const controller = new AbortController();
    sceneController.current = controller;
    sceneRevision.current += 1;
    setSwitchingScene(true);
    setSceneError("");
    try {
      const source =
        mode === "draft"
          ? ({ mode, station: draft } as const)
          : ({ mode, taskId: selectedTaskId } as const);
      const selectedSource = await selectScene(
        source,
        controller.signal,
        platform,
      );
      if (!controller.signal.aborted) {
        setSceneSource(selectedSource);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setSceneError(
          `切换未完成，保留当前画面：${error instanceof Error ? error.message : String(error)}`,
        );
      }
    } finally {
      if (!controller.signal.aborted) {
        sceneController.current = undefined;
        setSwitchingScene(false);
      }
    }
  };
  useEffect(
    () => () => {
      submissionController.current?.abort();
      cancellationController.current?.abort();
      sceneController.current?.abort();
      planController.current?.abort();
    },
    [],
  );
  const startSimulation = async () => {
    if (egoNeedsPreview && !planValid) {
      setPlanError("请先对当前草稿完成有效的 EGO 预演。");
      return;
    }
    if (
      runtime?.ready !== true ||
      checkingTask ||
      submissionController.current ||
      taskIsActive(task)
    ) {
      return;
    }
    const id = crypto.randomUUID();
    const controller = new AbortController();
    rejectedTaskId.current = "";
    submissionController.current = controller;
    setSubmitting(true);
    setExecutionError("");
    setTaskId(id);
    setTask({
      id,
      status: "submitting",
      submittedAt: new Date().toISOString(),
      station,
    });
    // Save the ID before POST. A lost response must query this ID, never submit again.
    saveConfig({ executionTaskId: id });
    // The template must not replace this task selection when the page reloads.
    const url = new URL(window.location.href);
    url.searchParams.delete("layoutUrl");
    window.history.replaceState(window.history.state, "", url);
    try {
      const result = await requestSimulation<SimulationTask>(
        "/tasks",
        controller.signal,
        {
          taskId: id,
          station,
          ...(egoNeedsPreview ? { planId: config.previewPlanId } : {}),
        },
        platform,
      );
      if (!controller.signal.aborted) {
        if (result.id !== id) {
          throw new TaskRequestError(
            "提交响应的任务 ID 不一致，请查询原任务。",
          );
        }
        setTask(result);
        sceneRevision.current += 1;
        setSceneSource({
          mode: "task",
          taskId: id,
          phase: result.phase,
          status: result.status,
        });
        setSceneError("");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        const message = error instanceof Error ? error.message : String(error);
        const rejected =
          error instanceof TaskRequestError &&
          [400, 422].includes(error.status ?? 0);
        if (rejected) {
          rejectedTaskId.current = id;
        }
        setTask({
          id,
          status: rejected ? "failed" : "unknown",
          message: rejected
            ? "执行器拒绝了当前草稿。请按错误提示修改。"
            : "提交结果未确认，请查询原任务；不会自动重新提交。",
          error: message,
          station,
        });
        setExecutionError(message);
      }
    } finally {
      submissionController.current = undefined;
      if (!controller.signal.aborted) {
        setSubmitting(false);
      }
    }
  };
  const startPlan = async () => {
    if (
      planController.current ||
      planSubmitting ||
      taskIsActive(planTask) ||
      taskIsActive(task)
    ) {
      return;
    }
    const id = crypto.randomUUID();
    const controller = new AbortController();
    planController.current = controller;
    setPlanSubmitting(true);
    setPlanError("");
    setPlanTask({
      id,
      status: "pending",
      message: "正在提交 EGO 场景模型预演",
    });
    saveConfig({ previewPlanId: id, previewPlanStation: station });
    const url = new URL(window.location.href);
    url.searchParams.delete("layoutUrl");
    window.history.replaceState(window.history.state, "", url);
    try {
      const submitted = await requestSimulation<DronePlanTask>(
        "/plans",
        controller.signal,
        { taskId: id, station },
        "px4",
      );
      if (!controller.signal.aborted) {
        if (submitted.id !== id) {
          throw new TaskRequestError("预演响应的 ID 不一致，请查询原预演。");
        }
        setPlanTask(submitted);
        // Changing the player source can remount this panel. Submit the saved
        // plan ID first so a remount queries that job rather than aborting it.
        await changeScene("draft");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setPlanError(error instanceof Error ? error.message : String(error));
        const rejected =
          error instanceof TaskRequestError &&
          [400, 422].includes(error.status ?? 0);
        setPlanTask({
          id,
          status: rejected ? "failed" : "unknown",
          message: rejected
            ? "预演请求被拒绝，请修改草稿。"
            : "预演提交状态未确认，请查询预演。",
        });
      }
    } finally {
      if (!controller.signal.aborted) {
        setPlanSubmitting(false);
      }
      planController.current = undefined;
    }
  };
  const cancelSimulation = async (
    action: "cancel" | "return-home" = "cancel",
  ) => {
    if (!taskId || cancellationController.current) {
      return;
    }
    const controller = new AbortController();
    cancellationController.current = controller;
    setCancelling(true);
    setExecutionError("");
    try {
      const result = await requestSimulation<SimulationTask>(
        `/tasks/${encodeURIComponent(taskId)}/${action}`,
        controller.signal,
        {},
        platform,
      );
      if (!controller.signal.aborted) {
        setTask(result);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setExecutionError(
          `${action === "return-home" ? "返航" : "取消"}结果未确认，请查询原任务：${error instanceof Error ? error.message : String(error)}`,
        );
      }
    } finally {
      cancellationController.current = undefined;
      if (!controller.signal.aborted) {
        setCancelling(false);
        setRefresh((value) => value + 1);
      }
    }
  };
  const node = station.nodes.find((item) => item.id === selected);
  const blocked = descendants(selected, station.nodes);
  const targets = station.nodes.filter((item) => item.kind === "target");
  const warnings = programWarnings(station);
  const videoUrl = simulationArtifactUrl(task?.artifacts?.video);
  const reportUrl = simulationArtifactUrl(task?.artifacts?.report);
  const replayUrl = drone
    ? simulationReplayUrl(task?.artifacts?.mcap, window.location.origin)
    : undefined;
  const commit = (next: Station, detachTask = false) => {
    setNotice("");
    setPast((history) => [...history, station]);
    setFuture([]);
    if (detachTask) {
      setTaskId("");
      setTask(undefined);
      setExecutionError("");
      rejectedTaskId.current = "";
    }
    saveConfig({ station: next, ...(detachTask ? { executionTaskId: "" } : {}) });
  };
  const copyTask = () => {
    if (checkingTask || submitting || cancelling || taskIsActive(task)) {
      return;
    }
    const next = copyStation(task?.station ?? station);
    setPast((history) => [...history, station]);
    setFuture([]);
    setTaskId("");
    setTask(undefined);
    setExecutionError("");
    rejectedTaskId.current = "";
    saveConfig({ station: next, executionTaskId: "" });
    setSelected(
      drone
        ? "takeoff"
        : next.nodes.some((item) => item.id === "place")
          ? "place"
          : "",
    );
    setNotice(
      drone
        ? "已复制为独立草稿。修改航点 XYZ 或速度，再显式运行；原任务记录保持。"
        : "已复制为独立草稿。修改放料坐标系 X/Y，再显式运行；原任务记录保持。",
    );
    void changeScene("draft", next);
  };
  const downloadDocument = (recipe: boolean) => {
    try {
      const content = recipe ? exportStationRecipe(station) : exportStation(station);
      const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = drone ? "drone-station.json"
        : recipe || station.recipeDocument ? "so101-recipe.json" : "so101-station.json";
      link.click();
      setTimeout(() => { URL.revokeObjectURL(url); }, 1000);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "配方导出失败，当前草稿保留。");
    }
  };
  const loadWorkspaceSample = (sample: "x-plus20" | "x-minus20") => {
    if (drone || checkingTask || submitting || cancelling || taskIsActive(task)) {
      return;
    }
    const next = workspaceStationSample(sample);
    setPast((history) => [...history, station]);
    setFuture([]);
    setTaskId("");
    setTask(undefined);
    setExecutionError("");
    rejectedTaskId.current = "";
    saveConfig({ station: next, executionTaskId: "" });
    setSelected("cube");
    setNotice("已载入独立草稿，尚未运行。修改后需重新验证，原任务记录保留。");
    void changeScene("draft", next);
  };
  const changeNode = (patch: Partial<StationNode>) => {
    commit({
      ...station,
      nodes: station.nodes.map((item) =>
        item.id === selected ? { ...item, ...patch } : item,
      ),
    });
  };
  const changeStep = (id: string, patch: Partial<Instruction>) => {
    commit({
      ...station,
      program: station.program.map((step) =>
        step.id === id ? { ...step, ...patch } : step,
      ),
    });
  };
  const addNode = (kind: Kind) => {
    const id = crypto.randomUUID();
    commit({
      ...station,
      nodes: [
        ...station.nodes,
        {
          id,
          kind,
          name: `${stationKindLabel(kind, platform)} ${station.nodes.filter((item) => item.kind === kind).length + 1}`,
          parent: "world",
          position: drone
            ? kind === "obstacle"
              ? [1.5, 0, 1]
              : [1, 1, kind === "target" ? 2 : 0]
            : [0.2, 0, 0.05],
          ...(drone && kind === "obstacle" ? { size: [1, 1, 2] as Vec3 } : {}),
        },
      ],
    });
    setSelected(id);
  };
  const shift = (index: number, offset: number) => {
    const program = [...station.program];
    const destination = index + offset;
    if (!program[index] || !program[destination]) {
      return;
    }
    [program[index], program[destination]] = [
      program[destination],
      program[index],
    ];
    commit({ ...station, program });
  };
  const renderTree = (parent: string, depth: number): React.ReactNode =>
    station.nodes
      .filter((item) => item.parent === parent)
      .map((item) => (
        <div key={item.id}>
          <button
            className={classes.object}
            style={{ paddingLeft: 6 + depth * 12 }}
            aria-pressed={selected === item.id}
            onClick={() => {
              setSelected(item.id);
            }}
          >
            <span style={{ color: COLORS[item.kind] }}>● </span>
            {item.name} <small>({stationKindLabel(item.kind, platform)})</small>
          </button>
          {renderTree(item.id, depth + 1)}
        </div>
      ));
  return (
    <>
      <PanelToolbar />
      <div className={classes.content} style={{ containerType: "inline-size" }}>
        <div className={classes.row}>
          <Typography variant="h6">场景与程序</Typography>
          <Button
            size="small"
            disabled={past.length === 0}
            onClick={() => {
              const previous = past.at(-1);
              if (previous) {
                setNotice("");
                setPast(past.slice(0, -1));
                setFuture([...future, station]);
                saveConfig({ station: previous });
              }
            }}
          >
            撤销
          </Button>
          <Button
            size="small"
            disabled={future.length === 0}
            onClick={() => {
              const next = future.at(-1);
              if (next) {
                setPast([...past, station]);
                setNotice("");
                setFuture(future.slice(0, -1));
                saveConfig({ station: next });
              }
            }}
          >
            重做
          </Button>
        </div>
        <div className={classes.row}>
          <Button
            size="small"
            variant="outlined"
            disabled={
              checkingTask || submitting || cancelling || taskIsActive(task)
            }
            onClick={copyTask}
          >
            复制为新任务
          </Button>
          <Typography variant="caption" color="text.secondary">
            {taskIsActive(task) || submitting || cancelling
              ? "运行结束或取消后可复制；当前任务仍可取消。"
              : task?.station
                ? "复制来源：当前任务的提交快照"
                : "复制来源：当前编辑草稿"}
          </Typography>
        </div>
        <Typography variant="body2" color="text.secondary">
          编辑草稿随工作台布局保存。三维画面可切换编辑预览或当前任务。
        </Typography>
        <div role="region" aria-label="三维画面来源">
          <div className={classes.row}>
            <Button
              size="small"
              variant={sceneSource?.mode === "draft" ? "contained" : "outlined"}
              aria-pressed={sceneSource?.mode === "draft"}
              disabled={switchingScene}
              onClick={() => {
                void changeScene("draft");
              }}
            >
              编辑预览
            </Button>
            <Button
              size="small"
              variant={sceneSource?.mode === "task" ? "contained" : "outlined"}
              aria-pressed={sceneSource?.mode === "task"}
              disabled={!taskId || switchingScene || submitting}
              onClick={() => {
                void changeScene("task");
              }}
            >
              当前任务
            </Button>
            {!drone && (
              <Button
                size="small"
                component="a"
                href="/so101"
                target="_blank"
                rel="noreferrer"
              >
                历史回放 ↗
              </Button>
            )}
          </div>
          <Typography
            variant="body2"
            style={{ overflowWrap: "anywhere", marginTop: 8 }}
          >
            {sceneModeLabel(sceneSource)}
          </Typography>
          {sceneSource?.mode === "task" && (
            <Typography variant="caption" color="text.secondary">
              {sceneSource.status
                ? taskStatusLabel(sceneSource.status)
                : "等待任务状态"}
              {sceneSource.phase ? ` · ${sceneSource.phase}` : ""}
              {sceneSource.simulation_s != undefined
                ? ` · ${sceneSource.simulation_s.toFixed(2)} s`
                : ""}
              {" · 编辑只保存草稿；取消或结束后保留最后实际姿态。"}
            </Typography>
          )}
          {sceneStatusError && (
            <Alert severity="warning" style={{ marginTop: 8 }}>
              {sceneStatusError}
            </Alert>
          )}
          {sceneError && (
            <Alert severity="warning" style={{ marginTop: 8 }}>
              {sceneError}
            </Alert>
          )}
        </div>
        <TextField
          label="工作站名称"
          size="small"
          value={station.name}
          onChange={(event) => {
            commit({ ...station, name: event.target.value });
          }}
        />
        {!drone && (
          <div role="region" aria-label="SO101 开发工位样例">
            <Typography variant="subtitle2">开发工位样例</Typography>
            <div className={classes.row}>
              <Button
                size="small"
                variant="outlined"
                disabled={checkingTask || submitting || cancelling || taskIsActive(task)}
                onClick={() => {
                  loadWorkspaceSample("x-plus20");
                }}
              >
                载入 X+20mm 布局
              </Button>
              <Button
                size="small"
                variant="outlined"
                disabled={checkingTask || submitting || cancelling || taskIsActive(task)}
                onClick={() => {
                  loadWorkspaceSample("x-minus20");
                }}
              >
                载入 X−20mm 布局
              </Button>
            </div>
            <Typography variant="caption" color="text.secondary">
              每个样例仅验证过指定点位。加载只改草稿；修改后重新规划并运行。
            </Typography>
            {station.execution !== undefined && (
              <Alert severity="info" style={{ marginTop: 8 }}>
                开发工位：红盘与取料高位随 JSON 保存。声明区域是定位先验，尚未证明整个区域都能抓放。
              </Alert>
            )}
            {station.recipeDocument && (
              <Alert severity="info" style={{ marginTop: 8 }}>
                已载入可编辑工位配方。历史验收仅作来源引用；当前草稿须重新运行。
              </Alert>
            )}
          </div>
        )}
        <div className={classes.row}>
          <Button
            size="small"
            variant="outlined"
            onClick={async () => {
              if (!layoutId) {
                setNotice("请先创建工作台布局，或导出 JSON 保存草稿。");
                return;
              }
              try {
                setNotice("正在保存草稿…");
                const current = getCurrentLayoutState().selectedLayout;
                await layoutManager.updateLayout({
                  id: layoutId,
                  name: current?.name,
                  data: current?.data,
                });
                await layoutManager.overwriteLayout({ id: layoutId });
                const url = new URL(window.location.href);
                url.searchParams.delete("layoutUrl");
                window.history.replaceState(window.history.state, "", url);
                setNotice(
                  "草稿与当前布局已保存，刷新页面可继续编辑。也可导出 JSON 备份。",
                );
              } catch (error) {
                setNotice(
                  `布局保存失败，草稿仍可导出：${error instanceof Error ? error.message : String(error)}`,
                );
              }
            }}
          >
            保存草稿
          </Button>
          <Button
            size="small"
            onClick={() => {
              downloadDocument(false);
            }}
          >
            导出 JSON
          </Button>
          {!drone && (
            <Button size="small" onClick={() => { downloadDocument(true); }}>
              导出工位配方
            </Button>
          )}
          <Button size="small"
            disabled={checkingTask || submitting || cancelling || taskIsActive(task)}
            onClick={() => fileInput.current?.click()}>
            导入 JSON
          </Button>
          <input
            hidden
            ref={fileInput}
            type="file"
            accept=".json,application/json"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) {
                return;
              }
              if (checkingTask || submitting || cancelling || taskIsActive(task)) {
                setNotice("任务运行中，请结束或停止后再导入；原任务与取消入口保留。");
                return;
              }
              try {
                const text = await file.text();
                const latest = latestTaskForImport.current;
                if (latest.taskId !== taskId || latest.checkingTask || latest.submitting
                    || latest.cancelling || taskIsActive(latest.task)
                    || submissionController.current || cancellationController.current) {
                  setNotice("读取期间任务状态已变化，请结束任务后重新导入；原任务与取消入口保留。");
                  return;
                }
                const imported = importStation(JSON.parse(text));
                if (stationPlatform(imported.station) !== platform) {
                  throw new Error(
                    "文件与当前机器人类型不同，请在对应工作台入口导入；当前草稿未改变。",
                  );
                }
                commit(imported.station, imported.station.recipeDocument !== undefined);
                setSelected(imported.station.nodes[0]?.id ?? "");
                setNotice(
                  imported.warnings.length > 0
                    ? `导入完成，注意：${imported.warnings.join(" ")}`
                    : "工作站已导入，可以继续编辑。",
                );
              } catch (error) {
                setNotice(
                  error instanceof Error
                    ? error.message
                    : "无法读取 JSON，当前草稿未改变。",
                );
              }
            }}
          />
        </div>
        {notice && (
          <Alert
            severity="info"
            onClose={() => {
              setNotice("");
            }}
          >
            {notice}
          </Alert>
        )}
        <div className={classes.workspace}>
          <div className={classes.tree} aria-label="工作站对象树">
            <Typography variant="caption">世界坐标系</Typography>
            {renderTree("world", 0)}
          </div>
          <ScenePreview
            station={station}
            selected={selected}
            select={setSelected}
          />
        </div>
        {drone && (
          <div role="region" aria-label="三维障碍编辑">
            <div className={classes.row}>
              <Button
                size="small"
                variant={boxEditMode === "translate" ? "contained" : "outlined"}
                aria-pressed={boxEditMode === "translate"}
                disabled={taskIsActive(task) || submitting}
                onClick={() => {
                  setBoxEditMode("translate");
                  if (sceneSource?.mode !== "draft") {
                    void changeScene("draft");
                  }
                }}
              >
                三维移动障碍
              </Button>
              <Button
                size="small"
                variant={boxEditMode === "scale" ? "contained" : "outlined"}
                aria-pressed={boxEditMode === "scale"}
                disabled={taskIsActive(task) || submitting}
                onClick={() => {
                  setBoxEditMode("scale");
                  if (sceneSource?.mode !== "draft") {
                    void changeScene("draft");
                  }
                }}
              >
                三维缩放障碍
              </Button>
            </div>
            <Typography variant="caption" color="text.secondary">
              在三维场景点选障碍，拖动彩色轴调整位置或宽深高；松手写入草稿。
            </Typography>
          </div>
        )}
        <div className={classes.row}>
          {(["target", "frame", "object", "obstacle"] as const)
            .filter((kind) => !drone || kind !== "object")
            .map((kind) => (
              <Button
                size="small"
                key={kind}
                onClick={() => {
                  addNode(kind);
                }}
              >
                添加{stationKindLabel(kind, platform)}
              </Button>
            ))}
        </div>
        {node && (
          <>
            <TextField
              size="small"
              label="对象名称"
              value={node.name}
              onChange={(event) => {
                changeNode({ name: event.target.value });
              }}
            />
            {node.kind !== "tool" && (
              <TextField
                select
                size="small"
                label="所属坐标系（切换保持世界位置）"
                value={node.parent}
                onChange={(event) => {
                  commit(reparent(station, node.id, event.target.value));
                }}
              >
                <MenuItem value="world">世界坐标系</MenuItem>
                {station.nodes
                  .filter(
                    (item) => item.kind === "frame" && !blocked.has(item.id),
                  )
                  .map((frame) => (
                    <MenuItem key={frame.id} value={frame.id}>
                      {frame.name}
                    </MenuItem>
                  ))}
                {node.parent !== "world" &&
                  !station.nodes.some(
                    (item) => item.id === node.parent && item.kind === "frame",
                  ) && <MenuItem value={node.parent}>{node.parent}</MenuItem>}
              </TextField>
            )}
            {node.kind !== "tool" && (
              <div className={classes.fields}>
                {([0, 1, 2] as const).map((axis) => (
                  <TextField
                    key={axis}
                    size="small"
                    type="number"
                    label={`${["X", "Y", "Z"][axis]}（m）`}
                    value={node.position[axis]}
                    disabled={
                      axis === 2 &&
                      ((!drone && node.id === "place") ||
                        (drone && node.kind === "robot"))
                    }
                    slotProps={{ htmlInput: { step: drone ? 0.1 : 0.005 } }}
                    onChange={(event) => {
                      if (event.target.value === "") {
                        return;
                      }
                      const value = Number(event.target.value);
                      if (!Number.isFinite(value)) {
                        return;
                      }
                      const position: Vec3 = [...node.position];
                      position[axis] = value;
                      changeNode({ position });
                    }}
                  />
                ))}
              </div>
            )}
            {drone && node.kind === "obstacle" && (
              <>
                <TextField
                  select
                  size="small"
                  label="障碍启用状态"
                  value={node.enabled === false ? "disabled" : "enabled"}
                  onChange={(event) => {
                    changeNode({ enabled: event.target.value === "enabled" });
                  }}
                >
                  <MenuItem value="enabled">启用，参与预演和碰撞检查</MenuItem>
                  <MenuItem value="disabled">停用，保留草稿配置</MenuItem>
                </TextField>
                <div className={classes.fields}>
                  {([0, 1, 2] as const).map((axis) => (
                    <TextField
                      key={axis}
                      size="small"
                      type="number"
                      label={`${["宽", "深", "高"][axis]}（m）`}
                      value={(node.size ?? [1, 1, 2])[axis]}
                      slotProps={{ htmlInput: { step: 0.1, min: 0.1 } }}
                      onChange={(event) => {
                        const value = Number(event.target.value);
                        if (!Number.isFinite(value) || value <= 0) {
                          return;
                        }
                        const size: Vec3 = [...(node.size ?? [1, 1, 2])];
                        size[axis] = value;
                        changeNode({ size });
                      }}
                    />
                  ))}
                </div>
                <TextField
                  select
                  size="small"
                  label="障碍运动"
                  value={node.motion ? "linear_ping_pong" : "static"}
                  onChange={(event) => {
                    changeNode({
                      motion:
                        event.target.value === "linear_ping_pong"
                          ? {
                              type: "linear_ping_pong",
                              axis: [0, 1, 0],
                              distance_m: 2,
                              speed_m_s: 0.3,
                            }
                          : undefined,
                    });
                  }}
                >
                  <MenuItem value="static">静态 Box</MenuItem>
                  <MenuItem value="linear_ping_pong">往返移动立柱</MenuItem>
                </TextField>
                {node.motion && (
                  <>
                    <div className={classes.fields}>
                      {([0, 1, 2] as const).map((axis) => (
                        <TextField
                          key={axis}
                          size="small"
                          type="number"
                          label={`运动方向 ${["X", "Y", "Z"][axis]}`}
                          value={node.motion!.axis[axis]}
                          slotProps={{ htmlInput: { step: 1 } }}
                          onChange={(event) => {
                            const value = Number(event.target.value);
                            if (!Number.isFinite(value) || !node.motion) {
                              return;
                            }
                            const direction: Vec3 = [...node.motion.axis];
                            direction[axis] = value;
                            changeNode({
                              motion: { ...node.motion, axis: direction },
                            });
                          }}
                        />
                      ))}
                    </div>
                    <div className={classes.row}>
                      {(["distance_m", "speed_m_s"] as const).map((key) => (
                        <TextField
                          key={key}
                          size="small"
                          type="number"
                          label={
                            key === "distance_m"
                              ? "往返行程（m）"
                              : "立柱速度（m/s）"
                          }
                          value={node.motion![key]}
                          slotProps={{ htmlInput: { min: 0.05, step: 0.1 } }}
                          onChange={(event) => {
                            const value = Number(event.target.value);
                            if (
                              Number.isFinite(value) &&
                              value > 0 &&
                              node.motion
                            ) {
                              changeNode({
                                motion: { ...node.motion, [key]: value },
                              });
                            }
                          }}
                        />
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
            {!drone && node.id === "place" && (
              <Typography variant="caption" color="text.secondary">
                修改 X/Y
                会同步移动蓝盘、释放点和脱离点。本轮保持盘高、盘尺寸和八步程序，执行范围由下方执行器说明。
              </Typography>
            )}
            {drone && node.kind === "robot" && (
              <Typography variant="caption" color="text.secondary">
                起点位于地面。X/Y 设置起飞位置，飞行高度在航点中设置。
              </Typography>
            )}
            <Typography variant="caption">
              {node.kind === "tool"
                ? "夹爪是机械臂附件，此草稿尚未定义 TCP。"
                : `世界位置：${worldPosition(node, station.nodes)
                    .map((x) => x.toFixed(3))
                    .join(", ")} m · 坐标轴与世界平行`}
            </Typography>
            {node.kind !== "robot" && node.kind !== "tool" && (
              <Button
                size="small"
                color="error"
                onClick={() => {
                  commit(removeNode(station, node.id));
                  setSelected("base");
                  setNotice(
                    "对象及其子节点已移除；引用它的步骤保留，需重新选择目标。可撤销。",
                  );
                }}
              >
                删除对象及子节点
              </Button>
            )}
          </>
        )}
        <Divider />
        <Typography variant="subtitle1">
          {drone ? "飞行程序" : "抓放程序"}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          动作引用目标点。改名不会丢失引用；虚线不表示规划成功。
        </Typography>
        {drone && (
          <>
            <Typography variant="caption" color="text.secondary">
              X 向东、Y 向北、Z 向上，单位米。起飞高度来自起飞步骤引用的航点 Z。
            </Typography>
            <div className={classes.row}>
              <TextField
                size="small"
                type="number"
                label="速度上限（m/s）"
                value={station.flight?.speed_m_s ?? 1}
                slotProps={{ htmlInput: { min: 1, max: 5, step: 0.1 } }}
                onChange={(event) => {
                  const speed = Number(event.target.value);
                  if (Number.isFinite(speed) && speed >= 1 && speed <= 5) {
                    commit({
                      ...station,
                      flight: {
                        ...station.flight,
                        planner: station.flight?.planner ?? "waypoint",
                        speed_m_s: speed,
                      },
                    });
                  }
                }}
              />
              <TextField
                select
                size="small"
                label="路径方式"
                value={station.flight?.planner ?? "waypoint"}
                onChange={(event) => {
                  commit({
                    ...station,
                    flight: {
                      ...station.flight,
                      speed_m_s: station.flight?.speed_m_s ?? 1,
                      planner:
                        event.target.value === "ego" ? "ego" : "waypoint",
                    },
                  });
                }}
              >
                <MenuItem value="waypoint">按航点巡航</MenuItem>
                <MenuItem
                  value="ego"
                  disabled={
                    runtime?.executor?.planners?.includes("ego") !== true
                  }
                >
                  {runtime?.executor?.planners?.includes("ego") === true
                    ? "EGO-Swarm 自动绕障"
                    : "EGO-Swarm（执行器未就绪）"}
                </MenuItem>
              </TextField>
            </div>
            <Typography variant="subtitle2">飞行验收参数</Typography>
            <Typography variant="caption" color="text.secondary">
              留空沿用执行器默认值。最低巡航速度只适用于有足够距离的巡航段；持续时长仅在填写最低巡航速度时参与验收。
            </Typography>
            <div className={classes.fields}>
              {(
                [
                  ["max_altitude_m", "高度上限（m）"],
                  ["position_tolerance_m", "到点误差上限（m）"],
                  ["min_clearance_m", "最小机体净空（m）"],
                  ["min_cruise_speed_m_s", "最低巡航速度（m/s）"],
                  ["min_cruise_duration_s", "最低巡航持续时长（s）"],
                ] as const
              ).map(([key, label]) => (
                <TextField
                  key={key}
                  size="small"
                  type="number"
                  label={label}
                  value={station.flight?.acceptance?.[key] ?? ""}
                  slotProps={{ htmlInput: { min: 0, step: 0.05 } }}
                  onChange={(event) => {
                    const value =
                      event.target.value === ""
                        ? undefined
                        : Number(event.target.value);
                    if (
                      value != undefined &&
                      (!Number.isFinite(value) || value < 0)
                    ) {
                      return;
                    }
                    const acceptance = { ...station.flight?.acceptance };
                    if (value == undefined) {
                      delete acceptance[key];
                    } else {
                      acceptance[key] = value;
                    }
                    commit({
                      ...station,
                      flight: {
                        speed_m_s: station.flight?.speed_m_s ?? 1,
                        planner: station.flight?.planner ?? "waypoint",
                        ...station.flight,
                        acceptance,
                      },
                    });
                  }}
                />
              ))}
            </div>
            <Typography variant="subtitle2">深度感知故障注入</Typography>
            <Typography variant="caption" color="text.secondary">
              仅作用于仿真深度通道。丢帧 0.1 表示 10%；延迟保留原采集时间。
            </Typography>
            <div className={classes.fields}>
              {(
                [
                  ["depth_drop_probability", "深度丢帧比例（0–1）", 0],
                  ["depth_delay_ms", "深度延迟（ms）", 0],
                  ["seed", "随机种子", 1],
                ] as const
              ).map(([key, label, fallback]) => (
                <TextField
                  key={key}
                  size="small"
                  type="number"
                  label={label}
                  value={station.flight?.sensors?.[key] ?? fallback}
                  slotProps={{
                    htmlInput: {
                      min: 0,
                      step: key === "depth_drop_probability" ? 0.01 : 1,
                    },
                  }}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    if (
                      !Number.isFinite(value) ||
                      value < 0 ||
                      (key === "depth_drop_probability" && value > 1) ||
                      (key === "seed" &&
                        (!Number.isInteger(value) || value > 4294967295))
                    ) {
                      return;
                    }
                    commit({
                      ...station,
                      flight: {
                        speed_m_s: station.flight?.speed_m_s ?? 1,
                        planner: station.flight?.planner ?? "waypoint",
                        ...station.flight,
                        sensors: { ...station.flight?.sensors, [key]: value },
                      },
                    });
                  }}
                />
              ))}
            </div>
            <Typography variant="caption" color="text.secondary">
              {station.flight?.planner === "ego"
                ? "EGO-Swarm 使用 Gazebo 理想定位和深度图，结果以本次仿真报告为准。"
                : "航点模式不自动绕障；请使用空旷仿真场景。"}
            </Typography>
          </>
        )}
        {station.program.map((step, index) => (
          <div className={classes.step} key={step.id}>
            <Typography variant="body2">{index + 1}.</Typography>
            <TextField
              select
              size="small"
              aria-label={`步骤 ${index + 1} 动作`}
              value={step.action}
              onChange={(event) => {
                const action = event.target.value as Instruction["action"];
                changeStep(step.id, {
                  action,
                  ...(drone
                    ? {
                        target:
                          action === "return_home"
                            ? "home"
                            : actionNeedsTarget(action)
                              ? step.target
                              : "",
                      }
                    : {}),
                });
              }}
            >
              {stationActions(platform).map((value) => (
                <MenuItem key={value} value={value}>
                  {ACTION_LABELS[value]}
                </MenuItem>
              ))}
            </TextField>
            {actionNeedsTarget(step.action) && (
              <TextField
                select
                size="small"
                label={`步骤 ${index + 1} 目标`}
                value={
                  targets.some((target) => target.id === step.target)
                    ? step.target
                    : ""
                }
                onChange={(event) => {
                  changeStep(step.id, { target: event.target.value });
                }}
                style={{ minWidth: 120, flex: 1 }}
              >
                <MenuItem value="">选择目标</MenuItem>
                {targets.map((target) => (
                  <MenuItem key={target.id} value={target.id}>
                    {target.name}
                  </MenuItem>
                ))}
              </TextField>
            )}
            {step.action === "wait" && (
              <TextField
                size="small"
                type="number"
                label={`步骤 ${index + 1} 等待秒数`}
                value={step.seconds}
                style={{ width: 100 }}
                onChange={(event) => {
                  const seconds = Number(event.target.value);
                  if (Number.isFinite(seconds) && seconds >= 0) {
                    changeStep(step.id, { seconds });
                  }
                }}
              />
            )}
            <Button
              size="small"
              aria-label={`上移步骤 ${index + 1}`}
              disabled={index === 0}
              onClick={() => {
                shift(index, -1);
              }}
            >
              ↑
            </Button>
            <Button
              size="small"
              aria-label={`下移步骤 ${index + 1}`}
              disabled={index === station.program.length - 1}
              onClick={() => {
                shift(index, 1);
              }}
            >
              ↓
            </Button>
            <Button
              size="small"
              aria-label={`删除步骤 ${index + 1}`}
              onClick={() => {
                commit({
                  ...station,
                  program: station.program.filter(
                    (item) => item.id !== step.id,
                  ),
                });
              }}
            >
              删除
            </Button>
          </div>
        ))}
        <Button
          variant="outlined"
          onClick={() => {
            commit({
              ...station,
              program: [
                ...station.program,
                {
                  id: crypto.randomUUID(),
                  action: drone ? "waypoint" : "move",
                  target: targets[0]?.id ?? "",
                  seconds: 1,
                },
              ],
            });
          }}
        >
          添加步骤
        </Button>
        {warnings.map((warning) => (
          <Alert severity="warning" key={warning}>
            {warning}
          </Alert>
        ))}
        <TextField
          label="工作站备注"
          multiline
          minRows={2}
          value={station.notes}
          onChange={(event) => {
            commit({ ...station, notes: event.target.value });
          }}
        />
        <Divider />
        <Typography variant="subtitle1">规划与仿真</Typography>
        {egoNeedsPreview && (
          <div role="region" aria-label="EGO 起飞前预演">
            <Button
              variant="outlined"
              disabled={
                planSubmitting ||
                taskIsActive(planTask) ||
                taskIsActive(task) ||
                runtime?.executor?.planners?.includes("ego") !== true
              }
              onClick={() => {
                void startPlan();
              }}
            >
              {planSubmitting || taskIsActive(planTask)
                ? "EGO 正在计算预演…"
                : "EGO 起飞前预演"}
            </Button>
            {config.previewPlanId && (
              <Button
                size="small"
                onClick={() => {
                  setRefresh((value) => value + 1);
                }}
              >
                查询预演
              </Button>
            )}
            <Typography variant="body2" color="text.secondary">
              预演使用当前场景模型计算 EGO
              空间曲线，黄色为规划轨迹，红色为净空不足段。
              预演不派发飞行，也不代表真实深度已感知；编辑后需重新预演。
            </Typography>
            {config.previewPlanId && (
              <Typography
                variant="caption"
                style={{ overflowWrap: "anywhere" }}
              >
                预演 ID：{config.previewPlanId}
              </Typography>
            )}
            {config.previewPlanId && !planCurrent && (
              <Alert severity="warning">草稿已修改，旧预演已过期。</Alert>
            )}
            {planCurrent && planTask && (
              <Alert
                severity={
                  planValid
                    ? "success"
                    : planTask.status === "failed"
                      ? "warning"
                      : "info"
                }
              >
                {planValid
                  ? "当前草稿预演有效，可以起飞。"
                  : (planTask.report?.reason ??
                    planTask.message ??
                    taskStatusLabel(planTask.status))}
                {planTask.report?.min_clearance_m != undefined
                  ? ` 最小净空：${planTask.report.min_clearance_m.toFixed(3)} m。`
                  : ""}
              </Alert>
            )}
            {planError && <Alert severity="warning">{planError}</Alert>}
          </div>
        )}
        <Alert severity={runtime?.ready === true ? "info" : "warning"}>
          {runtimeError
            ? `执行器暂不可用：${runtimeError}`
            : (runtime?.message ?? "正在检查已有规划执行器…")}
        </Alert>
        {runtime?.capabilities && runtime.capabilities.length > 0 && (
          <Typography variant="caption" color="text.secondary">
            执行器支持：{runtime.capabilities.join("；")}
          </Typography>
        )}
        <Typography variant="body2" color="text.secondary">
          运行使用提交时的草稿快照，并自动显示该任务的实时三维。后续编辑不会改变已提交任务；取消或结束后保留最后实际姿态。
        </Typography>
        <div className={classes.row}>
          <Button
            variant="contained"
            disabled={
              runtime?.ready !== true ||
              checkingTask ||
              submitting ||
              taskIsActive(task) ||
              (egoNeedsPreview && !planValid)
            }
            onClick={() => {
              void startSimulation();
            }}
          >
            {drone ? "起飞并执行仿真" : "规划并运行仿真"}
          </Button>
          <Button
            size="small"
            disabled={
              submitting || cancelling || !taskId || !taskIsActive(task)
            }
            onClick={() => {
              void cancelSimulation();
            }}
          >
            {cancelling
              ? "正在发送请求…"
              : drone
                ? "停止并安全返回降落"
                : "取消任务"}
          </Button>
          {drone && (
            <Button
              size="small"
              disabled={
                submitting || cancelling || !taskId || !taskIsActive(task)
              }
              onClick={() => {
                void cancelSimulation("return-home");
              }}
            >
              返航降落
            </Button>
          )}
          <Button
            size="small"
            disabled={submitting}
            onClick={() => {
              rejectedTaskId.current = "";
              setRefresh((value) => value + 1);
            }}
          >
            {taskId ? "查询原任务" : "刷新执行器"}
          </Button>
        </div>
        {drone && (
          <>
            <Typography variant="body2">
              <a
                href={`${task && !taskIsActive(task) ? `/drone-diagnostics?taskId=${encodeURIComponent(task.id)}` : "/drone-diagnostics?"}${window.innerWidth < 600 ? "&mobile=1" : ""}`}
                target="_blank"
                rel="noreferrer"
              >
                打开历史飞行诊断
              </a>
            </Typography>
            <TextField
              select
              size="small"
              label="历史任务"
              value={
                taskHistory.some((item) => item.id === taskId) ? taskId : ""
              }
              disabled={submitting || cancelling || taskIsActive(task)}
              onChange={(event) => {
                const selectedTask = taskHistory.find(
                  (item) => item.id === event.target.value,
                );
                if (!selectedTask) {
                  return;
                }
                setTaskId(selectedTask.id);
                setTask(selectedTask);
                setExecutionError("");
                rejectedTaskId.current = "";
                saveConfig({ executionTaskId: selectedTask.id });
                void changeScene("task", station, selectedTask.id);
              }}
            >
              <MenuItem value="">选择一次已保存任务</MenuItem>
              {taskHistory.map((item) => (
                <MenuItem key={item.id} value={item.id}>
                  {item.submittedAt ?? item.id} · {taskStatusLabel(item.status)}{" "}
                  · {item.station?.name ?? item.id}
                </MenuItem>
              ))}
            </TextField>
            {historyError && <Alert severity="warning">{historyError}</Alert>}
          </>
        )}
        {executionError && <Alert severity="warning">{executionError}</Alert>}
        {taskId && (
          <Typography variant="caption" style={{ overflowWrap: "anywhere" }}>
            原任务 ID：{taskId}
          </Typography>
        )}
        {task && (
          <div role="region" aria-live="polite" aria-label="当前仿真任务">
            <Typography variant="subtitle2">
              {taskStatusLabel(task.status)}
              {task.phase ? ` · ${task.phase}` : ""}
            </Typography>
            {task.station && (
              <Typography variant="body2">
                提交的工作站：{task.station.name}
              </Typography>
            )}
            {task.submittedAt && (
              <Typography variant="caption">
                提交时间：{task.submittedAt}
              </Typography>
            )}
            {task.simulation_s != undefined && (
              <Typography variant="body2">
                仿真时间：{task.simulation_s.toFixed(2)} s
              </Typography>
            )}
            {task.message && (
              <Typography variant="body2">{task.message}</Typography>
            )}
            {task.error && (
              <Typography variant="body2" color="error">
                {task.error}
              </Typography>
            )}
            {videoUrl && (
              <>
                <Typography variant="subtitle2" style={{ marginTop: 8 }}>
                  本次任务录像
                </Typography>
                <video
                  src={videoUrl}
                  controls
                  preload="metadata"
                  style={{ width: "100%", maxHeight: 340 }}
                >
                  浏览器不支持内嵌录像，请使用下面的链接。
                </video>
                <Typography variant="body2">
                  <a href={videoUrl} target="_blank" rel="noreferrer">
                    打开本次录像
                  </a>
                </Typography>
              </>
            )}
            {reportUrl && (
              <Typography variant="body2">
                <a href={reportUrl} target="_blank" rel="noreferrer">
                  打开本次原始报告
                </a>
              </Typography>
            )}
            {replayUrl && (
              <Typography variant="body2">
                <a href={replayUrl} target="_blank" rel="noreferrer">
                  回看本次三维轨迹 ↗
                </a>
              </Typography>
            )}
            {drone && task.report && (
              <Typography variant="body2">
                飞行验收：{task.report.passed === true ? "通过" : "未通过"}
              </Typography>
            )}
            {!drone && task.report && (
              <Typography variant="body2">
                物理验收：{task.report.passed === true ? "通过" : "未通过"}；
                真实夹起：
                {task.report.grasp_success === true ? "是" : "否"}； 放置落定：
                {task.report.place_success === true ? "是" : "否"}； 安全停止：
                {task.report.safety_stop === true ? "是" : "否"}
              </Typography>
            )}
            {!drone && graspEvidenceLabel(task) && (
              <Typography variant="body2" data-testid="physical-grasp-evidence">
                {graspEvidenceLabel(task)}
              </Typography>
            )}
            {task.report && (
              <details>
                <summary>本次任务原始物理报告</summary>
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                    fontSize: 11,
                  }}
                >
                  {JSON.stringify(task.report, undefined, 2)}
                </pre>
              </details>
            )}
          </div>
        )}
        <details>
          <summary>借用的产品能力</summary>
          <Typography variant="body2">
            RoboDK：场景树、坐标系归属、目标引用和指令列表。Lichtblick：原生三维、WebSocket
            数据源、布局保存、录像与曲线。草稿采用普通 JSON，可手工修改。
          </Typography>
        </details>
      </div>
    </>
  );
}
RobotStation.panelType = "RobotStation";
RobotStation.defaultConfig = { station: defaultStation(), executionTaskId: "" };
export default Panel(RobotStation);
