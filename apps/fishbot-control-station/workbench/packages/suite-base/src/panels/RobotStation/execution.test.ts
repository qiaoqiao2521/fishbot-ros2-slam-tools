/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import {
  carryGateWaiting,
  graspEvidenceLabel,
  latestSimulationTask,
  requestSimulation,
  simulationArtifactUrl,
  simulationReplayUrl,
  taskIsActive,
  TaskRequestError,
} from "./execution";
import { defaultDroneStation, defaultStation } from "./station";

describe("SO101 simulation task transport", () => {
  it("offers carry only for the original opted-in, waiting, nonterminal task", () => {
    const original = { id: "same-task", status: "running", phase: "hold",
      station: { ...defaultStation(), skillControl: { mode: "hold-before-carry" } },
      carry_gate: { mode: "hold-before-carry", state: "waiting" } };
    expect(carryGateWaiting(original)).toBe(true);
    expect(carryGateWaiting(undefined)).toBe(false);
    expect(carryGateWaiting({ ...original, station: defaultStation() })).toBe(false);
    expect(carryGateWaiting({ ...original, cancelRequested: true })).toBe(false);
    for (const state of ["pending", "released", "ended"]) {
      expect(carryGateWaiting({ ...original, carry_gate: { ...original.carry_gate, state } })).toBe(false);
    }
    for (const status of ["succeeded", "failed", "cancelled"]) {
      expect(carryGateWaiting({ ...original, status })).toBe(false);
    }
  });
  it("keeps grasp evidence separate from phase and cancelled attempt outcome", () => {
    const evidence = { schema: "so101.physical-skill-evidence.v1", scope: "observation_only",
      grasp: { postcondition_met: false, first_met_elapsed_s: null } };
    expect(graspEvidenceLabel({ id: "same-task", status: "running", phase: "close" })).toBeUndefined();
    expect(graspEvidenceLabel({ id: "same-task", status: "running", phase: "hold", skill_evidence: evidence }))
      .toContain("尚未确认");
    const confirmed = { ...evidence, grasp: { postcondition_met: true, first_met_elapsed_s: 27.68 } };
    const task = { id: "same-task", status: "cancelled", report: { passed: false, skill_evidence: confirmed } };
    expect(graspEvidenceLabel(task)).toBe("物理抓取证据：曾在 27.68 s 确认持续持物；不代表本回合完成。");
    expect(task.report.passed).toBe(false);
    expect(task.status).toBe("cancelled");
    expect(graspEvidenceLabel({ ...task, skill_evidence: { ...confirmed, scope: "control" } })).toBeUndefined();
  });

  const originalFetch = globalThis.fetch;
  let fetchMock: jest.MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = jest.fn() as jest.MockedFunction<typeof fetch>;
    globalThis.fetch = fetchMock;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  const response = (data: unknown, status = 200): Response =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => data,
    }) as Response;

  it("submits the caller's saved ID and station snapshot exactly once", async () => {
    const station = defaultStation();
    const controller = new AbortController();
    fetchMock.mockResolvedValue(
      response({ id: "saved-task", status: "pending" }, 202),
    );
    await requestSimulation("/tasks", controller.signal, {
      taskId: "saved-task",
      station,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/so101/tasks",
      expect.objectContaining({
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({ taskId: "saved-task", station }),
      }),
    );
  });

  it("restores and queries tasks through GET without creating a task", async () => {
    const controller = new AbortController();
    fetchMock.mockResolvedValue(
      response({ id: "saved-task", status: "running" }),
    );
    await requestSimulation("/tasks/saved-task", controller.signal);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/so101/tasks/saved-task",
      expect.objectContaining({ method: "GET", body: undefined }),
    );
  });

  it("sends one carry handoff to the same ID, then queries it without automatic POST retry", async () => {
    const signal = new AbortController().signal;
    fetchMock.mockResolvedValue(response({ id: "same-task", status: "running" }));
    await requestSimulation("/tasks/same-task/resume-carry", signal, {});
    await requestSimulation("/tasks/same-task", signal);
    expect(fetchMock.mock.calls.map(([url, options]) => [url, options?.method])).toEqual([
      ["/api/so101/tasks/same-task/resume-carry", "POST"],
      ["/api/so101/tasks/same-task", "GET"],
    ]);
  });

  it("routes PX4 submission, return-home and cancel to the drone service only", async () => {
    const signal = new AbortController().signal;
    fetchMock.mockResolvedValue(
      response({ id: "drone-task", status: "running" }),
    );
    await requestSimulation(
      "/tasks",
      signal,
      { taskId: "drone-task", station: defaultDroneStation() },
      "px4",
    );
    await requestSimulation("/tasks/drone-task/return-home", signal, {}, "px4");
    await requestSimulation("/tasks/drone-task/cancel", signal, {}, "px4");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/drone/tasks",
      "/api/drone/tasks/drone-task/return-home",
      "/api/drone/tasks/drone-task/cancel",
    ]);
    expect(
      fetchMock.mock.calls.every(([, options]) => options?.method === "POST"),
    ).toBe(true);
  });

  it("reads drone history without dispatching a task", async () => {
    fetchMock.mockResolvedValue(response({ tasks: [] }));
    await requestSimulation(
      "/tasks",
      new AbortController().signal,
      undefined,
      "px4",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/drone/tasks",
      expect.objectContaining({ method: "GET", body: undefined }),
    );
  });

  it("opens same-origin MCAP in the existing player with a separate review layout", () => {
    const origin = "http://127.0.0.1:5186";
    const artifact = "/api/drone/tasks/task-123/artifacts/mcap";
    const replay = new URL(simulationReplayUrl(artifact, origin)!, origin);
    expect(replay.searchParams.get("ds")).toBe("remote-file");
    expect(replay.searchParams.get("ds.url")).toBe(origin + artifact);
    expect(replay.searchParams.get("layoutUrl")).toBe(
      origin + "/layouts/drone-review.json",
    );
    for (const invalid of [
      undefined,
      "//other.example/file.mcap",
      "https://other.example/file.mcap",
      "/\\other.example/file.mcap",
    ]) {
      expect(simulationReplayUrl(invalid, origin)).toBeUndefined();
    }
  });

  it("preserves a real rejection reason and never retries POST", async () => {
    fetchMock.mockResolvedValue(response({ error: "此释放点尚未支持" }, 400));
    await expect(
      requestSimulation("/tasks", new AbortController().signal, {
        taskId: "saved-task",
      }),
    ).rejects.toMatchObject({
      name: "TaskRequestError",
      status: 400,
      message: "此释放点尚未支持",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("leaves a lost submission response for the caller to query by its original ID", async () => {
    fetchMock.mockRejectedValue(new TypeError("network lost"));
    await expect(
      requestSimulation("/tasks", new AbortController().signal, {
        taskId: "saved-task",
      }),
    ).rejects.toThrow("network lost");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects unreadable successful responses rather than treating them as completion", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => {
        throw new SyntaxError("truncated");
      },
    } as unknown as Response);
    await expect(
      requestSimulation("/tasks", new AbortController().signal, {
        taskId: "saved-task",
      }),
    ).rejects.toBeInstanceOf(TaskRequestError);
  });

  it("finds the latest persisted task independent of list order", () => {
    const older = {
      id: "older",
      status: "succeeded",
      submittedAt: "2026-10-20T01:00:00Z",
    };
    const newer = {
      id: "newer",
      status: "failed",
      submittedAt: "2026-10-20T02:00:00Z",
    };
    expect(latestSimulationTask([newer, older])).toBe(newer);
    expect(latestSimulationTask([older, newer])).toBe(newer);
    expect(latestSimulationTask([])).toBeUndefined();
  });

  it("keeps unknown and running tasks active while recognizing every terminal result", () => {
    expect(taskIsActive(undefined)).toBe(false);
    for (const status of ["submitting", "pending", "running", "unknown"]) {
      expect(taskIsActive({ id: "saved-task", status })).toBe(true);
    }
    for (const status of ["succeeded", "failed", "cancelled"]) {
      expect(taskIsActive({ id: "saved-task", status })).toBe(false);
    }
  });

  it("uses local artifact paths and refuses executable or foreign URLs", () => {
    expect(simulationArtifactUrl("/api/so101/tasks/saved-task/video.mp4")).toBe(
      "/api/so101/tasks/saved-task/video.mp4",
    );
    for (const value of [
      undefined,
      "javascript:alert(1)",
      "//other.example/video",
      "https://other.example/video",
    ]) {
      expect(simulationArtifactUrl(value)).toBeUndefined();
    }
  });
});
