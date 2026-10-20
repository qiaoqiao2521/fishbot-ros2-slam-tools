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
import { useRef, useState } from "react";
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

type Config = { station?: Station };
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
  const fileInput = useRef<HTMLInputElement>(null);
  const node = station.nodes.find((item) => item.id === selected);
  const blocked = descendants(selected, station.nodes);
  const targets = station.nodes.filter((item) => item.kind === "target");
  const warnings = programWarnings(station);
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
        <Alert severity="info">
          当前可编辑、保存和导出程序。仿真执行器尚未接入这个编辑入口；目标点和步骤尚未经过物理验证。
        </Alert>
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
RobotStation.defaultConfig = { station: defaultStation() };
export default Panel(RobotStation);
