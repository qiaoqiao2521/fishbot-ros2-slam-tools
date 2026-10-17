#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0

// Project-local browser acceptance against real records; no mocked application state.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");

const defaults = require("./review.config.json");
const upstreamRequire = createRequire(path.join(__dirname, "../workbench/package.json"));
const { chromium } = upstreamRequire("@playwright/test");
const { PNG } = upstreamRequire("pngjs");
const hash = value => crypto.createHash("sha256").update(value).digest("hex");

function argumentsFrom(argv) {
  const config = { ...defaults };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--help") return { help: true };
    if (arg === "--baseline") { config.baseline = true; continue; }
    if (arg === "--mobile") {
      config.mobile = true;
      config.layoutPath = config.mobileLayoutPath;
      config.viewport = { width: 390, height: 844 };
      continue;
    }
    if (!["--url", "--output", "--chrome", "--timeout-ms"].includes(arg) || !argv[i + 1]) {
      throw new Error(`Unknown or incomplete option: ${arg}`);
    }
    const value = argv[++i];
    if (arg === "--url") config.baseUrl = value;
    if (arg === "--output") config.output = path.resolve(value);
    if (arg === "--chrome") config.chromePath = value;
    if (arg === "--timeout-ms") config.timeoutMs = Number(value);
  }
  const base = new URL(config.baseUrl);
  assert(!(config.baseline && config.mobile), "Choose baseline or mobile mode, not both");
  assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Only loopback previews are allowed");
  assert.equal(base.protocol, "http:");
  assert.equal(base.username + base.password, "", "Credentials are not test configuration");
  assert(Number.isInteger(config.timeoutMs) && config.timeoutMs >= 1000 && config.timeoutMs <= 300000);
  assert(fs.statSync(config.chromePath).isFile(), "System Chrome executable must exist");
  config.baseUrl = base.origin;
  return config;
}

function panelById(page, id) {
  // Upstream Panel.tsx and e2e/page-objects use this exact test ID.
  return page.getByTestId(`panel-mouseenter-container ${id}`);
}

function panelByType(page, type) {
  return page.locator(`[data-testid^="panel-mouseenter-container ${type}!"]`);
}

function rasterStats(buffer) {
  const image = PNG.sync.read(buffer);
  const colors = new Set();
  const stride = Math.max(1, Math.floor(Math.sqrt(image.width * image.height / 20000)));
  let samples = 0, colored = 0;
  for (let y = 0; y < image.height; y += stride) {
    for (let x = 0; x < image.width; x += stride) {
      const i = (y * image.width + x) * 4;
      const [r, g, b] = image.data.subarray(i, i + 3);
      colors.add((r >> 3) * 1024 + (g >> 3) * 32 + (b >> 3));
      if (Math.max(r, g, b) - Math.min(r, g, b) > 35) colored++;
      samples++;
    }
  }
  return { width: image.width, height: image.height, quantizedColors: colors.size,
    coloredFraction: colored / samples, sha256: hash(buffer) };
}

function greenObjectBounds(buffer) {
  // A visual acceptance check for this record's bright green target, not FK.
  const image = PNG.sync.read(buffer), size = image.width * image.height;
  const mask = new Uint8Array(size), queue = new Int32Array(size);
  for (let i = 0; i < size; i++) {
    const [r, g, b, a] = image.data.subarray(i * 4, i * 4 + 4);
    if (a > 100 && g > 90 && g > r * 1.5 && g > b * 1.3) mask[i] = 1;
  }
  let largest;
  for (let i = 0; i < size; i++) {
    if (!mask[i]) continue;
    let head = 0, tail = 1, minX = image.width, maxX = 0, minY = image.height, maxY = 0;
    queue[0] = i; mask[i] = 0;
    while (head < tail) {
      const p = queue[head++], x = p % image.width, y = Math.floor(p / image.width);
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      for (const next of [x ? p - 1 : -1, x + 1 < image.width ? p + 1 : -1,
        y ? p - image.width : -1, y + 1 < image.height ? p + image.width : -1]) {
        if (next >= 0 && mask[next]) { mask[next] = 0; queue[tail++] = next; }
      }
    }
    if (!largest || tail > largest.area) largest = { area: tail, minX, maxX, minY, maxY };
  }
  assert(largest && largest.area >= 16, "The green recorded object must actually be visible in the 3D view");
  const margin = Math.min(largest.minX, largest.minY, image.width - 1 - largest.maxX, image.height - 1 - largest.maxY);
  assert(margin >= 3, `Recorded object reaches the 3D canvas edge (margin ${margin}px)`);
  return { ...largest, margin, canvasWidth: image.width, canvasHeight: image.height };
}

