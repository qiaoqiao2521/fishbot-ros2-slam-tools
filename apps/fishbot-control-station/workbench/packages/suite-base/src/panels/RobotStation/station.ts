/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

export type Vec3 = [number, number, number];
export type Platform = "so101" | "px4";
export type Kind =
  | "frame"
  | "robot"
  | "tool"
  | "object"
  | "target"
  | "obstacle";
export type StationNode = {
  id: string;
  name: string;
  kind: Kind;
  parent: string;
  position: Vec3;
  size?: Vec3;
  enabled?: boolean;
  motion?: {
    type: "linear_ping_pong";
    axis: Vec3;
    distance_m: number;
    speed_m_s: number;
  };
};
export type FlightAcceptance = {
  max_altitude_m?: number;
  position_tolerance_m?: number;
  min_clearance_m?: number;
  min_cruise_speed_m_s?: number;
  min_cruise_duration_s?: number;
};
export type Instruction = {
  id: string;
  action:
    | "move"
    | "open"
    | "close"
    | "wait"
    | "takeoff"
    | "waypoint"
    | "return_home"
    | "land";
  target: string;
  seconds: number;
};
export type Station = {
  platform?: Platform;
  // Preserve editable execution intent, including unsupported values, for backend validation.
  execution?: unknown;
  flight?: {
    speed_m_s: number;
    planner: "waypoint" | "ego";
    acceptance?: FlightAcceptance;
    sensors?: {
      depth_drop_probability?: number;
      depth_delay_ms?: number;
      seed?: number;
    };
  };
  name: string;
  nodes: StationNode[];
  program: Instruction[];
  notes: string;
};
export const KIND_LABELS: Record<Kind, string> = {
  frame: "坐标系",
  robot: "机械臂",
  tool: "夹爪",
  object: "物体",
  target: "目标点",
  obstacle: "障碍",
};
export const ACTION_LABELS: Record<Instruction["action"], string> = {
  move: "移动到目标",
  open: "张开夹爪",
  close: "闭合夹爪",
  wait: "等待",
  takeoff: "起飞",
  waypoint: "飞到航点",
  return_home: "返航",
  land: "降落",
};

export function stationPlatform(station: Station): Platform {
  return station.platform ?? "so101";
}

export function stationActions(platform: Platform): Instruction["action"][] {
  return platform === "px4"
    ? ["takeoff", "waypoint", "wait", "return_home", "land"]
    : ["move", "open", "close", "wait"];
}

export function actionNeedsTarget(action: Instruction["action"]): boolean {
  return ["move", "takeoff", "waypoint"].includes(action);
}

export function stationKindLabel(kind: Kind, platform: Platform): string {
  if (platform === "px4") {
    if (kind === "robot") {
      return "无人机";
    }
    if (kind === "target") {
      return "航点";
    }
  }
  return KIND_LABELS[kind];
}

export function defaultDroneStation(): Station {
  return {
    platform: "px4",
    flight: {
      speed_m_s: 2,
      planner: "ego",
      acceptance: {
        max_altitude_m: 2.2,
        position_tolerance_m: 0.3,
        min_clearance_m: 0.25,
      },
    },
    name: "PX4 四旋翼巡航",
    nodes: [
      {
        id: "base",
        name: "X500 四旋翼",
        kind: "robot",
        parent: "world",
        position: [0, 0, 0],
      },
      {
        id: "home",
        name: "起降坐标系",
        kind: "frame",
        parent: "world",
        position: [0, 0, 0],
      },
      {
        id: "takeoff",
        name: "起飞高度",
        kind: "target",
        parent: "home",
        position: [0, 0, 2],
      },
      {
        id: "wp1",
        name: "航点 1",
        kind: "target",
        parent: "home",
        position: [3, 0, 2],
      },
      {
        id: "wp2",
        name: "航点 2",
        kind: "target",
        parent: "home",
        position: [3, 3, 2],
      },
      {
        id: "wp3",
        name: "航点 3",
        kind: "target",
        parent: "home",
        position: [0, 3, 2],
      },
    ],
    program: [
      { id: "s1", action: "takeoff", target: "takeoff", seconds: 1 },
      { id: "s2", action: "waypoint", target: "wp1", seconds: 1 },
      { id: "s3", action: "waypoint", target: "wp2", seconds: 1 },
      { id: "s4", action: "waypoint", target: "wp3", seconds: 1 },
      { id: "s5", action: "return_home", target: "home", seconds: 1 },
      { id: "s6", action: "land", target: "", seconds: 1 },
    ],
    notes:
      "本地 PX4 + Gazebo 四旋翼仿真。X 向东、Y 向北、Z 向上，单位米。先做 EGO 场景模型预演；正式飞行使用 Gazebo 理想定位和深度图。",
  };
}

