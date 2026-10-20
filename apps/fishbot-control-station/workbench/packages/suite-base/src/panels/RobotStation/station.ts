/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

export type Vec3 = [number, number, number];
export type Kind =
  "frame" | "robot" | "tool" | "object" | "target" | "obstacle";
export type StationNode = {
  id: string;
  name: string;
  kind: Kind;
  parent: string;
  position: Vec3;
};
export type Instruction = {
  id: string;
  action: "move" | "open" | "close" | "wait";
  target: string;
  seconds: number;
};
export type Station = {
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
};

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

/** Keep references inside the document, but share no editable data with its source. */
export function copyStation(station: Station): Station {
  return {
    ...station,
    name: `${station.name} 副本`,
    nodes: station.nodes.map((node): StationNode => ({
      ...node,
      position: [...node.position],
    })),
    program: station.program.map((step) => ({ ...step })),
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
    step.action === "move" &&
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
    nodes.push({
      id: item.id,
      name: typeof item.name === "string" ? item.name : item.id,
      kind: kind as Kind,
      parent: typeof item.parent === "string" ? item.parent : "world",
      position: validPosition ? (position as Vec3) : [0, 0, 0],
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
      !Object.hasOwn(ACTION_LABELS, step.action)
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
  const station = {
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
