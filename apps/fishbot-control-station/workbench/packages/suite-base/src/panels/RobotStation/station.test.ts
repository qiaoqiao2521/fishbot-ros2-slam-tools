/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { LayoutData } from "@lichtblick/suite-base/context/CurrentLayoutContext/actions";
import { isLayoutEqual } from "@lichtblick/suite-base/services/LayoutManager/utils/isLayoutEqual";

import {
  copyStation,
  defaultDroneStation,
  defaultStation,
  exportStation,
  importStation,
  programWarnings,
  removeNode,
  reparent,
  stationActions,
  stationKindLabel,
  stationPlatform,
  transformObstacle,
  workspaceStationSample,
  worldPosition,
} from "./station";

describe("SO101 workspace development samples", () => {
  it.each([
    "x-plus20",
    "x-minus20",
  ] as const)("keeps %s geometry and execution intent aligned", (id) => {
    const station = workspaceStationSample(id);
    const plus = id === "x-plus20";
    const world = (name: string) =>
      worldPosition(station.nodes.find((node) => node.id === name)!, station.nodes);
    expect(world("pick")).toEqual(plus ? [0.26, -0.13, 0] : [0.235, -0.13, 0]);
    for (const name of ["cube", "approach", "grasp"]) {
      expect(world(name)[0]).toBeCloseTo(plus ? 0.26 : 0.22);
      expect(world(name)[1]).toBe(-0.13);
    }
    expect(world("approach")[2]).toBe(plus ? 0.074 : 0.08);
    expect(world("release")).toEqual(plus ? [0.24, 0.14, 0.03] : [0.2, 0.2, 0.03]);
    expect(world("clear")).toEqual(plus ? [0.24, 0.14, 0.1] : [0.2, 0.2, 0.1]);
    expect(station.program).toEqual(defaultStation().program);
    expect(station.execution).toEqual({
      mode: "workspace-development-v1",
      pick_xy_m: plus ? [0.26, -0.13] : [0.235, -0.13],
      pickup_hover_z_m: plus ? 0.054 : 0.06,
      target_region_xy_m: [
        [0.21, 0.27],
        [-0.16, -0.1],
      ],
    });
    expect(station.notes).toContain("须重新运行原物理裁判");
    expect(defaultStation()).not.toHaveProperty("execution");
  });

  it("round-trips edited execution fields through JSON and native layout storage", () => {
    const original = workspaceStationSample("x-plus20");
    const execution = original.execution as { pickup_hover_z_m: number; source?: string };
    execution.pickup_hover_z_m = 0.055;
    execution.source = "human edit";
    const restored = importStation(JSON.parse(exportStation(original)));
    expect(restored.station.execution).toEqual(original.execution);
    expect(restored.warnings).toEqual([]);
    const baseline = JSON.parse(
      readFileSync(join(__dirname, "../../../../../robot-layouts/so101-station.json"), "utf8"),
    ) as LayoutData;
    const id = "RobotStation!so101station";
    const current = {
      ...baseline,
      configById: {
        ...baseline.configById,
        [id]: { ...baseline.configById[id], station: restored.station },
      },
    };
    expect(isLayoutEqual(baseline, current)).toBe(false);
  });

  it("copies execution arrays independently from the original and imported document", () => {
    const original = workspaceStationSample("x-plus20");
    const imported = importStation(original).station;
    const copied = copyStation(imported);
    const execution = copied.execution as { pick_xy_m: number[]; target_region_xy_m: number[][] };
    execution.pick_xy_m[0] = 0.25;
    execution.target_region_xy_m[0]![0] = 0.22;
    expect(imported.execution).toEqual(original.execution);
    expect(copied.execution).not.toEqual(original.execution);
    (imported.execution as { pick_xy_m: number[] }).pick_xy_m[1] = -0.12;
    expect(imported.execution).not.toEqual(original.execution);
  });

  it.each([
    { mode: "unknown-mode", extra: [1, 2] },
    null,
    { mode: "workspace-development-v1", pickup_hover_z_m: -1 },
  ])("preserves invalid execution %s without falling back to legacy", (execution) => {
    const restored = importStation({ ...defaultStation(), execution });
    expect(restored.station).toHaveProperty("execution", execution);
    expect(restored.warnings.some((warning) => warning.includes("不回退默认场景"))).toBe(true);
    expect(importStation(JSON.parse(exportStation(restored.station))).station).toHaveProperty(
      "execution",
      execution,
    );
    expect(copyStation(restored.station)).toHaveProperty("execution", execution);
  });
});

