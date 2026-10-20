// Same browser station entry: editable EGO example -> real PX4/Gazebo flight.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
const source = '/home/muqiao/dev/ros2/projects/drone/examples/ego-obstacle.json';
const output = process.env.DRONE_QA_OUTPUT ?? path.join(__dirname, 'output/drone-ego-execution');
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, checks: [], posts: [], pageErrors: [] };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
const terminal = task => ['succeeded', 'failed', 'cancelled'].includes(task.status);
const checked = name => { result.checks.push(name); save(); console.log(name); };
const taskUrl = id => `${base}/api/drone/tasks/${id}`;
const readTask = async (request, id) => {
  const response = await request.get(taskUrl(id));
  assert(response.ok());
  result.task = await response.json();
  save();
  return result.task;
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, acceptDownloads: true });
  let activeId;
  page.on('pageerror', error => { result.pageErrors.push(error.message); save(); });
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/drone/tasks')) {
      result.posts.push({ url: request.url(), body: request.postDataJSON() });
      save();
    }
  });
  const exportDocument = async name => {
    const pending = page.waitForEvent('download');
    await panel.getByRole('button', { name: '导出 JSON', exact: true }).click();
    const file = path.join(output, name);
    await (await pending).saveAs(file);
    return JSON.parse(fs.readFileSync(file, 'utf8')).station;
  };
  const panel = page.getByTestId('panel-mouseenter-container RobotStation!dronestation');
  try {
    await page.goto(`${base}/drone-station`);
    await expect(panel.getByRole('button', { name: '复制为新任务', exact: true })).toBeEnabled({ timeout: 90000 });
    const runtime = await (await page.request.get(`${base}/api/drone/runtime`)).json();
    assert(runtime.executor.planners.includes('ego'));
    const example = JSON.parse(fs.readFileSync(source, 'utf8'));
    await panel.locator('input[type=file]').setInputFiles(source);
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(example.name);
    await expect(panel.getByRole('combobox', { name: /^路径方式/ })).toContainText('EGO-Swarm 自动绕障');
    await panel.locator('[aria-label="工作站对象树"]').getByRole('button', { name: /可移动箱形障碍/ }).click();
    for (const [index, dimension] of ['宽', '深', '高'].entries()) {
      await expect(panel.getByLabel(`${dimension}（m）`, { exact: true })).toHaveValue(String(example.nodes.find(node => node.id === 'box').size[index]));
    }
    const imported = await exportDocument('imported-example.json');
    assert.deepEqual(imported.nodes, example.nodes);
    assert.deepEqual(imported.flight, example.flight);
    assert.deepEqual(imported.nodes.find(node => node.id === 'base').position, [1, -1, 0]);
    await panel.getByRole('button', { name: '保存草稿', exact: true }).click();
    await panel.getByText('草稿与当前布局已保存，刷新页面可继续编辑。也可导出 JSON 备份。', { exact: true }).waitFor();
    await page.reload();
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(example.name, { timeout: 60000 });
    assert.deepEqual(await exportDocument('reloaded-example.json'), imported);
    checked('ego-example-obstacle-size-and-base-xy-preserved-through-import-save-reload');
    const response = page.waitForResponse(value => value.url() === `${base}/api/drone/tasks` && value.request().method() === 'POST');
    await panel.getByRole('button', { name: '起飞并执行仿真', exact: true }).click();
    const submitted = await response;
    assert(submitted.ok());
    result.task = await submitted.json();
    activeId = result.task.id;
    save();
    await expect(panel.getByText(`原任务 ID：${activeId}`, { exact: true })).toBeVisible();
    await expect.poll(async () => {
      const task = await readTask(page.request, activeId);
      return terminal(task) || (task.telemetry?.armed === true && task.telemetry.altitude_m > 1);
    }, { timeout: 180000, intervals: [500, 1000] }).toBe(true);
    assert(!terminal(result.task), result.task.message);
    await panel.getByRole('region', { name: '当前仿真任务' }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'ego-airborne.png'), fullPage: true });
    await expect.poll(async () => terminal(await readTask(page.request, activeId)), { timeout: 360000, intervals: [1000] }).toBe(true);
    activeId = undefined;
    const task = result.task;
    assert.equal(task.status, 'succeeded', task.message);
    assert.equal(task.report.passed, true);
    assert.equal(task.report.planner, 'ego');
    assert.equal(task.report.collision_free, true);
    assert.equal(task.report.landed, true);
    assert.equal(task.report.disarmed, true);
    assert.equal(task.telemetry.armed, false);
    assert.equal(task.telemetry.landed, 'ON_GROUND');
    assert.equal(task.report.visits.filter(visit => visit.phase === 'waypoint').length, 3);
    assert(task.report.visits.some(visit => visit.phase === 'returning_home'));
    assert(task.report.visits.every(visit => visit.truth_error_m <= .5 && visit.truth_hold_s >= 1));
    assert.equal(task.report.speed.within_requested_limit, true);
    assert(task.report.speed.gazebo_peak_m_s <= 1 && task.report.speed.mavsdk_peak_m_s <= 1);
    assert.deepEqual(task.station.nodes, imported.nodes);
    assert.deepEqual(task.station.flight, imported.flight);
    const report = await page.request.get(new URL(task.artifacts.report, base).href);
    assert(report.ok());
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(await report.json(), null, 2));
    const mcap = await page.request.get(new URL(task.artifacts.mcap, base).href, { headers: { Range: 'bytes=0-511' } });
    assert.equal(mcap.status(), 206);
    await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText('执行完成', { timeout: 30000 });
    await expect(panel.getByRole('link', { name: '回看本次三维轨迹 ↗', exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'ego-success.png'), fullPage: true });
    checked('browser-ego-three-waypoints-planned-return-and-land-disarm-without-collision');
    checked('independent-truth-and-mavsdk-speed-below-1mps');
    await page.reload();
    await expect(panel.getByText(`原任务 ID：${task.id}`, { exact: true })).toBeVisible({ timeout: 60000 });
    await expect(panel.getByRole('region', { name: '当前仿真任务' })).toContainText('执行完成');
    await expect(panel.getByRole('combobox', { name: /^历史任务/ })).toContainText(task.submittedAt);
    assert.equal(result.posts.length, 1, 'Reload and history must not submit a second flight');
    assert.deepEqual(result.pageErrors, []);
    checked('completed-ego-task-and-history-survive-refresh-with-one-total-task-post');
    result.passed = true;
    save();
    console.log(JSON.stringify({ passed: true, id: task.id, checks: result.checks, output }));
  } catch (error) {
    result.failure = error.stack ?? error.message;
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally {
    if (activeId) {
      try {
        const task = await readTask(page.request, activeId);
        if (!terminal(task)) {
          await page.request.post(`${taskUrl(activeId)}/cancel`, { data: {} });
          await expect.poll(async () => terminal(await readTask(page.request, activeId)), { timeout: 120000, intervals: [1000] }).toBe(true);
          result.cleanup = result.task;
        }
      } catch (error) { result.cleanupError = error.message; }
    }
    save();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
