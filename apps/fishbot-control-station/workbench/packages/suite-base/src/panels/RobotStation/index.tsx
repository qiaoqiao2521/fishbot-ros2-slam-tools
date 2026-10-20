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
import { useEffect, useRef, useState } from "react";
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

import {
  latestSimulationTask,
  requestSimulation,
  simulationArtifactUrl,
  taskIsActive,
  TaskRequestError,
  taskStatusLabel,
} from "./execution";
import type { SimulationRuntime, SimulationTask } from "./execution";
import {
  ACTION_LABELS,
  KIND_LABELS,
  defaultStation,
  descendants,
  exportStation,
  importStation,
  programWarnings,
  removeNode,
  reparent,
  worldPosition,
} from "./station";
import type { Instruction, Kind, Station, StationNode, Vec3 } from "./station";

type Config = { station?: Station; executionTaskId?: string };
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
    .filter((step) => step.action === "move")
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
  const station = config.station ?? defaultStation();
  const layoutManager = useLayoutManager();
  const { getCurrentLayoutState } = useCurrentLayoutActions();
  const layoutId = useCurrentLayoutSelector(selectedLayoutIdSelector);
  const [selected, setSelected] = useState("cube");
  const [past, setPast] = useState<Station[]>([]);
  const [future, setFuture] = useState<Station[]>([]);
  const [notice, setNotice] = useState("");
  const [runtime, setRuntime] = useState<SimulationRuntime>();
  const [runtimeError, setRuntimeError] = useState("");
  const [taskId, setTaskId] = useState(config.executionTaskId ?? "");
  const [task, setTask] = useState<SimulationTask>();
  const [checkingTask, setCheckingTask] = useState(true);
  const [executionError, setExecutionError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const submissionController = useRef<AbortController>();
  const cancellationController = useRef<AbortController>();
  const rejectedTaskId = useRef("");
  const fileInput = useRef<HTMLInputElement>(null);
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
  }, [refresh]);
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
          const result = await requestSimulation<{ tasks: SimulationTask[] }>(
            "/tasks",
            controller.signal,
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
  }, [taskId, submitting, refresh, saveConfig]);
  useEffect(
    () => () => {
      submissionController.current?.abort();
      cancellationController.current?.abort();
    },
    [],
  );
  const startSimulation = async () => {
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
    try {
      const result = await requestSimulation<SimulationTask>(
        "/tasks",
        controller.signal,
        { taskId: id, station },
      );
      if (!controller.signal.aborted) {
        if (result.id !== id) {
          throw new TaskRequestError(
            "提交响应的任务 ID 不一致，请查询原任务。",
          );
        }
        setTask(result);
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
  const cancelSimulation = async () => {
    if (!taskId || cancellationController.current) {
      return;
    }
    const controller = new AbortController();
    cancellationController.current = controller;
    setCancelling(true);
    setExecutionError("");
    try {
      const result = await requestSimulation<SimulationTask>(
        `/tasks/${encodeURIComponent(taskId)}/cancel`,
        controller.signal,
        {},
      );
      if (!controller.signal.aborted) {
        setTask(result);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setExecutionError(
          `取消结果未确认，请查询原任务：${error instanceof Error ? error.message : String(error)}`,
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
  const commit = (next: Station) => {
    setNotice("");
    setPast((history) => [...history, station]);
    setFuture([]);
    saveConfig({ station: next });
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
          name: `${KIND_LABELS[kind]} ${station.nodes.filter((item) => item.kind === kind).length + 1}`,
          parent: "world",
          position: [0.2, 0, 0.05],
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
            {item.name} <small>({KIND_LABELS[item.kind]})</small>
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
        <Typography variant="body2" color="text.secondary">
          编辑草稿随工作台布局保存。右侧录像是历史回合，不随草稿改变。
        </Typography>
        <TextField
          label="工作站名称"
          size="small"
          value={station.name}
          onChange={(event) => {
            commit({ ...station, name: event.target.value });
          }}
        />
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
              const url = URL.createObjectURL(
                new Blob([exportStation(station)], {
                  type: "application/json",
                }),
              );
              const link = document.createElement("a");
              link.href = url;
              link.download = "so101-station.json";
              link.click();
              setTimeout(() => {
                URL.revokeObjectURL(url);
              }, 1000);
            }}
          >
            导出 JSON
          </Button>
          <Button size="small" onClick={() => fileInput.current?.click()}>
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
              try {
                const imported = importStation(JSON.parse(await file.text()));
                commit(imported.station);
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
        <div className={classes.row}>
          {(["target", "frame", "object", "obstacle"] as const).map((kind) => (
            <Button
              size="small"
              key={kind}
              onClick={() => {
                addNode(kind);
              }}
            >
              添加{KIND_LABELS[kind]}
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
                    slotProps={{ htmlInput: { step: 0.005 } }}
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
        <Typography variant="subtitle1">抓放程序</Typography>
        <Typography variant="caption" color="text.secondary">
          动作引用目标点。改名不会丢失引用；虚线不表示规划成功。
        </Typography>
        {station.program.map((step, index) => (
          <div className={classes.step} key={step.id}>
            <Typography variant="body2">{index + 1}.</Typography>
            <TextField
              select
              size="small"
              aria-label={`步骤 ${index + 1} 动作`}
              value={step.action}
              onChange={(event) => {
                changeStep(step.id, {
                  action: event.target.value as Instruction["action"],
                });
              }}
            >
              {Object.entries(ACTION_LABELS).map(([value, label]) => (
                <MenuItem key={value} value={value}>
                  {label}
                </MenuItem>
              ))}
            </TextField>
            {step.action === "move" && (
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
                  action: "move",
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
          运行使用提交时的草稿快照。后续编辑不会改变已提交任务；右侧共享时间轴仍是历史回放。
        </Typography>
        <div className={classes.row}>
          <Button
            variant="contained"
            disabled={
              runtime?.ready !== true ||
              checkingTask ||
              submitting ||
              taskIsActive(task)
            }
            onClick={() => {
              void startSimulation();
            }}
          >
            规划并运行仿真
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
            {cancelling ? "正在取消…" : "取消任务"}
          </Button>
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
            {task.report && (
              <Typography variant="body2">
                物理验收：{task.report.passed === true ? "通过" : "未通过"}；
                真实夹起：{task.report.grasp_success === true ? "是" : "否"}；
                放置落定：{task.report.place_success === true ? "是" : "否"}；
                安全停止：{task.report.safety_stop === true ? "是" : "否"}
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
            RoboDK：场景树、坐标系归属、目标引用和指令列表。Lichtblick：原生面板、布局保存、录像、曲线和共享时间轴。草稿采用普通
            JSON，可手工修改。
          </Typography>
        </details>
      </div>
    </>
  );
}
RobotStation.panelType = "RobotStation";
RobotStation.defaultConfig = { station: defaultStation(), executionTaskId: "" };
export default Panel(RobotStation);
