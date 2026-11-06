#!/usr/bin/env node
'use strict';
// Browse existing material only: no fixture is counted as physical acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
async function main() {
  const args = Object.fromEntries(process.argv.slice(2).reduce((rows,v,i,a) => i%2 ? rows : [...rows,[v.replace(/^--/,''),a[i+1]]], []));
  const base = args.base || 'http://127.0.0.1:5194';
  assert.equal(new URL(base).hostname, '127.0.0.1'); assert.ok(args.output);
  fs.mkdirSync(args.output,{recursive:true});
  const result={passed:false,checks:[],writes:[],errors:[],scope:'Existing four-group files, no ROS, physics, inference or rescoring'};
  const browser=await chromium.launch({executablePath:args.chromium||'/opt/google/chrome/chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  page.on('pageerror',e=>result.errors.push(String(e)));
  page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))result.writes.push({method:r.method(),url:r.url()});});
  const card=page.locator('#j100-vision-delivery'), panel=page.locator('#workbench-delivery-timing');
  const select=async(id,marker)=>{await page.locator(`[data-result-group="${id}"]`).click();await card.getByText(marker,{exact:false}).first().waitFor();};
  try {
    await page.goto(base+'/results');
    await card.getByText('J100 视觉停靠完成 · 抓取规划超时',{exact:true}).waitFor();
    assert.equal(await page.locator('[data-result-group]').count(),4);
    await page.waitForFunction(()=>document.querySelector('#j100-vision-delivery video')?.readyState>=1);
    result.checks.push('four groups present; default v5 actual video still decodes and failed verdict remains');
    await select('j100-ideal','48.78 s');
    assert.equal(await panel.count(),0);
    await card.getByRole('button',{name:'订单 A',exact:true}).click();await card.getByText('19.26 s',{exact:true}).waitFor();
    assert.equal(await card.locator('video').count(),0);
    result.checks.push('wide-scene summary keeps missing timeline and switches A despite unknown task UUIDs');
    await card.getByLabel('选择配送成果').selectOption('/workbench/j100-ideal-k-result.json');
    await card.getByText('119.79 s',{exact:true}).waitFor();
    await card.locator('.regression-viewport svg').waitFor();
    const seek=card.getByLabel('视觉配送源时间');await seek.fill('10');
    const download=card.getByRole('link',{name:'下载成果摘要'});
    assert.equal(await download.getAttribute('href'),'/workbench/j100-ideal-k-result.json');
    await card.getByRole('button',{name:'订单 A',exact:true}).click();
    await card.getByText('34.88 s',{exact:true}).waitFor();await panel.getByText('34.883 s',{exact:true}).first().waitFor();
    assert.equal(await panel.getByLabel('选择配送记录').count(),0);
    result.checks.push('old J100 actual replay, matching task/timing/download switch together; standalone timing source cannot drift');
    await select('mecanum-2d','31.73 s');
    assert.ok((await card.innerText()).includes('1 次世界重置'));assert.ok(!(await card.innerText()).includes('所选模型候选'));
    await card.getByRole('button',{name:'订单 A',exact:true}).click();await card.getByText('26.95 s',{exact:true}).waitFor();await panel.getByText('26.951 s',{exact:true}).first().waitFor();
    result.checks.push('2D mecanum source, both orders and explicit reset matched; no visual-model claim');
    await select('mecanum-3d','28.68 s');
    await card.getByRole('button',{name:'订单 A',exact:true}).click();await card.getByText('22.29 s',{exact:true}).waitFor();await panel.getByText('22.289 s',{exact:true}).first().waitFor();
    assert.equal(await card.locator('video').count(),0);
    result.checks.push('3D mecanum uses independent task IDs/timing, missing media explicit');
    await page.getByLabel('筛选成果车型').selectOption('j100');await page.getByLabel('筛选成果雷达').selectOption('2d');
    await page.getByText('没有符合当前筛选的组合。',{exact:false}).waitFor();assert.equal(await card.count(),0);
    await page.getByLabel('筛选成果车型').selectOption('all');await page.getByLabel('筛选成果雷达').selectOption('all');
    result.checks.push('filter empty combination does not keep an unrelated result visible');
    await page.setViewportSize({width:390,height:844});
    for(const [id,text] of [['j100-vision','抓取规划超时'],['j100-ideal','48.78 s'],['mecanum-2d','31.73 s'],['mecanum-3d','28.68 s']]) {
      await select(id,text);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
    await page.locator('#delivery-results-gallery').evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-130));
    await page.screenshot({path:path.join(args.output,'gallery-mobile.png')});
    await page.setViewportSize({width:1440,height:1100});await page.locator('#delivery-results-gallery').evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-130));
    await page.screenshot({path:path.join(args.output,'gallery-desktop.png')});
    result.checks.push('all four groups on 390px without horizontal overflow; desktop and mobile screenshots');
    await page.route('**/workbench/mecanum-lidar3d-delivery-timing.json',r=>r.fulfill({status:404,json:{}}));
    await select('mecanum-2d','31.73 s');await select('mecanum-3d','28.68 s');
    await page.getByText('一项回放/阶段报告读取失败（HTTP 404）',{exact:false}).waitFor();
    assert.ok((await card.innerText()).includes('28.68 s'));
    result.checks.push('missing one timing asset retains corresponding order summary and warns per item');
    assert.deepEqual(result.writes,[]);assert.deepEqual(result.errors,[]);result.passed=true;
  } finally {await browser.close();fs.writeFileSync(path.join(args.output,'ui-result.json'),JSON.stringify(result,null,2)+'\n');}
  console.log(JSON.stringify(result));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
