// Native PX4 draft acceptance; all task writes are blocked in this browser context.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
const output = path.join(__dirname, 'output/drone-task-drafts');
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, checks: [], errors: [], requests: [] };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
const exported = async (page, panel, name) => {
  const pending = page.waitForEvent('download');
  await panel.getByRole('button', { name: '导出 JSON', exact: true }).click();
  const file = path.join(output, name);
  await (await pending).saveAs(file);
  return JSON.parse(fs.readFileSync(file, 'utf8'));
};
const observe = page => {
  page.on('pageerror', error => result.errors.push(error.message));
  page.on('request', request => {
    if (!['GET', 'HEAD'].includes(request.method())) {
      let body;
      try { body = request.postDataJSON(); } catch { body = request.postData(); }
      result.requests.push({ method: request.method(), url: request.url(), body });
    }
  });
};
const panelFor = (page, platform) => page.getByTestId(
  `panel-mouseenter-container RobotStation!${platform === 'drone' ? 'drone' : 'so101'}station`,
);
const taskSnapshot = async (request, platform) => {
  const response = await request.get(`${base}/api/${platform}/tasks`);
  assert(response.ok(), `Cannot read ${platform} task history: ${response.status()}`);
  return (await response.json()).tasks.map(({ id, status }) => ({ id, status }));
};
(async () => {
  const browser = await chromium.launch({
    executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'],
  });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1100 }, acceptDownloads: true,
  });
  const restore = {};
  await context.route(/\/api\/(?:so101|drone)\/tasks(?:[/?]|$)/, async route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) {
      result.errors.push(`Unexpected motion request: ${route.request().method()} ${route.request().url()}`);
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });
  try {
    const page = await context.newPage();
    observe(page);
    result.tasksBefore = {};
    for (const platform of ['drone', 'so101']) {
      result.tasksBefore[platform] = await taskSnapshot(page.request, platform);
      restore[platform] = await (await page.request.get(`${base}/api/${platform}/scene-mode`)).json();
    }
    await page.goto(base + '/drone-station');
    const panel = panelFor(page, 'drone');
    const copy = panel.getByRole('button', { name: '复制为新任务', exact: true });
    await expect(copy).toBeEnabled({ timeout: 90000 });
    const original = await exported(page, panel, 'original-drone.json');
    restore.drone.station = original.station;
    assert.equal(original.station.platform, 'px4');
    assert.equal(original.station.flight.speed_m_s, 1);
    assert.equal(original.station.program.filter(step => step.action === 'waypoint').length, 3);
    await expect(panel.getByText('飞行程序', { exact: true })).toBeVisible();
    await expect(panel.getByText('抓放程序', { exact: true })).toHaveCount(0);
    await panel.locator('[aria-label="工作站对象树"]').getByRole('button', { name: /X500 四旋翼/ }).click();
    await expect(panel.getByLabel('X（m）', { exact: true })).toBeEnabled();
    await expect(panel.getByLabel('Y（m）', { exact: true })).toBeEnabled();
    await expect(panel.getByLabel('Z（m）', { exact: true })).toBeDisabled();
    await copy.click();
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(original.station.name + ' 副本');
    await expect(panel.getByLabel('对象名称', { exact: true })).toHaveValue('起飞高度');
    await expect(panel.getByRole('region', { name: '当前仿真任务' })).toHaveCount(0);
    await panel.locator('[aria-label="工作站对象树"]').getByRole('button', { name: /航点 2/ }).click();
    await expect(panel.getByLabel('Z（m）', { exact: true })).toBeEnabled();
    const desired = [2.5, 3.5, 2.8];
    for (const [index, axis] of ['X', 'Y', 'Z'].entries()) {
      await panel.getByLabel(`${axis}（m）`, { exact: true }).fill(String(desired[index]));
    }
    await panel.getByLabel('速度上限（m/s）', { exact: true }).fill('1.2');
    const runtime = await (await page.request.get(base + '/api/drone/runtime')).json();
    result.egoAvailable = runtime.executor?.planners?.includes('ego') === true;
    await panel.getByRole('combobox', { name: /^路径方式/ }).click();
    const ego = page.getByRole('option', { name: /EGO-Swarm/ });
    if (result.egoAvailable) {
      await expect(ego).not.toHaveAttribute('aria-disabled', 'true');
    } else {
      await expect(ego).toHaveAttribute('aria-disabled', 'true');
    }
    await page.keyboard.press('Escape');
    await panel.getByRole('button', { name: '添加障碍', exact: true }).click();
    for (const [index, axis] of ['X', 'Y', 'Z'].entries()) {
      await expect(panel.getByLabel(`${axis}（m）`, { exact: true })).toHaveValue(String([1.5, 0, 1][index]));
    }
    for (const [index, dimension] of ['宽', '深', '高'].entries()) {
      await panel.getByLabel(`${dimension}（m）`, { exact: true }).fill(String([0.8, 1.2, 2.4][index]));
    }
    await panel.getByRole('button', { name: '保存草稿', exact: true }).click();
    await panel.getByText('草稿与当前布局已保存，刷新页面可继续编辑。也可导出 JSON 备份。', { exact: true }).waitFor();
    const saved = await exported(page, panel, 'saved-drone.json');
    assert.deepEqual(saved.station.nodes.find(node => node.id === 'wp2').position, desired);
    assert.equal(saved.station.flight.speed_m_s, 1.2);
    assert.deepEqual(saved.station.nodes.find(node => node.kind === 'obstacle').size, [0.8, 1.2, 2.4]);
    assert.deepEqual(saved.station.program, original.station.program);
    await panel.getByText('场景与程序', { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'desktop-drone.png'), fullPage: true });
    await page.reload();
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(saved.station.name, { timeout: 60000 });
    assert.deepEqual(await exported(page, panel, 'reloaded-drone.json'), saved);
    await expect(panel.getByRole('region', { name: '当前仿真任务' })).toHaveCount(0);
    await expect(panel.getByText(/^原任务 ID：/)).toHaveCount(0);
    const imported = JSON.parse(JSON.stringify(saved));
    imported.station.name += ' JSON复用';
    await panel.locator('input[type=file]').setInputFiles({
      name: 'drone-reuse.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)),
    });
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(imported.station.name);
    const reimported = await exported(page, panel, 'imported-drone.json');
    assert.deepEqual(reimported.station.nodes, imported.station.nodes);
    assert.deepEqual(reimported.station.flight, imported.station.flight);
    assert.deepEqual(reimported.station.program.map(({ id, ...step }) => step), imported.station.program.map(({ id, ...step }) => step));
    result.checks.push('px4-template-and-three-waypoints', 'copy-clears-task-without-motion', 'editable-waypoint-xyz-and-speed', 'obstacle-dimensions-survive-save-reload-and-import', 'save-reload-exact-document', 'json-preserves-flight-intent', 'ego-option-matches-runtime');

    await page.goto(base + '/so101-station');
    const arm = panelFor(page, 'so101');
    await expect(arm.getByRole('button', { name: '复制为新任务', exact: true })).toBeEnabled({ timeout: 60000 });
    const armOriginal = await exported(page, arm, 'so101-default.json');
    restore.so101.station = armOriginal.station;
    assert.equal(armOriginal.station.platform ?? 'so101', 'so101');
    assert.equal(armOriginal.station.program.length, 8);
    await expect(arm.getByText('抓放程序', { exact: true })).toBeVisible();
    await expect(arm.getByLabel('速度上限（m/s）', { exact: true })).toHaveCount(0);
    await expect(arm.getByRole('button', { name: '规划并运行仿真', exact: true })).toBeVisible();
    await arm.getByRole('button', { name: '编辑预览', exact: true }).click();
    await expect.poll(async () => (await (await page.request.get(base + '/api/so101/scene-mode')).json()).mode, { timeout: 30000 }).toBe('draft');
    await arm.locator('input[type=file]').setInputFiles({
      name: 'wrong-platform.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(saved)),
    });
    await arm.getByText('文件与当前机器人类型不同，请在对应工作台入口导入；当前草稿未改变。', { exact: true }).waitFor();
    assert.deepEqual(await exported(page, arm, 'so101-after-wrong-import.json'), armOriginal);
    await page.goto(base + '/drone-station');
    await expect(panelFor(page, 'drone').getByLabel('工作站名称', { exact: true })).toHaveValue(original.station.name, { timeout: 60000 });
    result.checks.push('so101-default-actions-preserved', 'cross-platform-import-keeps-original', 'same-tab-platform-switch');

    const mobile = await context.newPage();
    await mobile.setViewportSize({ width: 390, height: 844 });
    observe(mobile);
    await mobile.goto(base + '/drone-station-mobile');
    const narrow = panelFor(mobile, 'drone');
    const mobileCopy = narrow.getByRole('button', { name: '复制为新任务', exact: true });
    await expect(mobileCopy).toBeEnabled({ timeout: 60000 });
    await mobileCopy.click();
    await expect(narrow.getByLabel('Z（m）', { exact: true })).toBeEnabled();
    await narrow.getByLabel('Z（m）', { exact: true }).fill('2.4');
    const mobileExport = await exported(mobile, narrow, 'mobile-drone.json');
    assert.equal(mobileExport.station.nodes.find(node => node.id === 'takeoff').position[2], 2.4);
    result.mobileViewport = await mobile.evaluate(() => ({ width: innerWidth, height: innerHeight }));
    assert.equal(result.mobileViewport.width, 390);
    await narrow.getByText('场景与程序', { exact: true }).scrollIntoViewIfNeeded();
    const bounds = await mobileCopy.boundingBox();
    assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 391);
    assert(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await mobile.screenshot({ path: path.join(output, 'mobile-drone.png'), fullPage: true });
    result.checks.push('390px-copy-and-height-edit', 'mobile-without-page-overflow');

    result.tasksAfter = {};
    for (const platform of ['drone', 'so101']) {
      result.tasksAfter[platform] = await taskSnapshot(page.request, platform);
      assert(result.tasksBefore[platform].every(task => result.tasksAfter[platform].some(other => task.id === other.id)));
    }
    const permitted = /^\/api\/(so101|drone)\/(?:preview|scene-mode)$/;
    assert(result.requests.every(request => permitted.test(new URL(request.url).pathname)));
    for (const request of result.requests) {
      if (request.body?.station) {
        const expected = request.body.station.platform === 'px4' ? 'drone' : 'so101';
        assert(new URL(request.url).pathname.startsWith(`/api/${expected}/`));
      }
    }
    result.motionPosts = result.requests.filter(request => /\/api\/(?:so101|drone)\/tasks/.test(new URL(request.url).pathname)).length;
    assert.equal(result.motionPosts, 0);
    assert.deepEqual(result.errors, []);
    result.checks.push('both-platform-histories-retained', 'editing-uses-correct-platform-api', 'zero-task-write-requests', 'no-page-errors');
    result.passed = true;
    save();
    console.log(JSON.stringify({ passed: true, checks: result.checks, motionPosts: result.motionPosts, output }));
  } catch (error) {
    result.failure = error.stack ?? error.message;
    throw error;
  } finally {
    save();
    await context.close();
    if (process.env.STATION_RESTORE_PREVIEW !== 'false') {
      for (const [platform, previous] of Object.entries(restore)) {
        const source = previous.mode === 'task' && previous.taskId
          ? { mode: 'task', taskId: previous.taskId }
          : previous.station ? { mode: 'draft', station: previous.station } : undefined;
        if (source) {
          await fetch(`${base}/api/${platform}/scene-mode`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(source),
          }).catch(() => {});
        }
      }
    }
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