async function physicalTime(episode) {
  const text = await episode.innerText();
  const match = text.match(/物理时间\s+([\d.]+)\s*\/\s*([\d.]+)\s*s/);
  assert(match, "EpisodeReview must display the current simulation time");
  return { current: Number(match[1]), duration: Number(match[2]) };
}

async function run(config) {
  const expect = upstreamRequire("@playwright/test").expect.configure({ timeout: config.timeoutMs });
  const stamp = new Date().toISOString().replaceAll(":", "-");
  const output = config.output ?? path.join(__dirname, config.outputRoot, stamp);
  fs.mkdirSync(output, { recursive: true, mode: 0o700 });
  const report = {
    schemaVersion: 1, passed: false,
    scope: "Actual browser, native Lichtblick panels and recorded SO101 data; no new robot execution, policy evaluation or real-time claim",
    startedAt: new Date().toISOString(), config, output,
    checks: [], screenshots: [], errors: [], pageErrors: [], consoleErrors: [],
    requests: [], blockedRequests: [], websockets: [], steps: [],
    selectorSources: ["workbench/e2e/page-objects/player-controls.ts", "workbench/e2e/page-objects/layout-manager.ts",
      "workbench/e2e/page-objects/sidebar.ts", "workbench/packages/suite-base/src/components/Panel.tsx",
      "workbench/packages/suite-base/src/components/PanelToolbar/PanelActionsDropdown.tsx"],
  };
  const save = () => fs.writeFileSync(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n", { mode: 0o600 });
  const checked = (name, evidence = {}) => { report.checks.push({ name, passed: true, ...evidence }); save(); };
  const step = name => { report.steps.push({ name, at: new Date().toISOString() }); save(); };
  let browser, page;
  try {
    step("read actual layout and recording headers");
    const layoutUrl = new URL(config.layoutPath, config.baseUrl).href;
    const recordUrl = new URL(config.recordPath, config.baseUrl).href;
    let layoutText, layout;
    if (!config.baseline) {
      const layoutResponse = await fetch(layoutUrl, { signal: AbortSignal.timeout(config.timeoutMs) });
      assert(layoutResponse.ok, `Layout HTTP ${layoutResponse.status}`);
      layoutText = await layoutResponse.text();
      layout = JSON.parse(layoutText);
      assert(layout.configById && typeof layout.configById === "object", "Expected upstream exported layout schema");
    }
    const ids = {}, allIds = {};
    const expectedTypes = config.baseline ? [] : config.mobile ? ["Image", "EpisodeReview"] : config.expectedPanelTypes;
    for (const type of expectedTypes) {
      const matching = Object.keys(layout.configById).filter(id => id.startsWith(`${type}!`));
      assert(matching.length > 0, `At least one configured ${type} panel is required`);
      ids[type] = matching[0];
      allIds[type] = matching;
    }
    const recordingHead = await fetch(recordUrl, { method: "HEAD", signal: AbortSignal.timeout(config.timeoutMs) });
    assert(recordingHead.ok, `MCAP HTTP ${recordingHead.status}`);
    assert(Number(recordingHead.headers.get("content-length")) > 0, "Recording must not be empty");
    report.inputs = { layoutUrl: config.baseline ? null : layoutUrl, recordUrl,
      layoutSha256: config.baseline ? null : hash(layoutText), panelIds: allIds,
      recordingBytes: recordingHead.headers.get("content-length"), recordingEtag: recordingHead.headers.get("etag") };
    checked("actual_layout_and_nonempty_recording_readable", report.inputs);

    step("launch isolated background browser and install read-only network guard");
    browser = await chromium.launch({ executablePath: config.chromePath, headless: true,
      args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
    report.browserVersion = browser.version();
    report.rendererScope = "Independent headless system Chrome with software ANGLE; not the daily browser or a GPU performance measurement";
    const context = await browser.newContext({ viewport: config.viewport, locale: "en-US", serviceWorkers: "block",
      isMobile: !!config.mobile, hasTouch: !!config.mobile });
    await context.route("**/*", async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (["data:", "blob:"].includes(url.protocol)) return route.continue();
      const item = { method: request.method(), url: url.origin + url.pathname, resourceType: request.resourceType() };
      report.requests.push(item);
      if (!["GET", "HEAD"].includes(item.method) || url.origin !== config.baseUrl) {
        report.blockedRequests.push(item);
        return route.abort("blockedbyclient");
      }
      return route.continue();
    });
    assert.equal(typeof context.routeWebSocket, "function", "Playwright must support WebSocket isolation");
    await context.routeWebSocket("**/*", socket => {
      report.websockets.push({ url: new URL(socket.url()).origin });
      socket.close({ code: 1008, reason: "Recording review is read-only" });
    });
    page = await context.newPage();
    page.setDefaultTimeout(config.timeoutMs);
    page.on("pageerror", error => report.pageErrors.push(error.message));
    page.on("console", message => { if (message.type() === "error") report.consoleErrors.push(message.text().slice(0, 2000)); });
    const query = new URLSearchParams({ ds: "remote-file", "ds.url": recordUrl, layoutUrl });
    if (config.baseline) query.delete("layoutUrl");
    const deepLink = config.baseline ? `${config.baseUrl}/?${query}`
      : new URL(config.mobile ? config.mobileEntryPath : config.desktopEntryPath, config.baseUrl).href;
    report.deepLink = deepLink;
    const screenshot = async name => {
      const file = path.join(output, `${name}.png`);
      await page.screenshot({ path: file, fullPage: true });
      report.screenshots.push(file);
      save();
    };
    const initialResponse = await page.goto(deepLink, { waitUntil: "domcontentloaded", timeout: config.timeoutMs });
    report.initialResponseUrl = initialResponse?.url();
    if (!config.baseline) {
      const redirected = new URL(initialResponse.url());
      assert.equal(redirected.searchParams.get("ds"), "remote-file");
      assert.equal(redirected.searchParams.get("ds.url"), recordUrl);
      assert.equal(redirected.searchParams.get("layoutUrl"), layoutUrl);
      assert.equal(redirected.searchParams.get("time"), "0.04");
      checked("short_entry_redirects_to_bound_data_layout_and_first_frame_time");
    }
    if (config.mobile) {
      report.actualViewport = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight,
        visualWidth: window.visualViewport?.width, visualHeight: window.visualViewport?.height,
        viewportMeta: document.querySelector('meta[name="viewport"]')?.getAttribute("content") ?? null }));
      save();
      assert.equal(report.actualViewport.width, config.viewport.width,
        "Mobile page is using a desktop layout viewport rather than the configured phone width");
      assert.equal(report.actualViewport.height, config.viewport.height,
        "Mobile page is using a scaled desktop layout height");
    }
    await expect(page.getByTestId("play-button")).toBeEnabled({ timeout: config.timeoutMs });
    for (const type of expectedTypes) for (const id of allIds[type]) await expect(panelById(page, id)).toBeVisible();
    let episode = panelByType(page, "EpisodeReview").first();
    if (config.mobile) {
      step("measure the native two-panel mobile layout on a 390 by 844 touch viewport");
      const rect = locator => locator.evaluate(node => {
        const b = node.getBoundingClientRect();
        return { x: b.x, y: b.y, width: b.width, height: b.height, scrollWidth: node.scrollWidth,
          clientWidth: node.clientWidth, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight };
      });
      report.mobile = { viewport: config.viewport, panels: {}, limitations: [] };
      for (const type of expectedTypes) for (const id of allIds[type]) report.mobile.panels[id] = await rect(panelById(page, id));
      report.mobile.document = await page.evaluate(() => ({ width: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth, height: document.documentElement.scrollHeight, viewportHeight: window.innerHeight }));
      const episodeRect = await rect(episode);
      if (episodeRect.width < 280) report.mobile.limitations.push(`EpisodeReview is only ${episodeRect.width.toFixed(1)} CSS pixels wide; not accepted as a comfortable mobile reading layout.`);
      assert(report.mobile.document.width <= report.mobile.document.viewportWidth + 1, "Mobile document must not overflow horizontally");
      await episode.getByText("回合最终结果", { exact: true }).scrollIntoViewIfNeeded();
      await expect(episode.getByText("回合最终结果", { exact: true })).toBeInViewport();
      await expect(episode.getByText(/独立验收：通过/)).toBeInViewport();
      checked("mobile_episode_report_readable_in_native_two_panel_layout", { episodeRect });
      const initialMobileImage = panelById(page, ids.Image).locator("canvas").first();
      await expect(initialMobileImage).toBeVisible();
      await expect.poll(async () => rasterStats(await initialMobileImage.screenshot()).quantizedColors).toBeGreaterThan(10);
      checked("mobile_initial_camera_frame_drawn_without_pressing_play");
      await screenshot("01-mobile-overview");
      const timestamp = page.getByTestId("PlaybackTime-text").locator("input");
      const before = await timestamp.inputValue();
      await page.getByTestId("play-button").tap();
      await expect.poll(() => timestamp.inputValue()).not.toBe(before);
      await page.getByTestId("play-button").tap();
      await expect(page.getByRole("button", { name: "Play", exact: true })).toBeVisible();
      checked("mobile_native_play_pause_reachable", { before, after: await timestamp.inputValue() });

      step("seek the actual episode from the native mobile layout");
      const mobileStages = episode.getByRole("button").filter({ hasText: /\s[\d.]+s$/ });
      const labels = await mobileStages.allTextContents();
      assert(labels.length >= 3, "Mobile episode must expose actual stage controls");
      const target = labels.at(-1), seconds = Number(target.match(/([\d.]+)s$/)?.[1]);
      assert(Number.isFinite(seconds));
      await mobileStages.last().scrollIntoViewIfNeeded();
      await expect(mobileStages.last()).toBeInViewport();
      await mobileStages.last().tap();
      await expect.poll(async () => (await physicalTime(episode)).current).toBeCloseTo(seconds, 1);
      checked("mobile_episode_stage_seek_reachable", { target, seconds });
      await screenshot("02-mobile-episode-seek");
      await expect(panelById(page, ids.Image)).toBeVisible();
      const mobileImage = panelById(page, ids.Image).locator("canvas").first();
      await expect(mobileImage).toBeVisible();
      const mobileRaster = rasterStats(await mobileImage.screenshot());
      assert(mobileRaster.quantizedColors > 10, "Native mobile camera must draw the real image");
      checked("mobile_camera_stays_available_after_stage_seek", { raster: mobileRaster });
      await screenshot("03-mobile-after-seek");
      report.mobile.overviewReadingAccepted = report.mobile.limitations.length === 0;
      report.mobile.touchPlaybackAndStageAccepted = true;
    } else if (!config.baseline) {
    await expect(episode.getByText("回合最终结果", { exact: true })).toBeVisible();
    await expect(episode.getByText(/仿真录制回放/)).toBeVisible();
    await expect(episode.getByText(/独立验收：通过/)).toBeVisible();
    await expect(episode.getByText(/来源绑定：通过/)).toBeVisible();
    checked("native_panels_and_bound_episode_report_visible", { physicalTime: await physicalTime(episode) });

    step("check real image, scene and plot raster output");
    const rasters = {};
    for (const type of ["Image", "3D", "Plot"]) {
      for (const id of allIds[type]) {
      const root = panelById(page, id);
      await expect(root.locator("canvas").first()).toBeVisible();
      const canvas = root.locator("canvas").first();
      const result = await expect.poll(async () => {
        const buffer = await canvas.screenshot();
        rasters[id] = rasterStats(buffer);
        return rasters[id].quantizedColors;
      }, { timeout: config.timeoutMs, message: `${type} canvas must contain drawn content` }).toBeGreaterThan(10);
      void result;
      assert(rasters[id].width >= 40 && rasters[id].height >= 40, `${type} canvas is too small`);
      fs.writeFileSync(path.join(output, `${id.replace(/[^a-zA-Z0-9_-]/g, "_")}-initial.png`), await canvas.screenshot());
      }
    }
    await expect(panelById(page, ids.Plot).getByTestId("plot-legend-row-path-label").first()).toBeVisible();
    checked("native_image_3d_plot_rendered", { rasters });
    await screenshot("01-loaded");

    step("seek through recorded stages using real EpisodeReview controls");
    const eventButtons = episode.getByRole("button").filter({ hasText: /\s[\d.]+s$/ });
    const labels = await eventButtons.allTextContents();
    const events = labels.map((label, index) => ({ label: label.trim(), index,
      seconds: Number(label.match(/([\d.]+)s$/)?.[1]) })).filter(event => Number.isFinite(event.seconds));
    assert(events.length >= 3, "At least three recorded stage seek targets are required");
    const first = events[0];
    // Use the latest enabled recorded stage: approach can leave the object static.
    let later;
    for (const event of [...events].reverse()) {
      if (event.seconds > first.seconds + 8 && await eventButtons.nth(event.index).isEnabled()) {
        later = event;
        break;
      }
    }
    assert(later, "Recording must expose a materially later stage");
    await eventButtons.nth(first.index).click();
    await expect.poll(async () => (await physicalTime(episode)).current).toBeCloseTo(first.seconds, 1);
    const firstImages = {};
    for (const type of ["Image", "3D"]) firstImages[type] = await panelById(page, ids[type]).locator("canvas").first().screenshot();
    const framing = { start: greenObjectBounds(firstImages["3D"]) };
    const held = events.find(event => /^持物\s/.test(event.label));
    assert(held, "The actual held-object stage is needed for three-view framing acceptance");
    await eventButtons.nth(held.index).click();
    await expect.poll(async () => (await physicalTime(episode)).current).toBeCloseTo(held.seconds, 1);
    framing.held = greenObjectBounds(await panelById(page, ids["3D"]).locator("canvas").first().screenshot());
    await screenshot("02-held-object");
    await eventButtons.nth(later.index).click();
    await expect.poll(async () => (await physicalTime(episode)).current).toBeCloseTo(later.seconds, 1);
    const laterRaster = {};
    for (const type of ["Image", "3D"]) {
      await expect.poll(async () => hash(await panelById(page, ids[type]).locator("canvas").first().screenshot()),
        { timeout: config.timeoutMs, message: `${type} should redraw a different recorded stage` }).not.toBe(hash(firstImages[type]));
      laterRaster[type] = rasterStats(await panelById(page, ids[type]).locator("canvas").first().screenshot());
    }
    framing.settled = greenObjectBounds(await panelById(page, ids["3D"]).locator("canvas").first().screenshot());
    checked("recorded_green_object_fully_framed_at_start_hold_and_settle", { framing });
    const laterStageText = await episode.innerText();
    await screenshot("02-later-stage");
    await eventButtons.nth(first.index).click();
    await expect.poll(async () => (await physicalTime(episode)).current).toBeCloseTo(first.seconds, 1);
    await expect(episode.getByText(/^当前阶段：/)).not.toHaveText(laterStageText.match(/当前阶段：[^\n]+/)?.[0] ?? "invalid-stage");
    checked("stage_seek_updates_time_image_scene_and_rewinds_episode", { first, later, laterRaster });
    await screenshot("03-rewound");

    step("test upstream playback controls without sending commands");
    const beforePlay = (await physicalTime(episode)).current;
    await page.getByTestId("play-button").click();
    await expect.poll(async () => (await physicalTime(episode)).current).toBeGreaterThan(beforePlay + 0.1);
    await page.getByTestId("play-button").click();
    await expect(page.getByRole("button", { name: "Play", exact: true })).toBeVisible();
    const paused = (await physicalTime(episode)).current;
    await page.getByTestId("seek-forward-button").click();
    await expect.poll(async () => (await physicalTime(episode)).current).toBeGreaterThan(paused);
    checked("upstream_play_pause_and_seek_buttons_change_recording_time");

    step("save a user layout edit, then reload without importing the layout again");
    await episode.getByTestId("panel-menu").click();
    await page.getByRole("menuitem", { name: "Split down", exact: true }).click();
    await expect(panelByType(page, "EpisodeReview")).toHaveCount(2);
    if (!await page.getByTestId("layouts-left").isVisible()) await page.getByTestId("left-sidebar-button").click();
    await page.getByTestId("layouts-left").click();
    const layoutName = path.basename(config.layoutPath, ".json");
    const layoutRow = page.getByRole("listitem").filter({ hasText: layoutName }).first();
    await expect(layoutRow).toBeVisible();
    await layoutRow.hover();
    await layoutRow.getByTestId("layout-actions").click();
    await page.getByRole("menuitem", { name: "Save changes", exact: true }).click();
    await expect(layoutRow.getByTestId("unsaved-changes-icon")).toHaveCount(0);
    const savedUrl = new URL(page.url());
    savedUrl.searchParams.delete("layoutUrl");
    assert(!savedUrl.searchParams.has("layoutUrl"));
    await page.goto(savedUrl.href, { waitUntil: "domcontentloaded" });
    await expect(panelByType(page, "EpisodeReview")).toHaveCount(2);
    await expect(panelByType(page, "EpisodeReview").first().getByText("回合最终结果", { exact: true })).toBeVisible();
    checked("saved_layout_reloads_without_layoutUrl", { url: savedUrl.href, episodePanels: 2 });
    await screenshot("04-saved-layout-reloaded");

    step("remove a duplicate panel, save and reload the original four-panel workspace");
    await panelByType(page, "EpisodeReview").last().getByTestId("panel-menu").click();
    await page.getByTestId("panel-menu-remove").click();
    await expect(panelByType(page, "EpisodeReview")).toHaveCount(1);
    await page.getByTestId("layouts-left").click();
    const rowAfter = page.getByRole("listitem").filter({ hasText: layoutName }).first();
    await rowAfter.hover();
    await rowAfter.getByTestId("layout-actions").click();
    await page.getByRole("menuitem", { name: "Save changes", exact: true }).click();
    await expect(rowAfter.getByTestId("unsaved-changes-icon")).toHaveCount(0);
    await page.reload({ waitUntil: "domcontentloaded" });
    for (const type of expectedTypes) await expect(panelByType(page, type)).toHaveCount(allIds[type].length);
    episode = panelByType(page, "EpisodeReview").first();
    await expect(episode.getByText("回合最终结果", { exact: true })).toBeVisible();
    await expect(episode.getByText(/独立验收：通过/)).toBeVisible();
    checked("removed_panel_stays_removed_and_remaining_real_panels_recover");
    await screenshot("05-final-workspace");
    } else {
      checked("baseline_actual_remote_record_loaded_without_custom_layout");
      await screenshot("01-baseline-loaded");
      step("baseline native playback responds to actual MCAP time");
      const timestamp = page.getByTestId("PlaybackTime-text").locator("input");
      const before = await timestamp.inputValue();
      await page.getByTestId("play-button").click();
      await expect.poll(() => timestamp.inputValue()).not.toBe(before);
      await page.getByTestId("play-button").click();
      await expect(page.getByRole("button", { name: "Play", exact: true })).toBeVisible();
      checked("baseline_native_playback_advances_record_time", { before, after: await timestamp.inputValue() });
      await screenshot("02-baseline-playback");
    }

    assert(report.requests.some(request => request.url.endsWith(config.recordPath)), "Browser must actually request the MCAP");
    assert.equal(report.blockedRequests.length, 0, "Read-only review attempted a write or external request; see blockedRequests");
    assert.equal(report.websockets.length, 0, "Historical review must not create a live WebSocket");
    assert.equal(report.pageErrors.length, 0, "Unhandled browser errors remain");
    checked("zero_motion_or_other_write_requests_and_no_live_connection", {
      requestCount: report.requests.length, blockedRequests: report.blockedRequests, websockets: report.websockets,
    });
    if (!config.baseline) {
      const finalLayout = await fetch(layoutUrl).then(response => response.text());
      assert.equal(hash(finalLayout), report.inputs.layoutSha256, "Layout source changed during acceptance");
    }
    const finalHead = await fetch(recordUrl, { method: "HEAD" });
    assert.equal(finalHead.headers.get("etag"), report.inputs.recordingEtag, "Recording changed during acceptance");
    assert.equal(finalHead.headers.get("content-length"), report.inputs.recordingBytes);
    checked("input_assets_unchanged");
    report.passed = true;
  } catch (error) {
    report.errors.push(error.stack ?? String(error));
    if (page && !page.isClosed()) {
      try {
        const file = path.join(output, "failure.png");
        await page.screenshot({ path: file, fullPage: true, timeout: 5000 });
        report.screenshots.push(file);
        report.failureUrl = page.url();
        report.failureText = (await page.locator("body").innerText({ timeout: 5000 })).slice(0, 18000);
      } catch (captureError) { report.errors.push(`Failure capture: ${captureError.message}`); }
    }
  } finally {
    if (browser) await browser.close();
    report.finishedAt = new Date().toISOString();
    save();
  }
  console.log(JSON.stringify({ passed: report.passed, checks: report.checks.length, output, errors: report.errors.map(error => error.split("\n")[0]) }));
  if (!report.passed) process.exitCode = 1;
}

async function main() {
  const config = argumentsFrom(process.argv.slice(2));
  if (config.help) {
    console.log("node run-review.cjs [--baseline | --mobile] [--url http://127.0.0.1:5186] [--output DIRECTORY] [--chrome EXECUTABLE] [--timeout-ms 60000]");
    return;
  }
  await run(config);
}

if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