// Workcell XY from SO101 grasp_workcell.py. Heights are editable design values,
// not a collision-checked trajectory. Frame axes are parallel to world in this editor.
export function defaultStation(): Station {
  return {
    name: "SO101 抓放工作站",
    nodes: [
      {
        id: "base",
        name: "SO101",
        kind: "robot",
        parent: "world",
        position: [0, 0, 0],
      },
      {
        id: "jaw",
        name: "双指夹爪",
        kind: "tool",
        parent: "base",
        position: [0, 0, 0],
      },
      {
        id: "pick",
        name: "取料坐标系",
        kind: "frame",
        parent: "world",
        position: [0.24, -0.13, 0],
      },
      {
        id: "cube",
        name: "待抓方块",
        kind: "object",
        parent: "pick",
        position: [0, 0, 0.01],
      },
      {
        id: "approach",
        name: "接近点",
        kind: "target",
        parent: "pick",
        position: [0, 0, 0.08],
      },
      {
        id: "grasp",
        name: "抓取点",
        kind: "target",
        parent: "pick",
        position: [0, 0, 0.02],
      },
      {
        id: "place",
        name: "放料坐标系",
        kind: "frame",
        parent: "world",
        position: [0.24, 0.14, 0],
      },
      {
        id: "release",
        name: "释放点",
        kind: "target",
        parent: "place",
        position: [0, 0, 0.03],
      },
      {
        id: "clear",
        name: "脱离点",
        kind: "target",
        parent: "place",
        position: [0, 0, 0.1],
      },
    ],
    program: [
      { id: "s1", action: "open", target: "", seconds: 1 },
      { id: "s2", action: "move", target: "approach", seconds: 1 },
      { id: "s3", action: "move", target: "grasp", seconds: 1 },
      { id: "s4", action: "close", target: "", seconds: 1 },
      { id: "s5", action: "move", target: "approach", seconds: 1 },
      { id: "s6", action: "move", target: "release", seconds: 1 },
      { id: "s7", action: "open", target: "", seconds: 1 },
      { id: "s8", action: "move", target: "clear", seconds: 1 },
    ],
    notes:
      "程序草稿。接近高度、绕障、释放和回位需由执行器规划验证。坐标系仅支持平移，尚未定义工具 TCP。",
  };
}

/** Development layouts remain editable task inputs, never inherited pass certificates. */
export function workspaceStationSample(id: "x-plus20" | "x-minus20"): Station {
  const station = defaultStation();
  const plus = id === "x-plus20";
  const pick: Vec3 = plus ? [0.26, -0.13, 0] : [0.235, -0.13, 0];
  const offset = plus ? 0 : -0.015;
  station.name = plus ? "SO101 X+20mm 布局开发样例" : "SO101 X−20mm 布局开发样例";
  for (const node of station.nodes) {
    if (node.id === "pick") {
      node.position = pick;
    } else if (["cube", "approach", "grasp"].includes(node.id)) {
      node.position[0] = offset;
      if (node.id === "approach" && plus) {
        node.position[2] = 0.074;
      }
    } else if (node.id === "place" && !plus) {
      node.position = [0.2, 0.2, 0];
    }
  }
  station.execution = {
    mode: "workspace-development-v1",
    pick_xy_m: pick.slice(0, 2),
    pickup_hover_z_m: plus ? 0.054 : 0.06,
    target_region_xy_m: [
      [0.21, 0.27],
      [-0.16, -0.1],
    ],
  };
  station.notes = `来源：workspace-x-m1a / ${plus ? "outside_x_plus20_layout" : "outside_x_minus20_layout_secondary"}。仅为布局开发样例，不代表连续工作区已验证；编辑后须重新运行原物理裁判。`;
  return station;
}

