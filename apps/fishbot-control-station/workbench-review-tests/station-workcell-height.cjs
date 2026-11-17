// F2 draft acceptance. This script edits an isolated preview and never submits motion.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL;
const input = process.env.STATION_TEST_INPUT;
assert(base && input, 'Set STATION_TEST_URL to an isolated service and STATION_TEST_INPUT to the F2 JSON');
const document = JSON.parse(fs.readFileSync(input, 'utf8'));
const station = document.station ?? document;
const place = station.nodes.find(node => node.id === 'place');
assert(place && place.parent === 'world', 'The F2 fixture must expose its tray base in world coordinates');
const height = Number(process.env.STATION_TEST_HEIGHT ?? '0.015');
assert(Number.isFinite(height) && height !== place.position[2], 'Choose a different finite tray height');
const output = process.env.STATION_QA_OUTPUT ?? path.join(__dirname, 'output/station-workcell-height');
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, checks: [], pageErrors: [], motionRequests: [], preview: {}, input };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
const blueWalls = scene => scene?.entities?.flatMap(entity => entity.cubes ?? [])
  .filter(cube => cube.color.r < 0.3 && cube.color.g > 0.3 && cube.color.g < 0.5 && cube.color.b > 0.5) ?? [];
const exported = async (page, panel, name) => {
  const pending = page.waitForEvent('download');
  await panel.getByRole('button', { name: '导出 JSON', exact: true }).click();
  const file = path.join(output, name);
  await (await pending).saveAs(file);
  return JSON.parse(fs.readFileSync(file, 'utf8'));
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, acceptDownloads: true });
  await context.route('**/api/so101/tasks**', async route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) {
      result.motionRequests.push({ method: route.request().method(), url: route.request().url() });
      await route.abort('blockedbyclient');
    } else {
      await route.continue();
    }
  });
  try {
    const page = await context.newPage();
    page.on('pageerror', error => result.pageErrors.push(error.message));
    const scene = async () => await (await page.request.get(base + '/api/so101/scene-state')).json();
    const tasksBefore = (await (await page.request.get(base + '/api/so101/tasks')).json()).tasks;
    const originals = await Promise.all(tasksBefore.map(async task => ({
      id: task.id,
      station: (await (await page.request.get(base + '/api/so101/tasks/' + task.id)).json()).station,
    })));
    result.originalTaskCount = originals.length;
    await page.goto(base + '/so101-station');
    const panel = page.getByTestId('panel-mouseenter-container RobotStation!so101station');
    const copy = panel.getByRole('button', { name: '复制为新任务', exact: true });
    await expect(copy).toBeEnabled({ timeout: 90000 });
    await copy.click();
    await panel.locator('input[type=file]').setInputFiles(input);
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(station.name);
    await panel.locator('[aria-label="工作站对象树"]').getByRole('button').filter({ hasText: place.name }).click();
    await expect(panel.getByLabel('对象名称', { exact: true })).toHaveValue(place.name);
    const z = panel.getByLabel('Z（m）', { exact: true });
    await expect(z).toBeEnabled();
    await expect(z).toHaveValue(String(place.position[2]));
    const previewReady = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/so101/scene-mode' &&
      response.request().method() === 'POST' &&
      response.request().postDataJSON()?.station?.name === station.name &&
      response.status() === 200);
    await panel.getByRole('button', { name: '编辑预览', exact: true }).click();
    await previewReady;
    await expect.poll(async () => (await scene()).mode, { timeout: 30000 }).toBe('draft');
    await expect.poll(async () => blueWalls((await scene()).scene).length, { timeout: 30000 }).toBe(5);
    const imported = await exported(page, panel, 'imported-f2.json');
    assert.deepEqual(imported.station.nodes, station.nodes);
    const before = blueWalls((await scene()).scene);
    await z.fill(String(height));
    const delta = height - place.position[2];
    await expect.poll(async () => {
      const after = blueWalls((await scene()).scene);
      return after.length === 5 && after.every((wall, i) =>
        Math.abs(wall.pose.position.z - before[i].pose.position.z - delta) < 1e-9 &&
        Math.abs(wall.pose.position.x - before[i].pose.position.x) < 1e-9 &&
        Math.abs(wall.pose.position.y - before[i].pose.position.y) < 1e-9 &&
        JSON.stringify(wall.size) === JSON.stringify(before[i].size));
    }, { timeout: 30000 }).toBe(true);
    result.preview = { originalHeight: place.position[2], editedHeight: height, before, after: blueWalls((await scene()).scene) };
    result.checks.push('f2-import-preserves-scene', 'tray-height-editable', 'all-five-tray-pieces-follow-height-with-original-size');
    await panel.getByRole('button', { name: '保存草稿', exact: true }).click();
    await panel.getByText('草稿与当前布局已保存，刷新页面可继续编辑。也可导出 JSON 备份。', { exact: true }).waitFor();
    const saved = await exported(page, panel, 'saved-height.json');
    assert.deepEqual(saved.station.nodes.find(node => node.id === 'place').position, [place.position[0], place.position[1], height]);
    for (const id of ['release', 'clear']) {
      assert.deepEqual(saved.station.nodes.find(node => node.id === id), station.nodes.find(node => node.id === id));
    }
    assert.deepEqual(saved.station.program.map(({ id, ...step }) => step), station.program.map(({ id, ...step }) => step));
    await page.reload();
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(station.name, { timeout: 60000 });
    assert.deepEqual(await exported(page, panel, 'reloaded-height.json'), saved);
    await expect(panel.getByRole('region', { name: '当前仿真任务' })).toHaveCount(0);
    await panel.locator('[aria-label="工作站对象树"]').getByRole('button').filter({ hasText: place.name }).click();
    await expect(panel.getByLabel('Z（m）', { exact: true })).toHaveValue(String(height));
    await page.screenshot({ path: path.join(output, 'height-editor.png'), fullPage: true });
    for (const original of originals) {
      const latest = await (await page.request.get(base + '/api/so101/tasks/' + original.id)).json();
      assert.deepEqual(latest.station, original.station);
    }
    assert.deepEqual(result.motionRequests, []);
    assert.deepEqual(result.pageErrors, []);
    result.checks.push('relative-release-clear-targets-preserved', 'eight-step-program-preserved', 'save-export-reload-exact', 'old-result-not-restored', originals.length ? 'existing-task-inputs-unchanged' : 'isolated-task-store-initially-empty', 'zero-motion-requests', 'zero-page-errors');
    result.passed = true;
    console.log(JSON.stringify({ passed: true, checks: result.checks, output }));
  } finally {
    save();
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
