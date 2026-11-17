/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import { parseRecipeEnvelope, wrapRecipeEnvelope } from "./stationRecipe";

function stationDraft() {
  return {
    name: "X+20mm 上料",
    nodes: [
      {
        id: "pick",
        kind: "frame",
        parent: "world",
        position: [0.26, -0.13, 0],
      },
    ],
    program: [{ id: "s1", action: "open", target: "", seconds: 1 }],
    execution: {
      mode: "workspace-development-v1",
      pick_xy_m: [0.26, -0.13],
      pickup_hover_z_m: 0.054,
      target_region_xy_m: [
        [0.21, 0.27],
        [-0.16, -0.1],
      ],
    },
    notes: "草稿由原 Station 导入器及执行器继续验证。",
  };
}

describe("independent-episode Station recipe envelope", () => {
  it("creates an editable identity from the Station name and round-trips the original payload", () => {
    const station = stationDraft();
    const document = wrapRecipeEnvelope(station);
    expect(document).toMatchObject({
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
      recipe: { id: station.name, name: station.name, revision: "1" },
      skills: ["pick", "transfer", "place"],
      station,
    });
    const parsed = parseRecipeEnvelope(JSON.parse(JSON.stringify(document)));
    expect(parsed.stationSource).toEqual(station);
    expect(parsed.metadata).not.toHaveProperty("station");
    expect(parsed.warnings).toEqual([]);
    expect(wrapRecipeEnvelope(parsed.stationSource, parsed.metadata)).toEqual(
      document,
    );
  });

  it("does not alias Station payload or nested metadata during parse and wrap", () => {
    const original = stationDraft();
    const document = wrapRecipeEnvelope(original);
    document.provenance = [{ repository: "so101", examples: ["x-plus20"] }];
    const parsed = parseRecipeEnvelope(document);
    const exported = wrapRecipeEnvelope(parsed.stationSource, parsed.metadata);
    const editable = parsed.stationSource as ReturnType<typeof stationDraft>;
    editable.nodes[0]!.position[0] = 0.25;
    editable.execution.pick_xy_m[0] = 0.25;
    const provenance = parsed.metadata.provenance as { examples: string[] }[];
    provenance[0]!.examples.push("edited");
    expect(original.nodes[0]!.position[0]).toBe(0.26);
    expect(
      (document.station as ReturnType<typeof stationDraft>).execution
        .pick_xy_m[0],
    ).toBe(0.26);
    expect(
      (exported.station as ReturnType<typeof stationDraft>).execution
        .pick_xy_m[0],
    ).toBe(0.26);
    expect(document.provenance).toEqual([
      { repository: "so101", examples: ["x-plus20"] },
    ]);
    expect(exported.provenance).toEqual(document.provenance);
  });

  it("preserves unknown optional metadata with a warning instead of blocking the document", () => {
    const document = wrapRecipeEnvelope(stationDraft());
    document.vendorNotes = { palette: ["red", "blue"], editable: true };
    document.observation = {
      source: "rgb",
      vendor: { camera: "existing-overview" },
    };
    document.provenance = { opaqueFutureShape: [1, { original: true }] };
    const identity = document.recipe as Record<string, unknown>;
    identity.ownerLabel = "现场人员可改";
    const compatibility = document.compatibility as Record<string, unknown>;
    compatibility.sourceRevision = "human-editable-reference";
    const parsed = parseRecipeEnvelope(document);
    expect(wrapRecipeEnvelope(parsed.stationSource, parsed.metadata)).toEqual(
      document,
    );
    expect(
      parsed.warnings.some((warning) => warning.includes("vendorNotes")),
    ).toBe(true);
    expect(
      parsed.warnings.some((warning) => warning.includes("ownerLabel")),
    ).toBe(true);
    expect(
      parsed.warnings.some((warning) => warning.includes("sourceRevision")),
    ).toBe(true);
    expect(parsed.metadata.observation).toEqual(document.observation);
    expect(parsed.metadata.provenance).toEqual(document.provenance);
  });

  it.each([
    ["format", "robot-station"],
    ["version", 2],
    ["version", "1"],
    ["units", "mm"],
    ["frameConvention", "se3"],
    ["executionScope", "fishbot_shared_world"],
    ["station", null],
    ["skills", ["pick", "place", "transfer"]],
    ["skills", ["pick", "transfer", "place", "retry"]],
    ["skills", ["Locate", "Approach", "Grasp", "Carry", "Place", "Retreat"]],
  ])(
    "rejects unsupported required %s=%j without modifying the source",
    (field, value) => {
      const document = {
        ...wrapRecipeEnvelope(stationDraft()),
        [field as string]: value,
      };
      const before = JSON.stringify(document);
      expect(() => parseRecipeEnvelope(document)).toThrow(`配方 ${field}`);
      expect(JSON.stringify(document)).toBe(before);
    },
  );

  it.each([
    ["platform", "px4"],
    ["executor", "other-controller"],
    ["stationVersion", 2],
  ])(
    "rejects incompatible %s without silently choosing a different executor",
    (field, value) => {
      const document = wrapRecipeEnvelope(stationDraft());
      document.compatibility = {
        ...(document.compatibility as Record<string, unknown>),
        [field as string]: value,
      };
      expect(() => parseRecipeEnvelope(document)).toThrow(
        `compatibility.${field}`,
      );
    },
  );

  it.each(["id", "name", "revision"])(
    "keeps recipe.%s editable but requires a nonempty string",
    (field) => {
      const document = wrapRecipeEnvelope(stationDraft());
      document.recipe = {
        id: "custom-id",
        name: "现场卸料草稿",
        revision: "二改版",
      };
      expect(parseRecipeEnvelope(document).metadata.recipe).toEqual(
        document.recipe,
      );
      for (const value of ["", "  ", null, 1]) {
        document.recipe = {
          ...(document.recipe as Record<string, unknown>),
          [field]: value,
        };
        expect(() => parseRecipeEnvelope(document)).toThrow(`recipe.${field}`);
      }
    },
  );

  it("requires all execution-contract fields and does not handle plain Station documents", () => {
    expect(() => parseRecipeEnvelope(stationDraft())).toThrow("format");
    for (const field of [
      "version",
      "units",
      "frameConvention",
      "executionScope",
      "compatibility",
      "recipe",
      "skills",
      "station",
    ]) {
      const document = wrapRecipeEnvelope(stationDraft());
      delete document[field];
      expect(() => parseRecipeEnvelope(document)).toThrow(`配方 ${field}`);
    }
    expect(() => wrapRecipeEnvelope(stationDraft(), {})).toThrow("format");
  });

  it.each([
    "rotation",
    "quaternion",
    "orientation",
    "rpy",
    "transform",
    "matrix",
  ])(
    "rejects explicit %s geometry instead of letting Station import discard it",
    (field) => {
      for (const location of ["station", "node"]) {
        const document = wrapRecipeEnvelope(stationDraft());
        const source = document.station as ReturnType<typeof stationDraft> &
          Record<string, unknown>;
        if (location === "station") {
          source[field] = [0, 0, 0];
        } else {
          (source.nodes[0] as Record<string, unknown>)[field] = [0, 0, 0];
        }
        expect(() => parseRecipeEnvelope(document)).toThrow(
          location === "station"
            ? `station.${field}`
            : `station.nodes[0].${field}`,
        );
      }
    },
  );

  it("does not inspect optional provenance as execution geometry", () => {
    const document = wrapRecipeEnvelope(stationDraft());
    document.provenance = { rotation: [0, 0, 1], transform: "historical note" };
    const source = document.station as ReturnType<typeof stationDraft>;
    const parsed = parseRecipeEnvelope(document);
    expect(parsed.metadata.provenance).toEqual(document.provenance);
    expect(parsed.stationSource).toEqual(source);
  });

  it.each(["size", "motion", "enabled"])("rejects SO101 node %s rather than silently dropping it", (field) => {
    const document = wrapRecipeEnvelope(stationDraft());
    const source = document.station as ReturnType<typeof stationDraft>;
    (source.nodes[0] as Record<string, unknown>)[field] = field === "enabled" ? false : [1, 1, 1];
    expect(() => parseRecipeEnvelope(document)).toThrow(`station.nodes[0].${field}`);
  });

  it("rejects a drone payload wrapped in SO101 compatibility", () => {
    const document = wrapRecipeEnvelope(stationDraft());
    (document.station as Record<string, unknown>).platform = "px4";
    expect(() => parseRecipeEnvelope(document)).toThrow("station.platform");
  });

  it.each([-1, 2, null, true, "1", undefined])("rejects recipe duration %p instead of repairing it to 1", (seconds) => {
    const document = wrapRecipeEnvelope(stationDraft());
    (document.station as Record<string, unknown>).program = [{ action: "open", target: "jaw", seconds }];
    expect(() => parseRecipeEnvelope(document)).toThrow("station.program[0].seconds");
  });

  it("retains historical pass references as metadata without creating task or current-pass state", () => {
    const station = stationDraft();
    const document = wrapRecipeEnvelope(station);
    const historical = [
      {
        taskId: "prior-episode",
        report: "episode/report.json",
        historicalVerdict: "pass",
      },
    ];
    document.acceptanceReferences = historical;
    const parsed = parseRecipeEnvelope(document);
    const edited = parsed.stationSource as ReturnType<typeof stationDraft>;
    edited.nodes[0]!.position[0] = 0.25;
    const exported = wrapRecipeEnvelope(edited, parsed.metadata);
    expect(exported.acceptanceReferences).toEqual(historical);
    expect(
      parsed.warnings.some((warning) =>
        warning.includes("不代表当前草稿或新任务通过"),
      ),
    ).toBe(true);
    expect(parsed).not.toHaveProperty("currentPass");
    expect(parsed).not.toHaveProperty("taskId");
    expect(exported).not.toHaveProperty("currentPass");
    expect(exported).not.toHaveProperty("taskId");
    expect(exported.station).not.toHaveProperty("currentPass");
    expect(exported.station).not.toHaveProperty("taskId");
    expect(document.station).toEqual(station);
  });
});