describe("RoboDK-style station editing", () => {
  it("commits 3D obstacle handles in their parent's frame and preserves undo input", () => {
    const station = defaultDroneStation();
    station.nodes.find((node) => node.id === "home")!.position = [1, -1, 0];
    station.nodes.push({
      id: "box",
      name: "Box",
      kind: "obstacle",
      parent: "home",
      position: [1.5, 0, 1],
      size: [1, 1, 2],
      motion: {
        type: "linear_ping_pong",
        axis: [0, 1, 0],
        distance_m: 2,
        speed_m_s: 0.3,
      },
    });
    const next = transformObstacle(station, "box", [4, 2, 1.5], [0.8, 1.2, 3]);
    const box = next.nodes.find((node) => node.id === "box")!;
    expect(box.position).toEqual([3, 3, 1.5]);
    expect(worldPosition(box, next.nodes)).toEqual([4, 2, 1.5]);
    expect(box.size).toEqual([0.8, 1.2, 3]);
    expect(box.motion).toEqual(station.nodes.at(-1)!.motion);
    expect(station.nodes.at(-1)!.position).toEqual([1.5, 0, 1]);
    expect(station.nodes.at(-1)!.size).toEqual([1, 1, 2]);
    const so101 = defaultStation();
    expect(transformObstacle(so101, "box", [4, 2, 1.5], [1, 1, 1])).toBe(so101);
    station.nodes.at(-1)!.enabled = false;
    expect(transformObstacle(station, "box", [4, 2, 1.5], [1, 1, 1])).toBe(
      station,
    );
  });
  it("copies a submitted station without sharing editable scene or program data", () => {
    const source = defaultStation();
    const copy = copyStation(source);
    expect(copy.name).toBe(`${source.name} 副本`);
    expect(copy.nodes).toEqual(source.nodes);
    expect(copy.program).toEqual(source.program);
    copy.nodes.find((node) => node.id === "place")!.position[0] = 0.26;
    copy.nodes.find((node) => node.id === "cube")!.name = "副本方块";
    copy.program[0]!.seconds = 3;
    expect(source.nodes.find((node) => node.id === "place")!.position[0]).toBe(
      0.24,
    );
    expect(source.nodes.find((node) => node.id === "cube")!.name).toBe(
      "待抓方块",
    );
    expect(source.program[0]!.seconds).toBe(1);
  });
  it("moves copied release and clearance targets together through the place frame", () => {
    const source = defaultStation();
    const copy = copyStation(source);
    const place = copy.nodes.find((node) => node.id === "place")!;
    place.position = [0.25, 0.12, 0];
    expect(
      worldPosition(
        copy.nodes.find((node) => node.id === "release")!,
        copy.nodes,
      ),
    ).toEqual([0.25, 0.12, 0.03]);
    expect(
      worldPosition(
        copy.nodes.find((node) => node.id === "clear")!,
        copy.nodes,
      ),
    ).toEqual([0.25, 0.12, 0.1]);
    expect(copy.program[5]!.target).toBe("release");
    expect(source.nodes.find((node) => node.id === "place")!.position).toEqual([
      0.24, 0.14, 0,
    ]);
  });
  it("preserves copied task input through editable JSON export and import", () => {
    const copy = copyStation(defaultStation());
    copy.nodes.find((node) => node.id === "place")!.position[1] = 0.15;
    const restored = importStation(JSON.parse(exportStation(copy))).station;
    expect(restored.name).toBe(copy.name);
    expect(restored.nodes).toEqual(copy.nodes);
    expect(restored.program.map(({ id: _id, ...step }) => step)).toEqual(
      copy.program.map(({ id: _id, ...step }) => step),
    );
  });
  it("keeps world coordinates when changing reference frames", () => {
    const station = defaultStation();
    const before = worldPosition(
      station.nodes.find((n) => n.id === "grasp")!,
      station.nodes,
    );
    const next = reparent(station, "grasp", "place");
    expect(
      worldPosition(next.nodes.find((n) => n.id === "grasp")!, next.nodes),
    ).toEqual(before);
    expect(station.nodes.find((n) => n.id === "grasp")!.parent).toBe("pick");
  });
  it("moves descendants with their frame without rewriting program references", () => {
    const station = defaultStation();
    station.nodes.find((n) => n.id === "pick")!.position[0] += 0.05;
    expect(
      worldPosition(
        station.nodes.find((n) => n.id === "grasp")!,
        station.nodes,
      )[0],
    ).toBeCloseTo(0.29);
    expect(station.program[2]!.target).toBe("grasp");
  });
  it("rejects cycles when changing parents", () => {
    const station = defaultStation();
    station.nodes.push({
      id: "child",
      parent: "pick",
      kind: "frame",
      name: "child",
      position: [0, 0, 0],
    });
    expect(reparent(station, "pick", "child")).toBe(station);
  });
  it("preserves instructions but reports deleted targets", () => {
    const station = removeNode(defaultStation(), "pick");
    expect(
      station.nodes.some((n) =>
        ["pick", "grasp", "cube", "approach"].includes(n.id),
      ),
    ).toBe(false);
    expect(station.program).toHaveLength(8);
    expect(programWarnings(station)).toHaveLength(3);
  });
  it("round-trips human-editable JSON without input locks", () => {
    const station = defaultStation();
    const raw = JSON.parse(exportStation(station));
    raw.version = 99;
    raw.station.name = "手工修改";
    const imported = importStation(raw);
    expect(imported.station.name).toBe("手工修改");
    expect(imported.station.nodes).toEqual(station.nodes);
    expect(
      imported.station.program.map(({ id: _id, ...step }) => step),
    ).toEqual(station.program.map(({ id: _id, ...step }) => step));
  });
  it("skips broken items and repairs invalid coordinates or missing parents", () => {
    const imported = importStation({
      nodes: [
        null,
        { id: "a", kind: "target", parent: "gone", position: ["bad", 0, 0] },
        { id: "a", kind: "target" },
      ],
      program: [{ action: "unrecognized" }],
    });
    expect(imported.station.nodes).toEqual([
      {
        id: "a",
        kind: "target",
        parent: "world",
        position: [0, 0, 0],
        name: "a",
      },
    ]);
    expect(imported.warnings.length).toBeGreaterThanOrEqual(4);
  });
  it("repairs imported parent cycles", () => {
    const { station, warnings } = importStation({
      nodes: [
        { id: "a", kind: "frame", parent: "b", position: [1, 0, 0] },
        { id: "b", kind: "frame", parent: "a", position: [0, 1, 0] },
      ],
    });
    expect(warnings.some((w) => w.includes("父节点"))).toBe(true);
    expect(
      worldPosition(station.nodes[0]!, station.nodes).every(Number.isFinite),
    ).toBe(true);
  });
  it("does not replace an existing draft with an unrelated JSON document", () => {
    expect(() => importStation({ foo: 1 })).toThrow("当前草稿未改变");
  });
});

