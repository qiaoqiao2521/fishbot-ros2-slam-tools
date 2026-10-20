/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import {
  latestSimulationTask,
  requestSimulation,
  simulationArtifactUrl,
  taskIsActive,
  TaskRequestError,
} from "./execution";
import { defaultStation } from "./station";

describe("SO101 simulation task transport", () => {
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
