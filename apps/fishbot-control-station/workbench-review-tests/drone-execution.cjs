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
const cancelOnly = process.env.DRONE_CANCEL_ONLY === '1';
const terminal = new Set(['succeeded', 'failed', 'cancelled']);
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, checks: [], tasks: [], posts: [], plans: [], planPosts: [], pageErrors: [], sceneTraffic: [], httpErrors: [], replayWrites: [], replayWebSockets: [], modelResponses: [] };
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
  for (const event of ['request', 'response', 'requestfailed']) page.on(event, value => {
    const request = event === 'response' ? value.request() : value;
    if (!/\/api\/drone\/(?:scene-mode|preview)$/.test(new URL(request.url()).pathname)) return;
    result.sceneTraffic.push({ event, at: new Date().toISOString(), method: request.method(), url: request.url(),
      ...(event === 'response' ? { status: value.status() } : {}),
      ...(event === 'requestfailed' ? { failure: request.failure()?.errorText } : {}) });
    save();
  });
  page.on('response', response => {
    if (response.status() >= 400) {
      result.httpErrors.push({ url: response.url(), status: response.status() });
      save();
    }
  });
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/drone/plans') {
      result.planPosts.push({ url: request.url(), body: request.postDataJSON() });
      save();
    }
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
const preparePlan = async (page, panel, station) => {
  if (station.flight?.planner !== 'ego') return undefined;
  const before = result.posts.length;
  const planButton = panel.getByRole('button', { name: 'EGO 起飞前预演', exact: true });
  await expect(planButton).toBeEnabled({ timeout: 90000 });
  const [response] = await Promise.all([
    page.waitForResponse(value => value.url() === `${base}/api/drone/plans` && value.request().method() === 'POST'),
    planButton.click(),
  ]);
  let plan = await json(response);
  const id = plan.id;
  await expect.poll(async () => {
    plan = await json(await page.request.get(`${base}/api/drone/plans/${id}`));
    return terminal.has(plan.status);
  }, { timeout: 240000, intervals: [1000] }).toBe(true);
  result.plans.push(plan);
  save();
  assert.equal(plan.status, 'succeeded', plan.message);
  assert.equal(plan.report.valid, true, plan.report.reason);
  assert.equal(plan.report.flight_control, false);
  assert(plan.report.points.length > 3);
  assert.equal(result.posts.length, before, 'Scene-model planning must not dispatch any flight control');
  await expect(panel.getByRole('region', { name: 'EGO 起飞前预演', exact: true })).toContainText('当前草稿预演有效，可以起飞。');
  checked('real-ego-preflight-for-current-draft-without-flight-post');
  return id;
};
const worldPosition = (station, id) => {
  const node = station.nodes.find(item => item.id === id);
  assert(node, `Missing node ${id}`);
  const parent = node.parent === 'world' ? [0, 0, 0] : worldPosition(station, node.parent);
  return node.position.map((value, index) => value + parent[index]);
};
const boxFootprints = station => station.nodes.filter(node => node.kind === 'obstacle' && node.enabled !== false)
  .map(node => ({ id: node.id, center: worldPosition(station, node.id), size: node.size ?? [1, 1, 2] }));
const insideFootprint = (position, box) => Math.abs(position[0] - box.center[0]) <= box.size[0] / 2
  && Math.abs(position[1] - box.center[1]) <= box.size[1] / 2;
const boxesBelow = (position, boxes) => boxes.filter(box => insideFootprint(position, box)
  && position[2] > box.center[2] + box.size[2] / 2);