function copyExecution(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(copyExecution);
  }
  const object = record(value);
  return object
    ? Object.fromEntries(Object.entries(object).map(([key, item]) => [key, copyExecution(item)]))
    : value;
}

/** Keep references inside the document, but share no editable data with its source. */
export function copyStation(station: Station): Station {
  return {
    ...station,
    name: `${station.name} 副本`,
    nodes: station.nodes.map(
      (node): StationNode => ({
        ...node,
        position: [...node.position],
        ...(node.size ? { size: [...node.size] as Vec3 } : {}),
        ...(node.motion
          ? { motion: { ...node.motion, axis: [...node.motion.axis] as Vec3 } }
          : {}),
      }),
    ),
    program: station.program.map((step) => ({ ...step })),
    ...(Object.hasOwn(station, "execution")
      ? { execution: copyExecution(station.execution) }
      : {}),
    ...(station.flight
      ? {
          flight: {
            ...station.flight,
            ...(station.flight.acceptance
              ? { acceptance: { ...station.flight.acceptance } }
              : {}),
            ...(station.flight.sensors
              ? { sensors: { ...station.flight.sensors } }
              : {}),
          },
        }
      : {}),
  };
}

export function worldPosition(
  node: StationNode,
  nodes: readonly StationNode[],
): Vec3 {
  const result: Vec3 = [...node.position];
  const visited = new Set([node.id]);
  let parent = node.parent;
  while (parent !== "world" && !visited.has(parent)) {
    visited.add(parent);
    const currentParent = parent;
    const ancestor = nodes.find((item) => item.id === currentParent);
    if (!ancestor) {
      break;
    }
    for (const i of [0, 1, 2] as const) {
      result[i] += ancestor.position[i];
    }
    parent = ancestor.parent;
  }
  return result;
}

export function descendants(
  id: string,
  nodes: readonly StationNode[],
): Set<string> {
  const result = new Set([id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const node of nodes) {
      if (result.has(node.parent) && !result.has(node.id)) {
        result.add(node.id);
        changed = true;
      }
    }
  }
  return result;
}

/** Commit a native world-space handle without moving the obstacle's parent. */
export function transformObstacle(
  station: Station,
  id: string,
  position: Vec3,
  size: Vec3,
): Station {
  const node = station.nodes.find((item) => item.id === id);
  if (
    stationPlatform(station) !== "px4" ||
    node?.kind !== "obstacle" ||
    node.enabled === false
  ) {
    return station;
  }
  const parent = station.nodes.find((item) => item.id === node.parent);
  const offset: Vec3 = parent
    ? worldPosition(parent, station.nodes)
    : [0, 0, 0];
  return {
    ...station,
    nodes: station.nodes.map((item) =>
      item.id === id
        ? {
            ...item,
            position: position.map((value, axis) =>
              Number((value - offset[axis]!).toFixed(3)),
            ) as Vec3,
            size: size.map((value) => Number(value.toFixed(3))) as Vec3,
          }
        : item,
    ),
  };
}

export function reparent(
  station: Station,
  id: string,
  parent: string,
): Station {
  const node = station.nodes.find((item) => item.id === id);
  const frame = station.nodes.find(
    (item) => item.id === parent && item.kind === "frame",
  );
  if (
    !node ||
    descendants(id, station.nodes).has(parent) ||
    (parent !== "world" && !frame)
  ) {
    return station;
  }
  const world = worldPosition(node, station.nodes);
  const origin: Vec3 = frame ? worldPosition(frame, station.nodes) : [0, 0, 0];
  return {
    ...station,
    nodes: station.nodes.map((item) =>
      item.id === id
        ? {
            ...item,
            parent,
            position: world.map((value, i) => value - origin[i]!) as Vec3,
          }
        : item,
    ),
  };
}

export function removeNode(station: Station, id: string): Station {
  const removed = descendants(id, station.nodes);
  return {
    ...station,
    nodes: station.nodes.filter((node) => !removed.has(node.id)),
    program: station.program.map((step) =>
      removed.has(step.target) ? { ...step, target: "" } : step,
    ),
  };
}

