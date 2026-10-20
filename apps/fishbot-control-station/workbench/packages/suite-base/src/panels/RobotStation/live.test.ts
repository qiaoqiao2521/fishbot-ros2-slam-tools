/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import { previewStation, sceneModeLabel, selectScene } from "./live";
import { defaultDroneStation, defaultStation } from "./station";

describe("SO101 native live scene source", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: jest.MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = jest.fn() as jest.MockedFunction<typeof fetch>;
    globalThis.fetch = fetchMock;
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ mode: "draft" }),
    } as Response);
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("updates geometry through preview without creating a simulation task", async () => {
    const station = defaultStation();
    const controller = new AbortController();
    await previewStation(station, controller.signal);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/so101/preview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ station }),
        signal: controller.signal,
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("switches explicitly to the original task ID without resubmitting it", async () => {
    await selectScene(
      { mode: "task", taskId: "original-task" },
      new AbortController().signal,
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/so101/scene-mode",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ mode: "task", taskId: "original-task" }),
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps PX4 preview and selected task requests in the drone namespace", async () => {
    const station = defaultDroneStation();
    const signal = new AbortController().signal;
    await previewStation(station, signal);
    await selectScene({ mode: "draft", station }, signal);
    await selectScene({ mode: "task", taskId: "drone-task" }, signal, "px4");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/drone/preview",
      "/api/drone/scene-mode",
      "/api/drone/scene-mode",
    ]);
    expect(fetchMock.mock.calls[2]?.[1]?.body).toBe(
      JSON.stringify({ mode: "task", taskId: "drone-task" }),
    );
  });

  it("includes the current draft when switching away from a task", async () => {
    const station = defaultStation();
    await selectScene({ mode: "draft", station }, new AbortController().signal);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/so101/scene-mode",
      expect.objectContaining({
        body: JSON.stringify({ mode: "draft", station }),
      }),
    );
  });

  it("keeps task identity visible independently of terminal state", () => {
    expect(
      sceneModeLabel({
        mode: "task",
        taskId: "cancelled-task",
        status: "cancelled",
      }),
    ).toContain("cancelled-task");
    expect(sceneModeLabel({ mode: "draft" })).toContain("不推进仿真");
    expect(sceneModeLabel(undefined)).toContain("正在连接");
  });

  it("reports invalid preview geometry without changing or submitting the draft", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: "对象坐标不可用" }),
    } as Response);
    await expect(
      previewStation(defaultStation(), new AbortController().signal),
    ).rejects.toThrow("对象坐标不可用");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