describe("PX4 station data", () => {
  it("defaults old documents to SO101 and keeps each platform's action list separate", () => {
    expect(stationPlatform(defaultStation())).toBe("so101");
    expect(stationActions("so101")).toEqual(["move", "open", "close", "wait"]);
    expect(stationActions("px4")).toEqual([
      "takeoff",
      "waypoint",
      "wait",
      "return_home",
      "land",
    ]);
    expect(stationKindLabel("robot", "px4")).toBe("无人机");
    expect(stationKindLabel("robot", "so101")).toBe("机械臂");
  });

  it("provides a ceiling-limited EGO draft without a cruise minimum on short legs", () => {
    const station = defaultDroneStation();
    expect(station.flight).toEqual({
      speed_m_s: 2,
      planner: "ego",
      acceptance: {
        max_altitude_m: 2.2,
        position_tolerance_m: 0.3,
        min_clearance_m: 0.25,
      },
    });
    expect(
      station.nodes.find((node) => node.id === "takeoff")?.position[2],
    ).toBe(2);
    const waypoints = station.program.filter(
      (step) => step.action === "waypoint",
    );
    expect(waypoints).toHaveLength(3);
    expect(
      waypoints.map(
        (step) =>
          station.nodes.find((node) => node.id === step.target)?.position[2],
      ),
    ).toEqual([2, 2, 2]);
    expect(programWarnings(station)).toEqual([]);
    expect(programWarnings(removeNode(station, "wp2"))).toHaveLength(1);
  });

  it("copies flight settings independently and preserves edited flight intent through JSON", () => {
    const original = defaultDroneStation();
    const copied = copyStation(original);
    copied.flight!.speed_m_s = 1.5;
    copied.nodes.find((node) => node.id === "wp2")!.position[2] = 4;
    expect(original.flight!.speed_m_s).toBe(2);
    expect(original.nodes.find((node) => node.id === "wp2")!.position[2]).toBe(
      2,
    );
    const restored = importStation(JSON.parse(exportStation(copied))).station;
    expect(restored.platform).toBe("px4");
    expect(restored.flight).toEqual(copied.flight);
    expect(restored.nodes).toEqual(copied.nodes);
    expect(restored.program.map(({ id: _id, ...step }) => step)).toEqual(
      copied.program.map(({ id: _id, ...step }) => step),
    );
  });

  it("keeps an explicitly selected EGO planner and repairs only invalid optional speed", () => {
    const station = defaultDroneStation();
    const result = importStation({
      ...station,
      flight: { planner: "ego", speed_m_s: -2 },
    });
    expect(result.station.flight).toEqual({ planner: "ego", speed_m_s: 1 });
    expect(result.warnings).toContain("速度上限需在 1–5 m/s，使用 1 m/s。");
  });

  it.each([
    0.5, 5.1,
  ])("repairs unsupported flight speed limit %s to the default", (speed) => {
    const { station, warnings } = importStation({
      ...defaultDroneStation(),
      flight: { planner: "waypoint", speed_m_s: speed },
    });
    expect(station.flight?.speed_m_s).toBe(1);
    expect(warnings).toContain("速度上限需在 1–5 m/s，使用 1 m/s。");
  });

  it("preserves obstacle geometry through import, copy, and export without shared size arrays", () => {
    const source = defaultDroneStation();
    source.nodes.push({
      id: "box",
      name: "绕行障碍",
      kind: "obstacle",
      parent: "world",
      position: [1.5, 0, 1.2],
      size: [0.8, 1.2, 2.4],
    });
    const imported = importStation(source).station;
    const copied = copyStation(imported);
    expect(copied.nodes.at(-1)?.size).toEqual([0.8, 1.2, 2.4]);
    copied.nodes.at(-1)!.size![0] = 1.5;
    expect(imported.nodes.at(-1)?.size).toEqual([0.8, 1.2, 2.4]);
    imported.nodes.at(-1)!.size![1] = 2;
    expect(source.nodes.at(-1)?.size).toEqual([0.8, 1.2, 2.4]);
    expect(
      importStation(JSON.parse(exportStation(copied))).station.nodes,
    ).toEqual(copied.nodes);
  });

  it("round-trips moving boxes and optional acceptance without sharing draft arrays", () => {
    const source = defaultDroneStation();
    source.flight!.acceptance!.min_cruise_speed_m_s = 1.5;
    source.flight!.acceptance!.min_cruise_duration_s = 2;
    source.nodes.push({
      id: "moving-box",
      name: "立柱",
      kind: "obstacle",
      parent: "world",
      position: [4, 0, 1],
      size: [0.4, 0.4, 2],
      motion: {
        type: "linear_ping_pong",
        axis: [0, 1, 0],
        distance_m: 2,
        speed_m_s: 0.3,
      },
    });
    const imported = importStation(JSON.parse(exportStation(source))).station;
    expect(imported.nodes).toEqual(source.nodes);
    expect(imported.flight).toEqual(source.flight);
    const copy = copyStation(imported);
    copy.nodes.at(-1)!.motion!.axis[1] = -1;
    copy.flight!.acceptance!.max_altitude_m = 4;
    copy.flight!.acceptance!.min_cruise_duration_s = 3;
    expect(imported.nodes.at(-1)!.motion!.axis).toEqual([0, 1, 0]);
    expect(imported.flight!.acceptance!.max_altitude_m).toBe(2.2);
    expect(imported.flight!.acceptance!.min_cruise_duration_s).toBe(2);
    expect(
      importStation(JSON.parse(exportStation(copy))).station.flight!
        .acceptance!.min_cruise_duration_s,
    ).toBe(3);
    const legacy = importStation({
      ...source,
      flight: { planner: "ego", speed_m_s: 1 },
    }).station;
    expect(legacy.flight!.acceptance).toBeUndefined();
  });

  it("preserves disabled roofs and explicit perception faults without truncating valid delays", () => {
    const source = defaultDroneStation();
    source.flight!.sensors = {
      depth_drop_probability: 1,
      depth_delay_ms: 5000,
      seed: 4294967295,
    };
    source.nodes.push({
      id: "roof",
      name: "天花板",
      kind: "obstacle",
      parent: "world",
      position: [0, 0, 3],
      size: [8, 8, 0.2],
      enabled: false,
    });
    const imported = importStation(JSON.parse(exportStation(source)));
    expect(imported.warnings).toEqual([]);
    expect(imported.station.nodes.at(-1)!.enabled).toBe(false);
    expect(imported.station.flight!.sensors).toEqual(source.flight!.sensors);
    const copied = copyStation(imported.station);
    copied.flight!.sensors!.depth_delay_ms = 50;
    expect(imported.station.flight!.sensors!.depth_delay_ms).toBe(5000);
  });

  it("repairs invalid optional drone obstacle dimensions without discarding the scene", () => {
    const source = defaultDroneStation();
    const { station, warnings } = importStation({
      ...source,
      nodes: [
        ...source.nodes,
        { id: "box", kind: "obstacle", position: [1.5, 0, 1], size: [0, 1, 2] },
      ],
    });
    expect(station.nodes.at(-1)?.size).toEqual([1, 1, 2]);
    expect(warnings.some((warning) => warning.includes("障碍尺寸无效"))).toBe(
      true,
    );
  });
});

