// Real browser -> PX4 SITL flight, cooperative landing, and native MCAP replay.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = upstream('@playwright/test');
const { McapIndexedReader } = upstream('@mcap/core');
const { PNG } = upstream('pngjs');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
const output = process.env.DRONE_QA_OUTPUT ?? path.join(__dirname, 'output/drone-execution');
const terminal = new Set(['succeeded', 'failed', 'cancelled']);
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, checks: [], tasks: [], posts: [], pageErrors: [], httpErrors: [], replayWrites: [], replayWebSockets: [], modelResponses: [] };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
const checked = name => { result.checks.push(name); save(); console.log(name); };
const greenPixels = bytes => {
  const png = PNG.sync.read(bytes);
  let count = 0;
  for (let i = 0; i < png.data.length; i += 4) {
    const [red, green, blue, alpha] = png.data.subarray(i, i + 4);
    if (alpha > 200 && green > 100 && green > red * 1.2 && green > blue * 1.15) count++;
  }
  return count;
};
const panelFor = page => page.getByTestId('panel-mouseenter-container RobotStation!dronestation');
const taskUrl = id => `${base}/api/drone/tasks/${id}`;
const json = async response => {
  assert(response.ok(), `${response.status()} ${response.url()}: ${await response.text()}`);
  return response.json();
};
const readTask = async (request, id) => json(await request.get(taskUrl(id)));
const observe = page => {
  page.on('pageerror', error => { result.pageErrors.push(error.message); save(); });
  page.on('response', response => {
    if (response.status() >= 400) {
      result.httpErrors.push({ url: response.url(), status: response.status() });
      save();
    }
  });
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/(?:drone|so101)\/tasks(?:\/|$)/.test(new URL(request.url()).pathname)) {
      result.posts.push({ url: request.url(), body: request.postDataJSON() });
      save();
    }
  });
};
const exportStation = async (page, panel, filename) => {
  const pending = page.waitForEvent('download');
  await panel.getByRole('button', { name: '导出 JSON', exact: true }).click();
  const file = path.join(output, filename);
  await (await pending).saveAs(file);
  return JSON.parse(fs.readFileSync(file, 'utf8')).station;
};
const updateTask = task => {
  const index = result.tasks.findIndex(item => item.id === task.id);
  if (index === -1) result.tasks.push(task); else result.tasks[index] = task;
  save();
  return task;
};
const waitTask = async (request, id, predicate, message, timeout = 360000) => {
  let state;
  await expect.poll(async () => {
    state = updateTask(await readTask(request, id));
    return predicate(state) || terminal.has(state.status);
  }, { message, timeout, intervals: [500, 1000] }).toBe(true);
  assert(predicate(state), `${message}: ${state.status}; ${state.message}; ${JSON.stringify(state.report?.errors)}`);
  return state;
};
const startFromUi = async (page, panel) => {
  const pending = page.waitForResponse(response => response.url() === `${base}/api/drone/tasks` && response.request().method() === 'POST', { timeout: 30000 });
  await panel.getByRole('button', { name: '起飞并执行仿真', exact: true }).click();
  const task = updateTask(await json(await pending));
  await expect(panel).toContainText(task.id);
  return task;
};
const selectHistory = async (page, panel, task) => {
  const history = panel.getByRole('combobox', { name: /^历史任务/ });
  await expect(history).toBeEnabled();
  await history.click();
  await page.getByRole('option').filter({ hasText: task.submittedAt }).click();
  await expect(panel.getByText(`原任务 ID：${task.id}`, { exact: true })).toBeVisible();
};
const refreshActiveTask = async (page, panel, task, expectedPosts) => {
  result.refreshUrl = page.url();
  save();
  await page.reload();
  await expect(panel.getByText(`原任务 ID：${task.id}`, { exact: true })).toBeVisible({ timeout: 60000 });
  await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText(task.submittedAt);
  await expect(panel.getByRole('button', { name: '取消并降落', exact: true })).toBeEnabled();
  assert.equal(result.posts.filter(post => new URL(post.url).pathname === '/api/drone/tasks').length, expectedPosts, 'Refresh must query the original ID without submitting');
  const scene = await json(await page.request.get(`${base}/api/drone/scene-mode`));
  assert.equal(scene.taskId, task.id);
};
const assertLanded = task => {
  assert.equal(task.telemetry.armed, false);
  assert.equal(task.telemetry.landed, 'ON_GROUND');
  assert.equal(task.report.landed, true);
  assert.equal(task.report.disarmed, true);
};
const artifactChecks = async (request, task) => {
  assert(task.artifacts.report && task.artifacts.mcap, 'First terminal GET must expose both artifacts');
  const report = await json(await request.get(new URL(task.artifacts.report, base).href));
  assert.equal(report.task_id, task.id);
  assert.equal(report.status, task.status);
  assert.equal(report.passed, task.report.passed);
  const partial = await request.get(new URL(task.artifacts.mcap, base).href, { headers: { Range: 'bytes=0-511' } });
  assert.equal(partial.status(), 206);
  assert.equal((await partial.body()).length, 512);
  fs.writeFileSync(path.join(output, `${task.id}-report.json`), JSON.stringify(report, null, 2));
};
const replayRecording = async (browser, sourceRequest, task, replayUrl) => {
  const response = await sourceRequest.get(new URL(task.artifacts.mcap, base).href);
  assert(response.ok());
  const bytes = await response.body();
  const reader = await McapIndexedReader.Initialize({
    readable: {
      size: async () => BigInt(bytes.length),
      read: async (offset, size) => bytes.subarray(Number(offset), Number(offset + size)),
    },
  });
  let maximumTelemetrySpeed = 0;
  let speedSamples = 0;
  for await (const message of reader.readMessages({ topics: ['/drone/live/telemetry'], validateCrcs: true })) {
    const telemetry = JSON.parse(Buffer.from(message.data).toString('utf8'));
    if (Number.isFinite(telemetry.speed_m_s)) {
      maximumTelemetrySpeed = Math.max(maximumTelemetrySpeed, telemetry.speed_m_s);
      speedSamples++;
    }
  }
  result.speed = {
    maximumRecordedTelemetrySpeed_m_s: maximumTelemetrySpeed,
    telemetrySamples: speedSamples,
    maximumExecutorTelemetrySpeed_m_s: task.report.speed?.mavsdk_peak_m_s,
    maximumGazeboTruthSpeed_m_s: task.report.speed?.gazebo_peak_m_s,
  };
  assert(speedSamples > 20);
  assert(maximumTelemetrySpeed <= 1, `Recorded three-axis speed ${maximumTelemetrySpeed} exceeds 1 m/s`);
  const scenes = [];
  for await (const message of reader.readMessages({ topics: ['/drone/live/scene'], validateCrcs: true })) {
    const value = JSON.parse(Buffer.from(message.data).toString('utf8'));
    const vehicle = value.entities.find(entity => entity.id === 'x500');
    const trail = value.entities.find(entity => entity.id === 'actual-trajectory')?.lines[0]?.points ?? [];
    if (vehicle?.models.length) scenes.push({ ns: message.logTime, seconds: Number(message.logTime) / 1e9, vehicle, trail });
  }
  assert(scenes.length > 20, 'Recording must include a real sequence of aircraft poses');
  const first = scenes[0], last = scenes.at(-1);
  const airborne = scenes.reduce((highest, frame) => (frame.trail.at(-1)?.z ?? 0) > (highest.trail.at(-1)?.z ?? 0) ? frame : highest);
  assert(airborne.trail.at(-1).z > 2.5, 'Height-changing route must be present in recorded telemetry');
  assert(last.trail.length > 20, 'Final recorded scene must contain the flown trajectory');
  const modelUrls = [...new Set(first.vehicle.models.map(model => model.url))];
  assert(modelUrls.every(url => url.startsWith('/api/drone/meshes/')), 'Recorded model paths must resolve at the replay origin');
  result.recording = { frames: scenes.length, first_s: first.seconds, airborne_s: airborne.seconds, end_s: last.seconds, modelUrls, trajectoryPoints: last.trail.length };
  save();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  await context.route('**/*', async route => {
    const request = route.request();
    if (!['GET', 'HEAD'].includes(request.method())) {
      result.replayWrites.push({ method: request.method(), url: request.url() });
      save();
      await route.abort('blockedbyclient');
    } else await route.continue();
  });
  await context.routeWebSocket('**/*', socket => {
    result.replayWebSockets.push(socket.url());
    save();
    socket.close();
  });
  let page;
  try {
    page = await context.newPage();
    observe(page);
    page.on('response', response => {
      if (new URL(response.url()).pathname.startsWith('/api/drone/meshes/')) {
        result.modelResponses.push({ url: response.url(), status: response.status() });
      }
    });
    await page.goto(replayUrl);
    await expect(page.getByTestId('PlaybackTime-text').locator('input')).toBeVisible({ timeout: 90000 });
    await expect(page.getByTestId('play-button')).toBeEnabled();
    await expect(panelFor(page)).toHaveCount(0);
    const scene = page.getByTestId('panel-mouseenter-container 3D!dronelive');
    await expect(scene).toBeVisible();
    await expect(scene.locator('canvas').first()).toBeVisible();
    result.replayInitialText = await page.locator('body').innerText();
    save();
    const timestamp = page.getByTestId('PlaybackTime-text').locator('input');
    const sceneScreens = {};
    const seek = async (frame, name) => {
      const text = `${frame.ns / 1000000000n}.${String(frame.ns % 1000000000n).padStart(9, '0')}`;
      await timestamp.fill(text);
      await timestamp.press('Enter');
      await timestamp.blur();
      await expect.poll(async () => Number(await timestamp.inputValue()), { timeout: 15000 }).toBeCloseTo(frame.seconds, 5);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      sceneScreens[name] = await scene.screenshot({ path: path.join(output, `replay-${name}-scene.png`) });
      await page.screenshot({ path: path.join(output, `replay-${name}.png`), fullPage: true });
    };
    await seek(first, 'initial');
    await expect.poll(
      () => modelUrls.every(url => result.modelResponses.some(item => new URL(item.url).pathname === url)),
      { timeout: 30000, message: 'native 3D loads all recorded model assets after seeking a known pose' },
    ).toBe(true);
    await seek(first, 'initial');
    await seek(airborne, 'airborne');
    await seek(last, 'finished');
    await seek(first, 'rewound');
    assert(!sceneScreens.initial.equals(sceneScreens.airborne), 'Native 3D image must change when seeking the flight');
    assert(!sceneScreens.airborne.equals(sceneScreens.finished), 'Native 3D image must change when seeking to the final pose');
    result.trajectoryPixels = Object.fromEntries(Object.entries(sceneScreens).map(([name, bytes]) => [name, greenPixels(bytes)]));
    assert(result.trajectoryPixels.airborne > result.trajectoryPixels.initial + 100, 'Actual green trajectory must appear in flight');
    assert(result.trajectoryPixels.rewound <= result.trajectoryPixels.initial + 20, 'Rewinding must remove the future flown trajectory');
    const beforePlay = Number(await timestamp.inputValue());
    await page.getByTestId('play-button').click();
    await expect.poll(async () => Number(await timestamp.inputValue())).toBeGreaterThan(beforePlay + .1);
    await page.getByTestId('play-button').click();
    await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
    const paused = Number(await timestamp.inputValue());
    await page.getByTestId('seek-forward-button').click();
    await expect.poll(async () => Number(await timestamp.inputValue())).toBeGreaterThan(paused);
    await expect.poll(() => result.modelResponses.length, { timeout: 15000 }).toBeGreaterThan(0);
    for (const model of result.modelResponses) {
      assert.equal(new URL(model.url).origin, new URL(base).origin);
      assert.equal(model.status, 200, `Native model failed: ${model.url}`);
    }
    for (const url of modelUrls) assert(result.modelResponses.some(item => new URL(item.url).pathname === url), `Model was not requested: ${url}`);
    assert.deepEqual(result.replayWrites, []);
    assert.deepEqual(result.replayWebSockets, []);
    const panelLogs = scene.getByRole('button', { name: /^Show logs/ });
    if (await panelLogs.isEnabled()) {
      await panelLogs.click();
      result.nativePanelLogs = await page.locator('body').innerText();
      await page.screenshot({ path: path.join(output, 'replay-panel-logs.png'), fullPage: true });
    }
    checked('native-mcap-seek-play-pause-and-rewind-without-control-requests');
    checked('native-model-assets-resolve-at-current-origin-and-trajectory-is-recorded');
  } catch (error) {
    if (page) {
      result.replayFailureUrl = page.url();
      result.replayFailureText = await page.locator('body').innerText().catch(() => '');
      await page.screenshot({ path: path.join(output, 'replay-failure.png'), fullPage: true }).catch(() => {});
      const logs = page.getByTestId('panel-mouseenter-container 3D!dronelive').getByRole('button', { name: /^Show logs/ });
      if (await logs.isEnabled().catch(() => false)) {
        await logs.click();
        result.replayLogsText = await page.locator('body').innerText();
      }
    }
    save();
    throw error;
  } finally { await context.close(); }
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, acceptDownloads: true });
  let activeTask;
  let page;
  try {
    page = await context.newPage();
    observe(page);
    await context.route(/\/api\/so101\/tasks(?:\/|$)/, async route => {
      if (!['GET', 'HEAD'].includes(route.request().method())) await route.abort('blockedbyclient');
      else await route.continue();
    });
    let first;
    let replayUrl;
    if (process.env.DRONE_REPLAY_TASK_ID) {
      first = updateTask(await readTask(page.request, process.env.DRONE_REPLAY_TASK_ID));
      assert.equal(first.status, 'succeeded');
      replayUrl = `${base}/?${new URLSearchParams({ ds: 'remote-file', 'ds.url': new URL(first.artifacts.mcap, base).href, layoutUrl: `${base}/layouts/drone-review.json` })}`;
    } else {
      await page.goto(`${base}/drone-station`);
      const panel = panelFor(page);
      await expect(panel.getByRole('button', { name: '起飞并执行仿真', exact: true })).toBeEnabled({ timeout: 90000 });
      const original = await exportStation(page, panel, 'default-station.json');
      assert.equal(original.platform, 'px4');
      assert.equal(original.flight.planner, 'waypoint');
      assert.equal(original.flight.speed_m_s, 1);
      const waypoints = original.program.filter(step => step.action === 'waypoint');
      assert.equal(waypoints.length, 3);
      assert(new Set(waypoints.map(step => original.nodes.find(node => node.id === step.target).position[2])).size > 1);
      if (process.env.DRONE_COMPLETED_TASK_ID) {
        first = updateTask(await readTask(page.request, process.env.DRONE_COMPLETED_TASK_ID));
        await selectHistory(page, panel, first);
        result.reusedCompletedTask = first.id;
      } else {
        first = await startFromUi(page, panel);
        activeTask = first.id;
        await waitTask(page.request, first.id, task => task.telemetry?.armed === true && task.telemetry.altitude_m > 1, 'first flight becomes airborne');
        await panel.getByRole('region', { name: '当前仿真任务' }).scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(output, 'live-airborne.png'), fullPage: true });
        await refreshActiveTask(page, panel, first, 1);
        checked('browser-start-and-refresh-original-id-without-repost');
      }
      const firstId = first.id;
      first = await waitTask(page.request, first.id, task => terminal.has(task.status), 'first flight reaches terminal status');
      activeTask = undefined;
      assert.equal(first.status, 'succeeded', first.message);
      assert.equal(first.report.passed, true);
      assert.equal(first.report.planner, 'waypoint');
      assert.equal(first.report.independent_source, 'Gazebo model pose');
      assert.equal(first.report.speed.requested_max_m_s, 1);
      assert.equal(first.report.speed.within_requested_limit, true);
      assert(Number.isFinite(first.report.speed.gazebo_peak_m_s) && first.report.speed.gazebo_peak_m_s <= 1);
      assert(Number.isFinite(first.report.speed.mavsdk_peak_m_s) && first.report.speed.mavsdk_peak_m_s <= 1);
      assertLanded(first);
      for (const step of waypoints) {
        const target = original.nodes.find(node => node.id === step.target).position;
        const visit = first.report.visits.find(item => JSON.stringify(item.target) === JSON.stringify(target));
        assert(visit, `Missing independent arrival: ${step.target}`);
        assert(visit.truth_error_m <= .5 && visit.truth_hold_s >= 1);
      }
      await artifactChecks(page.request, first);
      await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText('执行完成', { timeout: 30000 });
      const replayLink = panel.getByRole('link', { name: '回看本次三维轨迹 ↗', exact: true });
      await expect(replayLink).toBeVisible();
      await page.screenshot({ path: path.join(output, 'live-success.png'), fullPage: true });
      checked('three-height-changing-waypoints-and-independent-land-disarm-report');
      checked('terminal-task-exposes-report-and-range-readable-mcap');

      await panel.getByRole('button', { name: '复制为新任务', exact: true }).click();
      await panel.locator('[aria-label="工作站对象树"]').getByRole('button', { name: /航点 2/ }).click();
      const changed = [2.5, 3.5, 2.8];
      for (const [index, axis] of ['X', 'Y', 'Z'].entries()) await panel.getByLabel(`${axis}（m）`, { exact: true }).fill(String(changed[index]));
      const copy = await exportStation(page, panel, 'copied-station.json');
      assert.deepEqual(copy.nodes.find(node => node.id === 'wp2').position, changed);
      let second = await startFromUi(page, panel);
      activeTask = second.id;
      assert.notEqual(second.id, firstId);
      assert.deepEqual(second.station.nodes.find(node => node.id === 'wp2').position, changed);
      await waitTask(page.request, second.id, task => task.telemetry?.armed === true && task.telemetry.altitude_m > 1, 'copied flight becomes airborne');
      const expectedPosts = process.env.DRONE_COMPLETED_TASK_ID ? 1 : 2;
      await refreshActiveTask(page, panel, second, expectedPosts);
      checked('airborne-refresh-restores-task-region-and-enabled-cancel-without-repost');
      const cancellation = page.waitForResponse(response => response.url() === `${taskUrl(second.id)}/cancel` && response.request().method() === 'POST');
      await panel.getByRole('button', { name: '取消并降落', exact: true }).click();
      await json(await cancellation);
      second = await waitTask(page.request, second.id, task => terminal.has(task.status), 'cancelled flight lands and disarms', 120000);
      activeTask = undefined;
      assert.equal(second.status, 'cancelled', second.message);
      assertLanded(second);
      assert.equal(second.report.cancelled_before_takeoff, undefined);
      assert.equal(second.report.passed, false);
      await artifactChecks(page.request, second);
      await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText('已取消', { timeout: 30000 });
      await page.screenshot({ path: path.join(output, 'live-cancelled-on-ground.png'), fullPage: true });
      const originalAgain = await readTask(page.request, firstId);
      assert.equal(originalAgain.status, 'succeeded');
      assert.deepEqual(originalAgain.station, original);
      assert.equal(result.posts.filter(post => new URL(post.url).pathname === '/api/drone/tasks').length, expectedPosts);
      assert.equal(result.posts.filter(post => post.url.endsWith('/cancel')).length, 1);
      checked('copy-changed-target-has-new-id-with-original-task-preserved');
      checked('airborne-cancel-completes-only-after-ground-and-disarmed');
      await selectHistory(page, panel, first);
      await expect(replayLink).toBeVisible();
      replayUrl = new URL(await replayLink.getAttribute('href'), base).href;
      assert.equal(new URL(replayUrl).searchParams.get('ds'), 'remote-file');
      checked('history-selection-opens-original-task-recording');
    }
    result.replayUrl = replayUrl;
    save();
    await replayRecording(browser, page.request, first, replayUrl);
    assert.deepEqual(result.pageErrors, []);
    checked('no-browser-page-errors');
    result.passed = true;
    save();
    console.log(JSON.stringify({ passed: true, tasks: result.tasks.map(task => ({ id: task.id, status: task.status })), checks: result.checks, output }));
  } catch (error) {
    result.failure = error.stack ?? error.message;
    result.failureUrl = page?.url();
    if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally {
    if (activeTask) {
      try {
        const state = await readTask(context.request, activeTask);
        if (!terminal.has(state.status)) {
          await context.request.post(`${taskUrl(activeTask)}/cancel`, { data: {} });
          result.cleanup = await waitTask(context.request, activeTask, task => terminal.has(task.status), 'failure cleanup lands owned task', 120000);
        }
      } catch (error) { result.cleanupError = error.message; }
    }
    save();
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