const assertCancelWindow = (task, station, target, expectedVisits, expectedBoxes) => {
  assert.equal(task.phase, 'waiting', 'Cancel must still be inside the imported wait window');
  assert.equal(task.telemetry.armed, true, 'Cancel must be issued to an airborne armed task');
  assert.equal(task.report.visits.filter(visit => visit.phase === 'waypoint').length, expectedVisits);
  assert(Math.hypot(...task.pose.position.map((value, i) => value - target[i])) <= (station.flight?.acceptance?.position_tolerance_m ?? .5));
  const below = boxesBelow(task.pose.position, boxFootprints(station));
  if (expectedBoxes.length) {
    assert(below.length > 0, 'Over-box cancellation must occur above an actual box footprint');
    for (const box of expectedBoxes) assert(below.some(item => item.id === box.id), `Cancel position must remain above ${box.id}`);
  }
  return below;
};
const assertOutsideBoxes = (position, boxes, label) => {
  assert(Array.isArray(position) && position.length === 3 && position.every(Number.isFinite), `${label} must be an actual finite XYZ pose`);
  for (const box of boxes) assert(!insideFootprint(position, box), `${label} must leave box ${box.id}'s footprint`);
};
const assertOverBoxRecovery = (task, cancelWindow, boxes, truth) => {
  assert(boxes.length > 0, 'Over-box recovery requires a verified box below the cancellation pose');
  const recovery = task.report.recovery;
  const firstDescent = recovery.checks.find(check => check.kind === 'descent');
  assert(firstDescent, 'Recovery must check the original descent column first');
  assert.equal(recovery.checks[0], firstDescent, 'The original column must be checked before retreat');
  assert.equal(firstDescent.safe, false, 'The original over-box descent must be rejected');
  assert.equal(firstDescent.source, 'current_depth_occupancy');
  for (const box of boxes) assert(insideFootprint(firstDescent.target, box), `The rejected descent must be above ${box.id}`);
  assert(recovery.traversed.length > 0, 'Cancellation above a box must actually retreat');
  assert(truth.length > 0, 'Cancellation needs independent Gazebo truth samples');
  const cancelTruth = truth.reduce((nearest, sample) => Math.abs(sample.simulation_s - cancelWindow.simulation_s)
    < Math.abs(nearest.simulation_s - cancelWindow.simulation_s) ? sample : nearest);
  assert(Math.abs(cancelTruth.simulation_s - cancelWindow.simulation_s) <= .25, 'Gazebo truth must cover the cancellation instant');
  for (const box of boxes) assert(boxesBelow(cancelTruth.pose.position, [box]).length === 1, `Gazebo truth must confirm cancellation above ${box.id}`);
  const landings = truth.filter(sample => sample.phase === 'landing' && sample.simulation_s >= cancelWindow.simulation_s);
  assert(landings.length > 0, 'Gazebo truth must contain the actual landing phase after cancellation');
  for (const sample of landings) assertOutsideBoxes(sample.pose.position, boxes, 'Actual landing pose');
  assertOutsideBoxes(truth.at(-1).pose.position, boxes, 'Last Gazebo truth pose');
  assertOutsideBoxes(task.report.final_truth_pose?.position, boxes, 'Terminal Gazebo truth pose');
  assertLanded(task);
  return { firstDescent, cancelTruth, firstLandingTruth: landings[0], lastTruth: truth.at(-1),
    finalTruthPose: task.report.final_truth_pose, landingTruthSamples: landings.length };
};
const readTaskTruth = task => {
  const root = process.env.DRONE_TASKS_ROOT ?? path.join(__dirname, '../workbench-tools/output/drone-tasks');
  const directory = path.join(root, task.id);
  assert.equal(JSON.parse(fs.readFileSync(path.join(directory, 'request.json'), 'utf8')).id, task.id, 'Local truth must belong to the selected task');
  return fs.readFileSync(path.join(directory, 'truth.jsonl'), 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
};
const programMeaning = program => program.map(step => ({ action: step.action, target: step.target ?? '', seconds: step.seconds ?? 1 }));
const assertAcceptance = (task, station, complete = true) => {
  const limits = station.flight?.acceptance ?? {};
  const speed = station.flight?.speed_m_s ?? 1;
  assert.deepEqual(task.report.acceptance ?? {}, limits);
  assert.equal(task.report.collision_free, true);
  assert.equal(task.report.speed.requested_max_m_s, speed);
  assert.equal(task.report.speed.within_requested_limit, true);
  for (const key of ['gazebo_peak_m_s', 'mavsdk_peak_m_s']) assert(Number.isFinite(task.report.speed[key]) && task.report.speed[key] <= speed);
  if (limits.max_altitude_m != null) assert(Number.isFinite(task.report.maximum_altitude_m) && task.report.maximum_altitude_m <= limits.max_altitude_m);
  if (limits.min_clearance_m != null && station.nodes.some(node => node.kind === 'obstacle' && node.enabled !== false)) {
    assert(Number.isFinite(task.report.minimum_body_clearance_m) && task.report.minimum_body_clearance_m > limits.min_clearance_m);
  }
  if (complete && limits.min_cruise_speed_m_s != null) assert(task.report.speed.cruise_above_minimum_longest_s >= (limits.min_cruise_duration_s ?? 1));
  for (const [action, phase] of [['takeoff', 'taking_off'], ['waypoint', 'waypoint'], ['return_home', 'returning_home']]) {
    const expected = station.program.filter(step => step.action === action);
    const visits = task.report.visits.filter(visit => visit.phase === phase);
    if (complete) assert.equal(visits.length, expected.length, `${action} arrival count must match the imported program`);
    visits.forEach((visit, index) => {
      assert(expected[index], `Unexpected ${phase} visit`);
      assert(visit.truth_error_m <= (limits.position_tolerance_m ?? .5));
      assert(visit.truth_hold_s >= Math.max(1, action === 'return_home' ? 1 : expected[index].seconds ?? 1));
      if (action !== 'return_home') assert.deepEqual(visit.target, worldPosition(station, expected[index].target));
    });
  }
};
const startFromUi = async (page, panel, station) => {
  const planId = await preparePlan(page, panel, station);
  const pending = page.waitForResponse(response => response.url() === `${base}/api/drone/tasks` && response.request().method() === 'POST', { timeout: 30000 });
  await panel.getByRole('button', { name: '起飞并执行仿真', exact: true }).click();
  const response = await pending;
  assert.equal(response.request().postDataJSON().planId, planId);
  const task = updateTask(await json(response));
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
  const expectedPlanPosts = result.planPosts.length;
  await page.reload();
  await expect(panel.getByText(`原任务 ID：${task.id}`, { exact: true })).toBeVisible({ timeout: 60000 });
  await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText(task.submittedAt);
  await expect(panel.getByRole('button', { name: '停止并安全返回降落', exact: true })).toBeEnabled();
  assert.equal(result.posts.filter(post => new URL(post.url).pathname === '/api/drone/tasks').length, expectedPosts, 'Refresh must query the original ID without submitting');
  assert.equal(result.planPosts.length, expectedPlanPosts, 'Refresh must not submit a second preflight plan');
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
  const speedLimit = task.report.speed?.requested_max_m_s ?? task.station.flight?.speed_m_s ?? 1;
  result.speed.requestedMax_m_s = speedLimit;
  assert(maximumTelemetrySpeed <= speedLimit, `Recorded three-axis speed ${maximumTelemetrySpeed} exceeds ${speedLimit} m/s`);
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
  const requestedHeight = Math.max(...task.report.visits.map(visit => visit.target[2]));
  assert(airborne.trail.at(-1).z >= requestedHeight - (task.station.flight?.acceptance?.position_tolerance_m ?? .5), 'Recording must contain the requested route height');
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
    if (process.env.DRONE_REPLAY_TASK_ID && process.env.DRONE_REPLAY_OVERHEAD === '1') {
      await scene.getByRole('button', { name: '3D', exact: true }).click();
      await page.mouse.move(20, 20);
      result.replayCamera = 'native-overhead';
    }
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
      assert(terminal.has(first.status), 'Replay requires an existing terminal task');
      assert(first.artifacts?.mcap, 'Replay requires an existing MCAP artifact');
      result.scope = 'recording-replay-only';
      result.originalFlightStatus = first.status;
      replayUrl = `${base}/?${new URLSearchParams({ ds: 'remote-file', 'ds.url': new URL(first.artifacts.mcap, base).href, layoutUrl: `${base}/layouts/drone-review.json` })}`;
    } else {
      await page.goto(`${base}/drone-station`);
      const panel = panelFor(page);
      await expect(panel.getByRole('button', { name: '复制为新任务', exact: true })).toBeEnabled({ timeout: 90000 });
      let supplied;
      if (process.env.DRONE_STATION_FILE) {
        const document = JSON.parse(fs.readFileSync(process.env.DRONE_STATION_FILE, 'utf8'));
        supplied = document.station ?? document;
        await panel.locator('input[type=file]').setInputFiles(process.env.DRONE_STATION_FILE);
        await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(supplied.name);
      }
      let original = await exportStation(page, panel, 'default-station.json');
      assert.equal(original.platform, 'px4');
      if (supplied) {
        assert.deepEqual(original.nodes, supplied.nodes);
        assert.deepEqual(original.flight, supplied.flight);
        assert.deepEqual(programMeaning(original.program), programMeaning(supplied.program));
      }
      assert(!cancelOnly || !process.env.DRONE_COMPLETED_TASK_ID, 'Cancel-only requires a new explicitly started task');
      const cancelWaitIndex = original.program.findIndex((step, index) => step.action === 'wait'
        && original.program.slice(0, index).some(previous => previous.action === 'waypoint'));
      assert(!cancelOnly || cancelWaitIndex >= 0, 'Cancel-only requires a wait step after a waypoint');
      if (process.env.DRONE_COMPLETED_TASK_ID) {
        first = updateTask(await readTask(page.request, process.env.DRONE_COMPLETED_TASK_ID));
        await selectHistory(page, panel, first);
        original = first.station;
        await panel.locator('input[type=file]').setInputFiles({ name: 'original-station.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(original)) });
        result.reusedCompletedTask = first.id;
      } else {
        first = await startFromUi(page, panel, original);
        activeTask = first.id;
        await waitTask(page.request, first.id, task => task.telemetry?.armed === true && task.telemetry.altitude_m > 1, 'first flight becomes airborne');
        await panel.getByRole('region', { name: '当前仿真任务' }).scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(output, 'live-airborne.png'), fullPage: true });
        await refreshActiveTask(page, panel, first, 1);
        checked('browser-start-and-refresh-original-id-without-repost');
      }
      const firstId = first.id;
      if (cancelOnly) {
        const preceding = original.program.slice(0, cancelWaitIndex).filter(step => step.action === 'waypoint');
        const target = worldPosition(original, preceding.at(-1).target);
        const atWindow = await waitTask(page.request, first.id, task => task.phase === 'waiting'
          && task.report.visits.filter(visit => visit.phase === 'waypoint').length === preceding.length,
        'flight reaches the imported cancellation wait window');
        const expectedBoxes = boxesBelow(target, boxFootprints(original));
        assertCancelWindow(atWindow, original, target, preceding.length, expectedBoxes);
        await page.screenshot({ path: path.join(output, 'cancel-window.png'), fullPage: true });
        // Screenshot/UI latency must not let an expired wait window pass on a stale pose.
        const beforeClick = updateTask(await readTask(page.request, first.id));
        result.cancelBoxes = assertCancelWindow(beforeClick, original, target, preceding.length, expectedBoxes);
        result.cancelOverBox = expectedBoxes.length > 0;
        result.cancelWindow = beforeClick;
        save();
        const cancellation = page.waitForResponse(response => response.url() === `${taskUrl(first.id)}/cancel` && response.request().method() === 'POST');
        await panel.getByRole('button', { name: '停止并安全返回降落', exact: true }).click();
        await json(await cancellation);
      }
      first = await waitTask(page.request, first.id, task => terminal.has(task.status), 'first flight reaches terminal status');
      activeTask = undefined;
      assert.equal(first.status, cancelOnly ? 'cancelled' : 'succeeded', first.message);
      assert.equal(first.report.passed, !cancelOnly);
      assert.equal(first.report.planner, original.flight.planner);
      const waypoints = original.program.filter(step => step.action === 'waypoint');
      assert(waypoints.length > 0);
      const speedLimit = original.flight.speed_m_s;
      assert.equal(first.report.independent_source, 'Gazebo model pose');
      assert.equal(first.report.speed.requested_max_m_s, speedLimit);
      assert.equal(first.report.speed.within_requested_limit, true);
      assert(Number.isFinite(first.report.speed.gazebo_peak_m_s) && first.report.speed.gazebo_peak_m_s <= speedLimit);
      assert(Number.isFinite(first.report.speed.mavsdk_peak_m_s) && first.report.speed.mavsdk_peak_m_s <= speedLimit);
      assertLanded(first);
      assertAcceptance(first, original, !cancelOnly);
      if (cancelOnly) {
        assert.equal(first.report.recovery.outcome, 'landed');
        assert.equal(first.report.recovery.trigger, 'operator_cancel');
        assert.equal(first.report.cancelled_before_takeoff, undefined);
        if (result.cancelOverBox || result.cancelBoxes.length) {
          result.cancelRecoveryEvidence = assertOverBoxRecovery(first, result.cancelWindow, result.cancelBoxes, readTaskTruth(first));
          save();
          checked('over-box-cancel-rejects-first-descent-and-truth-exits-before-landing');
        }
        assert.equal(result.posts.filter(post => new URL(post.url).pathname === '/api/drone/tasks').length, 1);
        assert.equal(result.posts.filter(post => post.url.endsWith('/cancel')).length, 1);
        checked('cancel-at-requested-wait-window-validates-retreat-and-ground-disarm');
      }
      await artifactChecks(page.request, first);
      await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText(cancelOnly ? '已取消' : '执行完成', { timeout: 30000 });
      const replayLink = panel.getByRole('link', { name: '回看本次三维轨迹 ↗', exact: true });
      await expect(replayLink).toBeVisible();
      await page.screenshot({ path: path.join(output, 'live-success.png'), fullPage: true });
      checked('requested-waypoints-and-independent-land-disarm-report');
      checked('terminal-task-exposes-report-and-range-readable-mcap');

      if (!cancelOnly) {
        await panel.getByRole('button', { name: '复制为新任务', exact: true }).click();
        const changedNode = original.nodes.find(node => node.id === (waypoints[1] ?? waypoints[0]).target);
        await panel.locator('[aria-label="工作站对象树"]').getByRole('button').filter({ hasText: changedNode.name }).click();
        const changed = [changedNode.position[0] + .5, changedNode.position[1] + .5, changedNode.position[2]];
        for (const [index, axis] of ['X', 'Y', 'Z'].entries()) await panel.getByLabel(`${axis}（m）`, { exact: true }).fill(String(changed[index]));
        const copy = await exportStation(page, panel, 'copied-station.json');
        assert.deepEqual(copy.nodes.find(node => node.id === changedNode.id).position, changed);
        let second = await startFromUi(page, panel, copy);
        activeTask = second.id;
        assert.notEqual(second.id, firstId);
        assert.deepEqual(second.station.nodes.find(node => node.id === changedNode.id).position, changed);
        await waitTask(page.request, second.id, task => task.telemetry?.armed === true && task.telemetry.altitude_m > 1, 'copied flight becomes airborne');
        const expectedPosts = process.env.DRONE_COMPLETED_TASK_ID ? 1 : 2;
        await refreshActiveTask(page, panel, second, expectedPosts);
        checked('airborne-refresh-restores-task-region-and-enabled-cancel-without-repost');
        const cancellation = page.waitForResponse(response => response.url() === `${taskUrl(second.id)}/cancel` && response.request().method() === 'POST');
        await panel.getByRole('button', { name: '停止并安全返回降落', exact: true }).click();
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
      }
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
