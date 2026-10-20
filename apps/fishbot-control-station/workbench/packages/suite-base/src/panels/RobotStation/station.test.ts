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
  defaultStation,
  exportStation,
  importStation,
  programWarnings,
  removeNode,
  reparent,
  worldPosition,
} from "./station";

describe("RoboDK-style station editing", () => {
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
      worldPosition(
        next.nodes.find((n) => n.id === "grasp")!,
        next.nodes,
      ),
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

// The upstream comparator ignores config keys missing from the baseline. Both
// entry layouts must seed the station document so user edits are persistable.
it.each(["so101-station", "so101-station-mobile"])(
  "%s persists edits through native comparison",
  (name) => {
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
  },
);