// The upstream comparator ignores config keys missing from the baseline. Both
// entry layouts must seed the station document so user edits are persistable.
it.each([
  "so101-station",
  "so101-station-mobile",
])("%s persists edits through native comparison", (name) => {
  const baseline = JSON.parse(
    readFileSync(
      join(__dirname, "../../../../../robot-layouts", name + ".json"),
      "utf8",
    ),
  ) as LayoutData;
  const id = "RobotStation!so101station";
  expect(baseline.configById[id]?.station).toBeDefined();
  const current = {
    ...baseline,
    configById: {
      ...baseline.configById,
      [id]: {
        ...baseline.configById[id],
        station: { ...defaultStation(), name: "修改后" },
      },
    },
  };
  expect(isLayoutEqual(baseline, current)).toBe(false);
});

it.each([
  "drone-station",
  "drone-station-mobile",
])("%s seeds flight parameters for native save and restore", (name) => {
  const baseline = JSON.parse(
    readFileSync(
      join(__dirname, "../../../../../robot-layouts", name + ".json"),
      "utf8",
    ),
  ) as LayoutData;
  const id = "RobotStation!dronestation";
  expect(baseline.configById[id]?.station).toEqual(defaultDroneStation());
  const current = {
    ...baseline,
    configById: {
      ...baseline.configById,
      [id]: {
        ...baseline.configById[id],
        station: {
          ...defaultDroneStation(),
          flight: { planner: "waypoint", speed_m_s: 1.5 },
        },
      },
    },
  };
  expect(isLayoutEqual(baseline, current)).toBe(false);
});