export function programWarnings(station: Station): string[] {
  return station.program.flatMap((step, i) =>
    actionNeedsTarget(step.action) &&
    !station.nodes.some(
      (node) => node.id === step.target && node.kind === "target",
    )
      ? [`第 ${i + 1} 步缺少目标点，请重新选择。`]
      : [],
  );
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value != undefined &&
    typeof value === "object" &&
    !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

/** Tolerant document import: skip malformed items, report every repair, retain usable content. */
export function importStation(value: unknown): {
  station: Station;
  warnings: string[];
} {
  const root = record(value);
  const source = record(root?.station) ?? root;
  if (!source || !Array.isArray(source.nodes)) {
    throw new Error("请选择含 nodes 数组的工作站 JSON；当前草稿未改变。");
  }
  const warnings: string[] = [];
  if (Object.hasOwn(source, "execution")) {
    const execution = record(source.execution);
    const pair = (value: unknown): value is [number, number] =>
      Array.isArray(value) &&
      value.length === 2 &&
      value.every((item) => typeof item === "number" && Number.isFinite(item));
    const region = execution?.target_region_xy_m;
    const hover = execution?.pickup_hover_z_m;
    if (
      execution?.mode !== "workspace-development-v1" ||
      !pair(execution.pick_xy_m) ||
      typeof hover !== "number" ||
      !Number.isFinite(hover) ||
      hover < 0.054 ||
      hover > 0.06 ||
      !Array.isArray(region) ||
      region.length !== 2 ||
      !region.every((bounds) => pair(bounds) && bounds[0] < bounds[1])
    ) {
      warnings.push("执行参数未知或无效，已原样保留；运行时由执行器校验，不回退默认场景。");
    }
  }
  const platform: Platform = source.platform === "px4" ? "px4" : "so101";
  if (
    source.platform != undefined &&
    source.platform !== "so101" &&
    source.platform !== "px4"
  ) {
    warnings.push("无法识别的平台，按 SO101 草稿导入。");
  }
  const nodes: StationNode[] = [];
  for (const [i, raw] of source.nodes.entries()) {
    const item = record(raw);
    const kind = item?.kind;
    if (
      !item ||
      typeof kind !== "string" ||
      !Object.hasOwn(KIND_LABELS, kind) ||
      typeof item.id !== "string" ||
      !item.id ||
      item.id === "world" ||
      nodes.some((node) => node.id === item.id)
    ) {
      warnings.push(`对象 ${i + 1} 无效或 ID 重复，已跳过。`);
      continue;
    }
    const position = item.position;
    const validPosition =
      Array.isArray(position) &&
      position.length === 3 &&
      position.every((x) => typeof x === "number" && Number.isFinite(x));
    if (!validPosition) {
      warnings.push(`对象 ${i + 1} 坐标无效，使用原点。`);
    }
    const size = item.size;
    const validSize =
      Array.isArray(size) &&
      size.length === 3 &&
      size.every((x) => typeof x === "number" && Number.isFinite(x) && x > 0);
    const motion = record(item.motion);
    const axis = motion?.axis;
    const distance = motion?.distance_m;
    const motionSpeed = motion?.speed_m_s;
    const validMotion =
      motion?.type === "linear_ping_pong" &&
      Array.isArray(axis) &&
      axis.length === 3 &&
      axis.every((x) => typeof x === "number" && Number.isFinite(x)) &&
      axis.some((x) => x !== 0) &&
      typeof distance === "number" &&
      Number.isFinite(distance) &&
      distance > 0 &&
      typeof motionSpeed === "number" &&
      Number.isFinite(motionSpeed) &&
      motionSpeed > 0;
    if (item.motion != undefined && !validMotion) {
      warnings.push(`对象 ${i + 1} 往返运动参数无效，按静态障碍导入。`);
    }
    if (
      platform === "px4" &&
      kind === "obstacle" &&
      size != undefined &&
      !validSize
    ) {
      warnings.push(`对象 ${i + 1} 障碍尺寸无效，使用 1 × 1 × 2 m。`);
    }
    nodes.push({
      id: item.id,
      name: typeof item.name === "string" ? item.name : item.id,
      kind: kind as Kind,
      parent: typeof item.parent === "string" ? item.parent : "world",
      position: validPosition ? (position as Vec3) : [0, 0, 0],
      ...(platform === "px4" && kind === "obstacle"
        ? { size: validSize ? ([...size] as Vec3) : ([1, 1, 2] as Vec3) }
        : {}),
      ...(platform === "px4" &&
      kind === "obstacle" &&
      typeof item.enabled === "boolean"
        ? { enabled: item.enabled }
        : {}),
      ...(platform === "px4" && kind === "obstacle" && validMotion
        ? {
            motion: {
              type: "linear_ping_pong" as const,
              axis: [...axis] as Vec3,
              distance_m: distance,
              speed_m_s: motionSpeed,
            },
          }
        : {}),
    });
  }
  for (const node of nodes) {
    if (
      node.parent !== "world" &&
      (!nodes.some((item) => item.id === node.parent) ||
        descendants(node.id, nodes).has(node.parent))
    ) {
      node.parent = "world";
      warnings.push(`${node.name} 的父节点无效，已挂到世界坐标系。`);
    }
  }
  const program: Instruction[] = [];
  for (const [i, raw] of (Array.isArray(source.program)
    ? source.program
    : []
  ).entries()) {
    const step = record(raw);
    if (
      !step ||
      typeof step.action !== "string" ||
      !stationActions(platform).includes(step.action as Instruction["action"])
    ) {
      warnings.push(`步骤 ${i + 1} 无法识别，已跳过。`);
      continue;
    }
    program.push({
      id: `import-step-${i}`,
      action: step.action as Instruction["action"],
      target: typeof step.target === "string" ? step.target : "",
      seconds:
        typeof step.seconds === "number" &&
        Number.isFinite(step.seconds) &&
        step.seconds >= 0
          ? step.seconds
          : 1,
    });
  }
  const flight = record(source.flight);
  const sensorsSource = record(flight?.sensors);
  const sensors: NonNullable<NonNullable<Station["flight"]>["sensors"]> = {};
  for (const key of [
    "depth_drop_probability",
    "depth_delay_ms",
    "seed",
  ] as const) {
    const parameter = sensorsSource?.[key];
    if (parameter == undefined) {
      continue;
    }
    const valid =
      typeof parameter === "number" &&
      Number.isFinite(parameter) &&
      parameter >= 0 &&
      (key !== "depth_drop_probability" || parameter <= 1) &&
      (key !== "seed" ||
        (Number.isInteger(parameter) && parameter <= 4294967295));
    if (valid) {
      sensors[key] = parameter;
    } else {
      warnings.push(`深度感知参数 ${key} 无效，沿用执行器默认值。`);
    }
  }
  const acceptanceSource = record(flight?.acceptance);
  const acceptance: FlightAcceptance = {};
  for (const key of [
    "max_altitude_m",
    "position_tolerance_m",
    "min_clearance_m",
    "min_cruise_speed_m_s",
    "min_cruise_duration_s",
  ] as const) {
    const limit = acceptanceSource?.[key];
    if (limit == undefined) {
      continue;
    }
    if (typeof limit === "number" && Number.isFinite(limit) && limit >= 0) {
      acceptance[key] = limit;
    } else {
      warnings.push(`飞行验收 ${key} 无效，未启用该项。`);
    }
  }
  const speed = flight?.speed_m_s;
  const validSpeed =
    typeof speed === "number" &&
    Number.isFinite(speed) &&
    speed >= 1 &&
    speed <= 5;
  if (platform === "px4" && flight?.speed_m_s != undefined && !validSpeed) {
    warnings.push("速度上限需在 1–5 m/s，使用 1 m/s。");
  }
  const station: Station = {
    ...(source.platform != undefined ? { platform } : {}),
    ...(Object.hasOwn(source, "execution")
      ? { execution: copyExecution(source.execution) }
      : {}),
    ...(platform === "px4"
      ? {
          flight: {
            speed_m_s: validSpeed ? speed : 1,
            planner:
              flight?.planner === "ego"
                ? ("ego" as const)
                : ("waypoint" as const),
            ...(acceptanceSource ? { acceptance } : {}),
            ...(sensorsSource ? { sensors } : {}),
          },
        }
      : {}),
    name: typeof source.name === "string" ? source.name : "导入工作站",
    nodes,
    program,
    notes: typeof source.notes === "string" ? source.notes : "",
  };
  return { station, warnings: [...warnings, ...programWarnings(station)] };
}

export function exportStation(station: Station): string {
  return (
    JSON.stringify(
      {
        format: "robot-station",
        version: 1,
        units: "m",
        frameConvention: "translation-only",
        station,
      },
      undefined,
      2,
    ) ?? "{}"
  );
}
