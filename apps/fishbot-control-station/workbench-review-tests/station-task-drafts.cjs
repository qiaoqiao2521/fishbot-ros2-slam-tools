// Native draft acceptance. Task POSTs are aborted if editing accidentally attempts motion.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
const output = process.env.STATION_QA_OUTPUT ?? path.join(__dirname, 'output/station-task-drafts');
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, checks: [], errors: [], requests: [], meshes: [], mobileMeshes: [] };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
const blueWalls = (scene) => scene?.entities?.flatMap(entity => entity.cubes ?? [])
  .filter(cube => cube.color.r < 0.3 && cube.color.g > 0.3 && cube.color.g < 0.5 && cube.color.b > 0.5) ?? [];
const exported = async (page, panel, name) => {
  const pending = page.waitForEvent('download');
  await panel.getByRole('button', { name: '导出 JSON', exact: true }).click();
  const file = path.join(output, name);
  await (await pending).saveAs(file);
  return JSON.parse(fs.readFileSync(file, 'utf8'));
};
const observe = (page, meshList) => {
  page.on('pageerror', error => result.errors.push(error.message));
  page.on('request', request => {
    if (!['GET', 'HEAD'].includes(request.method())) {
      result.requests.push({ method: request.method(), url: request.url(), body: request.postDataJSON() });
    }
  });
  page.on('response', response => {
    if (response.url().includes('/api/so101/meshes/')) {
      meshList.push({ name: response.url().split('/').at(-1), status: response.status() });
    }
  });
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  let cleanupStation;
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, acceptDownloads: true });
  await context.route('**/api/so101/tasks**', async route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) {
      result.errors.push(`Unexpected motion request: ${route.request().method()} ${route.request().url()}`);
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });
  try {
    const page = await context.newPage();
    observe(page, result.meshes);
    const scene = async () => await (await page.request.get(base + '/api/so101/scene-state')).json();
    const tasksBefore = (await (await page.request.get(base + '/api/so101/tasks')).json()).tasks;
    result.tasksBefore = tasksBefore.map(({ id, status }) => ({ id, status }));
    await page.goto(base + '/so101-station');
    const panel = page.getByTestId('panel-mouseenter-container RobotStation!so101station');
    const copy = panel.getByRole('button', { name: '复制为新任务', exact: true });
    await expect(copy).toBeEnabled({ timeout: 90000 });
    const original = await exported(page, panel, 'original-draft.json');
    cleanupStation = original.station;
    const oldIdText = await panel.getByText(/^原任务 ID：/).allTextContents();
    result.originalTaskId = oldIdText[0]?.replace('原任务 ID：', '').trim();
    const originalTask = result.originalTaskId
      ? await (await page.request.get(base + '/api/so101/tasks/' + result.originalTaskId)).json()
      : undefined;
    const source = originalTask?.station ?? original.station;
    await copy.click();
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(source.name + ' 副本');
    await expect(panel.getByLabel('对象名称', { exact: true })).toHaveValue('放料坐标系');
    await expect(panel.getByLabel('Z（m）', { exact: true })).toBeEnabled();
    await expect(panel.getByRole('region', { name: '当前仿真任务' })).toHaveCount(0);
    await expect.poll(async () => (await scene()).mode, { timeout: 30000 }).toBe('draft');
    await expect.poll(async () => blueWalls((await scene()).scene).length, { timeout: 30000 }).toBe(5);
    const before = blueWalls((await scene()).scene);
    const originalPlace = source.nodes.find(node => node.id === 'place').position;
    const desired = [0.235, 0.15, 0];
    await panel.getByLabel('X（m）', { exact: true }).fill(String(desired[0]));
    await panel.getByLabel('Y（m）', { exact: true }).fill(String(desired[1]));
    await expect.poll(async () => {
      const walls = blueWalls((await scene()).scene);
      return walls.length === before.length && walls.every((wall, i) =>
        Math.abs(wall.pose.position.x - before[i].pose.position.x - (desired[0] - originalPlace[0])) < 1e-9 &&
        Math.abs(wall.pose.position.y - before[i].pose.position.y - (desired[1] - originalPlace[1])) < 1e-9 &&
        JSON.stringify(wall.size) === JSON.stringify(before[i].size));
    }, { timeout: 30000 }).toBe(true);
    result.preview = { target: desired, blueWallsBefore: before, blueWallsAfter: blueWalls((await scene()).scene) };
    await expect.poll(() => new Set(result.meshes.filter(mesh => mesh.status === 200).map(mesh => mesh.name)).size, { timeout: 30000 }).toBe(13);
    result.checks.push('copy-source-snapshot-or-draft', 'copy-selects-place-and-clears-old-results', 'place-base-height-is-editable', 'xy-moves-all-blue-tray-pieces-with-original-size', 'desktop-13-stl-loaded');
    await panel.getByRole('button', { name: '保存草稿', exact: true }).click();
    await panel.getByText('草稿与当前布局已保存，刷新页面可继续编辑。也可导出 JSON 备份。', { exact: true }).waitFor();
    const saved = await exported(page, panel, 'saved-copy.json');
    assert.deepEqual(saved.station.nodes.find(node => node.id === 'place').position, desired);
    assert.deepEqual(saved.station.program, source.program);
    await panel.getByText('场景与程序', { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'desktop-copy.png'), fullPage: true });
    await page.reload();
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(saved.station.name, { timeout: 60000 });
    const restored = await exported(page, panel, 'reloaded-copy.json');
    assert.deepEqual(restored, saved);
    await expect(panel.getByRole('region', { name: '当前仿真任务' })).toHaveCount(0);
    await expect(panel.getByText(/^原任务 ID：/)).toHaveCount(0);
    await expect(panel.getByRole('button', { name: '规划并运行仿真', exact: true })).toBeEnabled({ timeout: 15000 });
    const imported = JSON.parse(JSON.stringify(saved));
    imported.station.name = saved.station.name + ' JSON复用';
    await panel.locator('input[type=file]').setInputFiles({ name: 'reuse.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)) });
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(imported.station.name);
    const importedExport = await exported(page, panel, 'imported-copy.json');
    // Import assigns document-local instruction IDs; action order and references are unchanged.
    assert.deepEqual(importedExport.station.nodes, imported.station.nodes);
    assert.deepEqual(importedExport.station.program.map(({ id, ...step }) => step), imported.station.program.map(({ id, ...step }) => step));
    result.checks.push('save-export-reload-json-exact', 'reload-does-not-restore-old-task', 'edited-json-import-preserves-goal-and-program');
    const mobile = await context.newPage();
    await mobile.setViewportSize({ width: 390, height: 844 });
    observe(mobile, result.mobileMeshes);
    await mobile.goto(base + '/so101-station-mobile');
    const narrow = mobile.getByTestId('panel-mouseenter-container RobotStation!so101station');
    const mobileCopy = narrow.getByRole('button', { name: '复制为新任务', exact: true });
    await expect(mobileCopy).toBeVisible({ timeout: 90000 });
    result.mobileViewport = await mobile.evaluate(() => ({ width: innerWidth, height: innerHeight }));
    assert.equal(result.mobileViewport.width, 390);
    await expect.poll(() => new Set(result.mobileMeshes.filter(mesh => mesh.status === 200).map(mesh => mesh.name)).size, { timeout: 30000 }).toBe(13);
    const bounds = await mobileCopy.boundingBox();
    assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 391);
    assert(bounds.y >= 0 && bounds.y + bounds.height <= 844);
    result.mobileCopyEnabled = await mobileCopy.isEnabled();
    assert(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await mobile.screenshot({ path: path.join(output, 'mobile-copy.png'), fullPage: false });
    const tasksAfter = (await (await page.request.get(base + '/api/so101/tasks')).json()).tasks;
    result.tasksAfter = tasksAfter.map(({ id, status }) => ({ id, status }));
    // Other browser acceptance may finish or create a task in the shared store.
    // This read-only context must retain existing records and issue no task writes.
    assert(result.tasksBefore.every(task => tasksAfter.some(other => other.id === task.id)));
    assert(result.requests.every(request => ['/api/so101/preview', '/api/so101/scene-mode'].includes(new URL(request.url).pathname)));
    assert.deepEqual(result.errors, []);
    assert(result.meshes.every(mesh => mesh.status === 200));
    assert(result.mobileMeshes.every(mesh => mesh.status === 200));
    result.motionPosts = result.requests.filter(request => new URL(request.url).pathname.startsWith('/api/so101/tasks')).length;
    assert.equal(result.motionPosts, 0);
    result.checks.push('mobile-copy-visible-without-overflow', 'mobile-13-stl-loaded', 'editing-has-zero-motion-posts', 'existing-task-records-retained', 'no-page-errors-or-mesh-failures');
    result.passed = true;
    save();
    console.log(JSON.stringify({ passed: true, checks: result.checks, motionPosts: result.motionPosts, output }));
  } finally {
    save();
    await context.close();
    if (cleanupStation && process.env.STATION_RESTORE_PREVIEW !== 'false') {
      await fetch(base + '/api/so101/scene-mode', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'draft', station: cleanupStation }) }).catch(() => {});
    }
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
