// Real saved SO101 tasks -> their own indexed MCAP and native replay. Never dispatches a task.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const requireWorkbench = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = requireWorkbench('@playwright/test');
const { McapIndexedReader } = requireWorkbench('@mcap/core');
const { PNG } = requireWorkbench('pngjs');
const zstd = requireWorkbench('@lichtblick/wasm-zstd');
const base = (process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187').replace(/\/$/, '');
const output = process.env.SO101_REPLAY_QA_OUTPUT ?? path.join(__dirname, 'output', `so101-task-replay-${Date.now()}`);
const requestedCase = process.env.TASK_REPLAY_CASE;
const customCases = process.env.SO101_REPLAY_TASKS ? JSON.parse(process.env.SO101_REPLAY_TASKS) : undefined;
const allCases = customCases ?? [
  { id: process.env.TASK_SUCCESS_ID, status: 'succeeded', label: 'success' },
  { id: process.env.TASK_CANCEL_ID, status: 'cancelled', label: 'cancelled' },
];
assert(Array.isArray(allCases) && allCases.length > 0, 'Supply saved task cases');
for (const item of allCases) {
  assert.match(item.id ?? '', /^[0-9a-f-]{36}$/i, 'Supply a real task UUID');
  assert(['succeeded', 'cancelled', 'failed'].includes(item.status), 'Supply the original terminal status');
  assert.match(item.label ?? '', /^[a-z0-9][a-z0-9-]*$/, 'Use a simple unique screenshot label');
}
assert.equal(new Set(allCases.map(item => item.id)).size, allCases.length);
assert.equal(new Set(allCases.map(item => item.label)).size, allCases.length);
if (requestedCase) assert(allCases.some(item => item.label === requestedCase), 'Unknown task label');
const cases = requestedCase ? allCases.filter(item => item.label === requestedCase) : allCases;
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, scope: requestedCase ?? (customCases ? 'selected-terminal-tasks-same-browser' : 'success-and-cancelled-same-browser'), base, output, controlPosts: [], viewWrites: [], replayWrites: [], pageErrors: [], cases: [] };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
const controlRoute = /\/api\/(?:so101|drone)\/(?:tasks|plans)(?:\/|$)/;
const observe = page => page.on('pageerror', error => { result.pageErrors.push({ url: page.url(), message: error.message }); save(); });
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.STATION_CHROME_BIN ?? '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  const replayPages = new Set();
  context.on('page', observe);
  await context.route('**/*', route => {
    const request = route.request();
    if (!['GET', 'HEAD'].includes(request.method())) {
      const row = { method: request.method(), url: request.url() };
      if (controlRoute.test(new URL(request.url()).pathname)) {
        result.controlPosts.push(row); save(); return route.abort();
      }
      let page;
      try { page = request.frame().page(); } catch { /* Worker requests have no frame. */ }
      if (page && replayPages.has(page)) {
        result.replayWrites.push(row); save(); return route.abort();
      }
      result.viewWrites.push(row);
    }
    return route.continue();
  });
  const page = await context.newPage();
  const getJson = async url => {
    const response = await context.request.get(new URL(url, base).href, { timeout: 90000 });
    assert.equal(response.status(), 200, url); return response.json();
  };
  const readMcap = async task => {
    const url = new URL(task.artifacts.mcap, base).href;
    const range = await context.request.get(url, { headers: { Range: 'bytes=0-511' } });
    assert.equal(range.status(), 206, 'Task MCAP supports indexed range requests');
    const response = await context.request.get(url, { timeout: 90000 });
    assert(response.ok()); const bytes = await response.body();
    await zstd.isLoaded;
    const reader = await McapIndexedReader.Initialize({ decompressHandlers: {
      zstd: (buffer, size) => new Uint8Array(zstd.decompress(buffer, Number(size))),
    }, readable: {
      size: async () => BigInt(bytes.length),
      read: async (offset, length) => bytes.subarray(Number(offset), Number(offset + length)),
    }});
    const facts = { bytes: bytes.length, topics: {}, first: null, last: null, sceneFrames: 0, geometryPrimitives: 0, taskRecords: 0, episodeRecords: 0, stageEvents: [] };
    for (const channel of reader.channelsById.values()) {
      assert.equal(channel.metadata.get('task_id'), task.id);
      facts.topics[channel.topic] = 0;
    }
    for await (const message of reader.readMessages({ topics: ['/so101/task', '/so101/episode', '/so101/joints', '/so101/contact', '/so101/scene'], validateCrcs: true })) {
      const topic = reader.channelsById.get(message.channelId).topic;
      facts.topics[topic]++;
      const value = JSON.parse(Buffer.from(message.data));
      const time = Number(message.logTime) / 1e9;
      if (topic === '/so101/task') {
        facts.taskRecords++;
        assert.equal(value.task_id, task.id);
        assert.equal(value.request.id, task.id);
        assert.equal(value.status, task.status);
        assert.deepEqual(value.report, task.report);
        assert.deepEqual(value.skill_evidence ?? null, task.skill_evidence ?? task.report?.skill_evidence ?? null);
      } else if (topic === '/so101/episode') {
        facts.episodeRecords++;
        assert.equal(value.run_id, task.id);
        assert.equal(value.success, task.report.passed);
        facts.stageEvents = value.stage_events;
      } else if (topic === '/so101/joints') {
        facts.first ??= time; facts.last = time;
      } else if (topic === '/so101/contact') {
        assert(Number.isFinite(value.fixed_finger_n));
        assert(Number.isFinite(value.moving_finger_n));
      } else {
        facts.sceneFrames++;
        facts.geometryPrimitives = Math.max(facts.geometryPrimitives, value.entities.reduce((total, entity) => total + ['cubes', 'spheres', 'cylinders', 'meshes', 'models', 'triangles'].reduce((count, key) => count + (entity[key]?.length ?? 0), 0), 0));
      }
    }
    assert(facts.taskRecords >= 2); assert(facts.episodeRecords >= 2);
    assert(facts.sceneFrames > 1); assert(facts.geometryPrimitives > 5);
    assert(facts.last > facts.first);
    return facts;
  };
  const selectHistory = async id => {
    const panel = page.getByTestId('panel-mouseenter-container RobotStation!so101station');
    const select = panel.getByRole('combobox', { name: '历史任务' });
    await expect(select).toBeEnabled({ timeout: 90000 });
    await select.click();
    await page.locator(`[role="option"][data-value="${id}"]`).click();
    await expect(panel).toContainText(id, { timeout: 30000 });
    await expect(panel.getByRole('link', { name: '回看本次三维轨迹 ↗', exact: true })).toBeVisible({ timeout: 30000 });
    return panel;
  };
  try {
    await page.goto(base + '/so101-station');
    for (const item of cases) {
      const task = await getJson(`/api/so101/tasks/${item.id}`);
      assert.equal(task.id, item.id); assert.equal(task.status, item.status);
      assert.equal(task.artifacts.mcap, `/api/so101/tasks/${item.id}/artifacts/mcap/episode.mcap`);
      const entry = { id: item.id, status: item.status, checks: [], mcap: await readMcap(task), screenshots: [] };
      result.cases.push(entry); save();
      assert.deepEqual(await getJson(task.artifacts.report), task.report);
      const video = await context.request.get(new URL(task.artifacts.video, base).href, { headers: { Range: 'bytes=0-511' } });
      assert.equal(video.status(), 206);
      if (item.status === 'succeeded') assert.equal(task.skill_evidence?.grasp?.postcondition_met, true);
      entry.checks.push('task-report-video-grasp-evidence-and-mcap-exact-uuid-readback');
      let panel = await selectHistory(item.id);
      const links = [ ['打开本次原始报告', task.artifacts.report], ['打开本次录像', task.artifacts.video] ];
      for (const [name, target] of links) {
        const href = await panel.getByRole('link', { name, exact: true }).getAttribute('href');
        assert.equal(new URL(href, base).href, new URL(target, base).href);
      }
      // Wait for the existing debounced layout save, without injecting browser state.
      const persistenceStarted = Date.now();
      await expect.poll(async () => page.evaluate(id => {
        const contains = value => value && typeof value === 'object' &&
          (value.executionTaskId === id || Object.values(value).some(contains));
        return Object.values(localStorage).some(raw => {
          try { return contains(JSON.parse(raw)); } catch { return false; }
        });
      }, item.id), { timeout: 15000 }).toBe(true);
      entry.layoutPersistenceWaitMs = Date.now() - persistenceStarted;
      await page.reload();
      panel = page.getByTestId('panel-mouseenter-container RobotStation!so101station');
      await expect(panel).toContainText(item.id, { timeout: 90000 });
      try {
        await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText(item.status === 'cancelled' ? '已取消' : item.status === 'failed' ? '执行失败' : '执行完成', { timeout: 10000 });
        entry.refreshPassed = true;
        entry.checks.push('history-selection-and-refresh-preserve-task-id-and-terminal-outcome');
      } catch (error) {
        entry.refreshPassed = false; entry.refreshError = error.message;
        const filename = path.join(output, `${item.label}-refresh-failure.png`);
        await page.screenshot({ path: filename, fullPage: true }); entry.screenshots.push(filename);
        // Preserve the failed refresh claim, then use the same real history UI for independent replay checks.
        panel = await selectHistory(item.id); save();
      }
      for (const [label, viewport] of [['desktop', { width: 1600, height: 1100 }], ['narrow', { width: 430, height: 932 }]]) {
        await page.setViewportSize(viewport);
        await panel.getByRole('region', { name: '当前仿真任务' }).scrollIntoViewIfNeeded();
        const filename = path.join(output, `${item.label}-station-${label}.png`);
        await page.screenshot({ path: filename, fullPage: true }); entry.screenshots.push(filename);
      }
      await page.setViewportSize({ width: 1600, height: 1100 });
      const link = panel.getByRole('link', { name: '回看本次三维轨迹 ↗', exact: true });
      const popup = page.waitForEvent('popup'); await link.click(); const replay = await popup;
      replayPages.add(replay);
      // The popup event can precede its first navigation; the initial page may have no URL.
      await replay.waitForURL(url => url.origin === new URL(base).origin,
        { waitUntil: 'domcontentloaded', timeout: 90000 });
      const url = new URL(replay.url()); entry.replayUrl = url.href; save();
      assert.equal(url.searchParams.get('ds'), 'remote-file');
      assert.equal(url.searchParams.get('ds.url'), new URL(task.artifacts.mcap, base).href);
      assert.equal(url.searchParams.get('layoutUrl'), base + '/layouts/so101-task-review.json');
      assert(!url.href.includes('/records/so101.mcap'));
      const timeInput = replay.getByTestId('PlaybackTime-text').locator('input');
      const scene = replay.getByTestId('panel-mouseenter-container 3D!so101object');
      const episode = replay.getByTestId('panel-mouseenter-container EpisodeReview!so101episode');
      await expect(timeInput).toBeVisible({ timeout: 90000 });
      await expect(episode).toContainText(item.id, { timeout: 90000 });
      await expect(scene.locator('canvas').first()).toBeVisible({ timeout: 60000 });
      const seek = async seconds => {
        await timeInput.fill(seconds.toFixed(9)); await timeInput.press('Enter'); await timeInput.blur();
        await expect.poll(async () => Number(await timeInput.inputValue())).toBeCloseTo(seconds, 5);
      };
      for (const [label, seconds] of [['initial', entry.mcap.first], ['middle', (entry.mcap.first + entry.mcap.last) / 2], ['final', entry.mcap.last], ['rewind', entry.mcap.first]]) {
        await seek(seconds);
        const filename = path.join(output, `${item.label}-3d-${label}.png`);
        const bytes = await scene.screenshot({ path: filename });
        const png = PNG.sync.read(bytes); const colors = new Set();
        for (let index = 0; index < png.data.length; index += 16) colors.add(`${png.data[index]}:${png.data[index + 1]}:${png.data[index + 2]}`);
        assert(colors.size > 20, 'Native 3D screenshot must not be a blank panel');
        entry.screenshots.push(filename); save();
      }
      const before = Number(await timeInput.inputValue());
      const play = replay.getByTestId('play-button'); await expect(play).toBeEnabled(); await play.click();
      await expect.poll(async () => Number(await timeInput.inputValue())).toBeGreaterThan(before + .1);
      if (await play.getAttribute('title') === 'Pause') await play.press('Space');
      await expect(play).toHaveAttribute('title', 'Play', { timeout: 15000 });
      const stage = episode.getByRole('button').first();
      if (await stage.count() && await stage.isEnabled()) await stage.click();
      await replay.reload();
      await expect(replay.getByTestId('panel-mouseenter-container EpisodeReview!so101episode')).toContainText(item.id, { timeout: 90000 });
      entry.checks.push('native-3d-pixel-content-seek-rewind-play-stage-seek-refresh');
      for (const [label, viewport] of [['desktop', { width: 1600, height: 1100 }], ['narrow', { width: 430, height: 932 }]]) {
        await replay.setViewportSize(viewport);
        const filename = path.join(output, `${item.label}-replay-${label}.png`);
        await replay.screenshot({ path: filename, fullPage: true }); entry.screenshots.push(filename);
      }
      await replay.close();
      // The replay tab may update the shared profile; the workcell URL must retain its own layout.
      assert(new URL(page.url()).searchParams.get('layout'), 'Workcell URL pins its saved layout name');
      await page.reload();
      panel = page.getByTestId('panel-mouseenter-container RobotStation!so101station');
      await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText(item.status === 'cancelled' ? '已取消' : item.status === 'failed' ? '执行失败' : '执行完成', { timeout: 90000 });
      await expect(panel).toContainText(item.id);
      const restoredHref = await panel.getByRole('link', { name: '回看本次三维轨迹 ↗', exact: true }).getAttribute('href');
      assert.equal(new URL(restoredHref, base).searchParams.get('ds.url'), new URL(task.artifacts.mcap, base).href);
      entry.checks.push('workcell-refresh-after-replay-tab-keeps-own-layout-and-task');
      assert.equal((await getJson(`/api/so101/tasks/${item.id}`)).status, item.status);
      entry.checks.push('playback-does-not-change-original-task-status'); save();
    }
    assert.deepEqual(result.controlPosts, []);
    assert.deepEqual(result.replayWrites, []);
    assert.deepEqual(result.pageErrors, []);
    assert(result.cases.every(item => item.refreshPassed), 'Saved layout task selection must survive refresh; see per-case evidence');
    result.passed = true; save();
  } catch (error) {
    result.error = error.stack;
    await page.screenshot({ path: path.join(output, 'station-failure.png'), fullPage: true }).catch(() => {});
    save(); throw error;
  } finally { await browser.close(); }
  console.log(JSON.stringify({ passed: result.passed, output, cases: result.cases.map(item => ({ id: item.id, checks: item.checks })), controlPosts: result.controlPosts.length, pageErrors: result.pageErrors.length }));
})().catch(error => { console.error(error); process.exitCode = 1; });
