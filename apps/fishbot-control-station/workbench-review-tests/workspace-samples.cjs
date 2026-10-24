// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// Exercise the existing editor; loading, saving and copying must not start motion.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const {chromium, expect} = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5186';
const output = process.env.STATION_QA_OUTPUT ?? path.join(__dirname, 'output/workspace-samples');
fs.mkdirSync(output, {recursive:true});
const result = {passed:false, checks:[], errors:[], motionRequests:[]};
async function exported(page, panel, name) {
  const download = page.waitForEvent('download');
  await panel.getByRole('button', {name:'导出 JSON', exact:true}).click();
  const file = path.join(output, name+'.json');
  await (await download).saveAs(file);
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}
function position(station, id) {
  if (id === 'world') return [0,0,0];
  const node = station.nodes.find(node => node.id === id);
  return position(station, node.parent).map((value,i) => value+node.position[i]);
}
async function sample(page, panel, plus, name) {
  await panel.getByRole('button', {name:plus ? '载入 X+20mm 布局' : '载入 X−20mm 布局', exact:true}).click();
  await expect(panel.getByLabel('工作站名称', {exact:true})).toHaveValue(
    plus ? 'SO101 X+20mm 布局开发样例' : 'SO101 X−20mm 布局开发样例');
  await expect(panel.getByRole('region', {name:'当前仿真任务', exact:true})).toHaveCount(0);
  const value = await exported(page, panel, name);
  assert.equal(value.station.execution.mode, 'workspace-development-v1');
  assert.deepEqual(value.station.execution.pick_xy_m, plus ? [.26,-.13] : [.235,-.13]);
  assert.equal(value.station.execution.pickup_hover_z_m, plus ? .054 : .06);
  assert.deepEqual(value.station.execution.target_region_xy_m, [[.21,.27],[-.16,-.10]]);
  const cube = position(value.station,'cube');
  assert.ok(Math.abs(cube[0]-(plus ? .26 : .22)) < 1e-12);
  assert.equal(cube[1], -.13);
  assert.equal(value.station.program.length, 8);
  return value;
}
(async () => {
  const browser = await chromium.launch({executablePath:'/usr/bin/google-chrome', headless:true,
    args:['--no-sandbox']});
  async function context(viewport) {
    const ctx = await browser.newContext({viewport, acceptDownloads:true});
    await ctx.route('**/api/so101/tasks**', async route => {
      if (!['GET','HEAD'].includes(route.request().method())) {
        result.motionRequests.push({method:route.request().method(),url:route.request().url()});
        await route.abort('blockedbyclient');
      } else await route.continue();
    });
    const page = await ctx.newPage();
    page.on('pageerror', error => result.errors.push(error.message));
    return {ctx,page};
  }
  try {
    const {ctx,page} = await context({width:1600,height:1100});
    await page.goto(base+'/so101-station');
    const panel = page.getByTestId('panel-mouseenter-container RobotStation!so101station');
    await expect(panel.getByRole('button',{name:'载入 X+20mm 布局',exact:true})).toBeEnabled({timeout:90000});
    const plus = await sample(page,panel,true,'desktop-plus');
    await panel.getByRole('button',{name:'保存草稿',exact:true}).click();
    await panel.getByText('草稿与当前布局已保存，刷新页面可继续编辑。也可导出 JSON 备份。',{exact:true}).waitFor();
    await page.reload();
    await expect(panel.getByLabel('工作站名称',{exact:true})).toHaveValue(plus.station.name,{timeout:90000});
    assert.deepEqual((await exported(page,panel,'desktop-reloaded')).station,plus.station);
    result.checks.push('plus-layout-export','native-save-and-reload-execution');
    await panel.getByRole('button',{name:'复制为新任务',exact:true}).click();
    const copy = await exported(page,panel,'desktop-copy');
    assert.deepEqual(copy.station.execution,plus.station.execution);
    assert.equal(copy.station.name,plus.station.name+' 副本');
    await sample(page,panel,false,'desktop-minus');
    result.checks.push('copy-preserves-execution','minus-layout-export','sample-load-clears-old-result');
    await panel.getByRole('region',{name:'SO101 开发工位样例'}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
    await ctx.close();
    const mobile = await context({width:390,height:844});
    await mobile.page.goto(base+'/so101-station-mobile');
    const narrow = mobile.page.getByTestId('panel-mouseenter-container RobotStation!so101station');
    await expect(narrow.getByRole('button',{name:'载入 X−20mm 布局',exact:true})).toBeEnabled({timeout:90000});
    await sample(mobile.page,narrow,false,'mobile-minus');
    await narrow.getByRole('region',{name:'SO101 开发工位样例'}).scrollIntoViewIfNeeded();
    await mobile.page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    result.checks.push('390px-sample-controls','390px-execution-export');
    assert.deepEqual(result.motionRequests,[]);
    assert.deepEqual(result.errors,[]);
    result.checks.push('zero-motion-requests','zero-page-errors');
    result.passed = true;
  } catch (error) {
    result.errors.push(error.stack ?? String(error));
    process.exitCode = 1;
  } finally {
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2)+'\n');
    await browser.close();
    console.log(JSON.stringify(result));
  }
})();
