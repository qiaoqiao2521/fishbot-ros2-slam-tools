// Import and persist the requested cruise duration; never dispatch a plan or flight.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
const source = process.env.DRONE_STATION_FILE ?? '/home/muqiao/dev/ros2/projects/drone/examples/ego-high-speed.json';
const output = process.env.DRONE_QA_OUTPUT ?? path.join(__dirname, 'output/drone-duration-draft');
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, writes: [], errors: [] };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, acceptDownloads: true });
  page.on('pageerror', error => { result.errors.push(error.message); save(); });
  await page.route(/\/api\/(?:drone|so101)\/(?:tasks|plans)(?:[/?]|$)/, async route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) {
      result.writes.push(route.request().url()); save();
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  const panel = page.getByTestId('panel-mouseenter-container RobotStation!dronestation');
  const exported = async name => {
    const pending = page.waitForEvent('download');
    await panel.getByRole('button', { name: '导出 JSON', exact: true }).click();
    const file = path.join(output, name);
    await (await pending).saveAs(file);
    return JSON.parse(fs.readFileSync(file, 'utf8')).station;
  };
  try {
    const document = JSON.parse(fs.readFileSync(source, 'utf8'));
    const station = document.station ?? document;
    const requested = station.flight.acceptance.min_cruise_duration_s;
    assert.equal(requested, 2, 'This regression must keep the original two-second acceptance');
    await page.goto(`${base}/drone-station`);
    await expect(panel.getByRole('button', { name: '复制为新任务', exact: true })).toBeEnabled({ timeout: 90000 });
    await panel.locator('input[type=file]').setInputFiles(source);
    const field = panel.getByLabel('最低巡航持续时长（s）', { exact: true });
    await expect(field).toHaveValue('2');
    result.imported = await exported('imported.json');
    assert.deepEqual(result.imported.flight, station.flight);
    assert.deepEqual(result.imported.nodes, station.nodes);
    await panel.getByRole('button', { name: '复制为新任务', exact: true }).click();
    await expect(field).toHaveValue('2');
    result.copied = await exported('copied.json');
    assert.deepEqual(result.copied.flight, station.flight);
    await panel.getByRole('button', { name: '保存草稿', exact: true }).click();
    await panel.getByText('草稿与当前布局已保存，刷新页面可继续编辑。也可导出 JSON 备份。', { exact: true }).waitFor();
    await page.reload();
    await expect(field).toHaveValue('2', { timeout: 60000 });
    result.reloaded = await exported('reloaded.json');
    assert.deepEqual(result.reloaded, result.copied);
    await field.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'duration-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    const mobileLayout = page.waitForResponse(response => new URL(response.url()).pathname === '/layouts/drone-station-mobile.json');
    await page.goto(`${base}/drone-station-mobile`);
    const layout = await (await mobileLayout).json();
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(layout.configById['RobotStation!dronestation'].station.name, { timeout: 90000 });
    await expect(panel.getByRole('button', { name: '复制为新任务', exact: true })).toBeEnabled({ timeout: 90000 });
    await panel.locator('input[type=file]').setInputFiles(source);
    await expect(panel.getByLabel('工作站名称', { exact: true })).toHaveValue(station.name);
    await expect(field).toHaveValue('2');
    await field.scrollIntoViewIfNeeded();
    const bounds = await field.boundingBox();
    assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 391);
    assert(await panel.evaluate(element => element.scrollWidth <= element.clientWidth));
    await page.screenshot({ path: path.join(output, 'duration-mobile.png'), fullPage: true });
    assert.deepEqual(result.writes, []);
    assert.deepEqual(result.errors, []);
    result.passed = true; save();
    console.log(JSON.stringify({ passed: true, duration_s: requested, output }));
  } catch (error) {
    result.failure = error.stack ?? error.message;
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    save(); throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
