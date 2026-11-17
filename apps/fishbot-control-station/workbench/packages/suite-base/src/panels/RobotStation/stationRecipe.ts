/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

export type ParsedRecipeEnvelope = {
  stationSource: unknown;
  metadata: Record<string, unknown>;
  warnings: string[];
};

const SKILLS = ["pick", "transfer", "place"] as const;
const UNSUPPORTED_TRANSFORMS = [
  "rotation",
  "quaternion",
  "orientation",
  "rpy",
  "transform",
  "matrix",
];
const ENVELOPE_FIELDS = new Set([
  "format",
  "version",
  "units",
  "frameConvention",
  "executionScope",
  "compatibility",
  "recipe",
  "station",
  "skills",
  "observation",
  "provenance",
  "acceptanceReferences",
]);

function record(value: unknown): Record<string, unknown> | undefined {
  return value != undefined &&
    typeof value === "object" &&
    !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function cloneDocument(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(cloneDocument);
  }
  const object = record(value);
  return object
    ? Object.fromEntries(
        Object.entries(object).map(([key, item]) => [key, cloneDocument(item)]),
      )
    : value;
}

function unsupported(field: string, expected: string): never {
  throw new Error(
    `配方 ${field} 不受支持：当前仅支持 ${expected}；当前草稿未改变。`,
  );
}

/** Parse only recipe documents; Station validation and dispatch remain with the caller. */
export function parseRecipeEnvelope(value: unknown): ParsedRecipeEnvelope {
  const source = record(value);
  if (source?.format !== "station-recipe") {
    unsupported("format", "station-recipe");
  }
  if (source.version !== 1) {
    unsupported("version", "1");
  }
  if (source.units !== "m") {
    unsupported("units", "m（米）");
  }
  if (source.frameConvention !== "translation-only") {
    unsupported(
      "frameConvention",
      "translation-only（仅平移，无旋转或 TCP 变换）",
    );
  }
  if (source.executionScope !== "independent_episode") {
    unsupported("executionScope", "independent_episode（独立仿真回合）");
  }
  const compatibility = record(source.compatibility);
  for (const [key, expected] of [
    ["platform", "so101"],
    ["executor", "so101-mujoco-visual-grasp"],
    ["stationVersion", 1],
  ] as const) {
    if (compatibility?.[key] !== expected) {
      unsupported(`compatibility.${key}`, String(expected));
    }
  }
  const identity = record(source.recipe);
  for (const key of ["id", "name", "revision"] as const) {
    if (
      typeof identity?.[key] !== "string" ||
      identity[key].trim().length === 0
    ) {
      unsupported(`recipe.${key}`, "可编辑的非空字符串");
    }
  }
  if (
    !Array.isArray(source.skills) ||
    source.skills.length !== SKILLS.length ||
    !source.skills.every((skill, index) => skill === SKILLS[index])
  ) {
    unsupported(
      "skills",
      "pick → transfer → place；动作仍由 station.program 执行",
    );
  }
  const station = record(source.station);
  if (!station) {
    unsupported("station", "原 Station 对象");
  }
  if (station.platform !== undefined && station.platform !== "so101") {
    unsupported("station.platform", "so101");
  }
  if (Array.isArray(station.program)) {
    for (const [index, step] of station.program.entries()) {
      if (record(step)?.seconds !== 1) {
        unsupported(`station.program[${index}].seconds`, "原模板值 1；自定义时长尚未实现");
      }
    }
  }
  const geometry = [
    ["station", station],
    ...(Array.isArray(station.nodes)
      ? station.nodes.map(
          (node, index) => [`station.nodes[${index}]`, record(node)] as const,
        )
      : []),
  ] as const;
  for (const [name, item] of geometry) {
    if (name !== "station" && item) {
      const unsupportedNodeField = ["size", "motion", "enabled"].find((key) => Object.hasOwn(item, key));
      if (unsupportedNodeField) {
        unsupported(`${name}.${unsupportedNodeField}`, "原 SO101 固定尺寸静态几何；自定义尺寸与动态障碍尚未接入");
      }
    }
    const field =
      item && UNSUPPORTED_TRANSFORMS.find((key) => Object.hasOwn(item, key));
    if (field) {
      unsupported(
        `${name}.${field}`,
        "position 米制平移；旋转与矩阵变换尚未接入原执行器",
      );
    }
  }

  const warnings: string[] = [];
  const unknownFields = Object.keys(source).filter(
    (key) => !ENVELOPE_FIELDS.has(key),
  );
  if (unknownFields.length > 0) {
    warnings.push(
      `配方附加字段 ${unknownFields.join("、")} 已保留，仅作元数据，不参与执行。`,
    );
  }
  for (const [name, object, fields] of [
    ["recipe", identity, ["id", "name", "revision"]],
    [
      "compatibility",
      compatibility,
      ["platform", "executor", "stationVersion"],
    ],
  ] as const) {
    const known = new Set<string>(fields);
    const unknown = Object.keys(object!).filter((key) => !known.has(key));
    if (unknown.length > 0) {
      warnings.push(
        `配方 ${name} 附加字段 ${unknown.join("、")} 已保留，不改变执行合同。`,
      );
    }
  }
  if (Object.hasOwn(source, "acceptanceReferences")) {
    warnings.push(
      "历史验收引用仅供查看，不代表当前草稿或新任务通过；运行后由原物理裁判重新判定。",
    );
  }
  const metadata = Object.fromEntries(
    Object.entries(source)
      .filter(([key]) => key !== "station")
      .map(([key, item]) => [key, cloneDocument(item)]),
  );
  return { stationSource: cloneDocument(source.station), metadata, warnings };
}

/** Wrap a Station draft without task state, requests, or inherited acceptance. */
export function wrapRecipeEnvelope(
  station: unknown,
  metadata?: Record<string, unknown>,
): Record<string, unknown> {
  const name = record(station)?.name;
  const title =
    typeof name === "string" && name.trim().length > 0
      ? name
      : "SO101 工位配方";
  const envelope = {
    ...(metadata ?? {
      format: "station-recipe",
      version: 1,
      units: "m",
      frameConvention: "translation-only",
      executionScope: "independent_episode",
      compatibility: {
        platform: "so101",
        executor: "so101-mujoco-visual-grasp",
        stationVersion: 1,
      },
      recipe: { id: title, name: title, revision: "1" },
      skills: [...SKILLS],
    }),
    station,
  };
  const parsed = parseRecipeEnvelope(envelope);
  return { ...parsed.metadata, station: parsed.stationSource };
}
