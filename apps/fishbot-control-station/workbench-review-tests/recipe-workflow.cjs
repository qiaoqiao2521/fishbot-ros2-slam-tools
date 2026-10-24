// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// Editor-only acceptance. Real task writes are blocked; race task responses are isolated mocks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const {chromium, expect} = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5186';
const output = process.env.STATION_QA_OUTPUT ?? path.join(__dirname, 'output/recipe-workflow');
const recipePath = process.env.STATION_RECIPE_FIXTURE ?? '/home/muqiao/dev/ros2/_delivery/so101-colab-20261001/experiments/colab-twin/scenarios/recipes/station_recipe_v1-x-plus20.json';
const canonical = JSON.parse(fs.readFileSync(recipePath, 'utf8'));
fs.mkdirSync(output, {recursive:true});
const result = {passed:false, checks:[], pageErrors:[], errors:[], realTaskWrites:[], mockTaskPosts:[], mockTaskGets:[], mockHistoricalGets:[], fixture:recipePath, race:{verified:false}};
const clone = value => JSON.parse(JSON.stringify(value));
const persist = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result,null,2)+'\n');
const panelFor = page => page.getByTestId('panel-mouseenter-container RobotStation!so101station');
async function exported(page, panel, name, recipe=false) {
  const pending=page.waitForEvent('download');
  await panel.getByRole('button',{name:recipe?'导出工位配方':'导出 JSON',exact:true}).click();
  const file=path.join(output,name+'.json');
  await (await pending).saveAs(file);
  return JSON.parse(fs.readFileSync(file,'utf8'));
}
async function imported(panel, value, name) {
  await panel.locator('input[type=file]').setInputFiles({name,mimeType:'application/json',buffer:Buffer.from(JSON.stringify(value))});
}
function envelope(document) {
  assert.equal(document.format,'station-recipe');
  assert.equal(document.version,1);
  assert.equal(document.units,'m');
  assert.equal(document.frameConvention,'translation-only');
  assert.equal(document.executionScope,'independent_episode');
  assert.deepEqual(document.compatibility,{platform:'so101',executor:'so101-mujoco-visual-grasp',stationVersion:1});
  assert.deepEqual(document.skills,['pick','transfer','place']);
  assert.equal(document.station.program.length,8);
  assert.equal(document.station.execution.mode,'workspace-development-v1');
}
(async()=>{
  const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  const contexts=[];
  async function context(viewport, {historical=false,race=false}={}) {
    const ctx=await browser.newContext({viewport,acceptDownloads:true});contexts.push(ctx);
    const historyId='qa-historical-completed-task';
    if(historical) {
      await ctx.route('**/layouts/so101-station.json',async route=>{
        const response=await route.fetch();const layout=await response.json();
        layout.configById['RobotStation!so101station'].executionTaskId=historyId;
        await route.fulfill({response,json:layout});
      });
    }
    const mock={id:undefined,station:undefined};
    await ctx.route('**/api/so101/tasks**',async route=>{
      const request=route.request(),method=request.method(),url=new URL(request.url());
      if(race) {
        if(method==='POST' && url.pathname==='/api/so101/tasks') {
          const body=request.postDataJSON();
          assert.match(body.taskId,/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i);
          mock.id=body.taskId;mock.station=body.station;
          result.mockTaskPosts.push({method,url:request.url(),taskId:body.taskId,scope:'isolated race mock; never sent to backend'});
          await route.fulfill({json:{id:mock.id,status:'running',phase:'qa_mock_only',station:mock.station}});
        } else if(['GET','HEAD'].includes(method)) {
          result.mockTaskGets.push({method,url:request.url()});
          const id=url.pathname.slice('/api/so101/tasks/'.length);
          await route.fulfill({json:url.pathname==='/api/so101/tasks'?{tasks:[]}:{id,status:'running',phase:'qa_mock_only',station:mock.station}});
        } else {
          result.errors.push('Unexpected race task endpoint: '+method+' '+url.pathname);
          await route.abort('blockedbyclient');
        }
      } else if(!['GET','HEAD'].includes(method)) {
        result.realTaskWrites.push({method,url:request.url(),blocked:true});
        await route.abort('blockedbyclient');
      } else if(historical && url.pathname==='/api/so101/tasks/'+historyId) {
        result.mockHistoricalGets.push({method,url:request.url(),scope:'completed history fixture only'});
        await route.fulfill({json:{id:historyId,status:'succeeded',station:canonical.station,message:'QA historical fixture; no new physical verdict'}});
      } else await route.continue();
    });
    if(race) await ctx.addInitScript(()=>{
      const original=File.prototype.text;
      window.__recipeReadPending=false;
      File.prototype.text=function(...args) {
        if(this.name!=='qa-race-recipe.json')return original.apply(this,args);
        window.__recipeReadPending=true;
        return new Promise(resolve=>{window.__releaseRecipeRead=resolve;}).then(()=>original.apply(this,args));
      };
    });
    const page=await ctx.newPage();page.on('pageerror',error=>result.pageErrors.push(error.message));
    return {ctx,page,mock,historyId};
  }
  try {
    const draft=await context({width:1600,height:1100});
    await draft.page.goto(base+'/so101-station');const draftPanel=panelFor(draft.page);
    await expect(draftPanel.getByRole('button',{name:'载入 X+20mm 布局',exact:true})).toBeEnabled({timeout:90000});
    await draftPanel.getByRole('button',{name:'载入 X+20mm 布局',exact:true}).click();
    const layout=await exported(draft.page,draftPanel,'layout-before-recipe');
    const wrapped=await exported(draft.page,draftPanel,'new-recipe',true);envelope(wrapped);
    assert.deepEqual(wrapped.station.execution,layout.station.execution);
    assert.deepEqual(wrapped.station.program,layout.station.program);
    result.checks.push('load-X-layout-and-export-recipe-headers','recipe-preserves-execution-and-eight-steps');
    await draft.ctx.close();

    const edit=await context({width:1600,height:1100},{historical:true});
    await edit.page.goto(base+'/so101-station');const panel=panelFor(edit.page);
    await expect(panel.getByText('原任务 ID：'+edit.historyId,{exact:true})).toBeVisible({timeout:90000});
    const plainStation={format:'robot-station',version:1,station:clone(canonical.station)};
    plainStation.station.name='普通 Station 导入：独立草稿';
    await imported(panel,plainStation,'qa-plain-station.json');
    await expect(panel.getByLabel('工作站名称',{exact:true})).toHaveValue(plainStation.station.name);
    await expect(panel.getByRole('region',{name:'当前仿真任务',exact:true})).toHaveCount(0);
    await expect(panel.getByText(/^原任务 ID：/)).toHaveCount(0);
    result.checks.push('plain-station-import-clears-historical-task-selection');
    const fixture=clone(canonical);
    fixture.station.name='配方浏览器核验：原件';
    fixture.vendorNotes={source:'editor-only QA',nested:{labels:['retain','clone'],editable:true}};
    await imported(panel,fixture,'qa-valid-recipe.json');
    await expect(panel.getByLabel('工作站名称',{exact:true})).toHaveValue(fixture.station.name);
    await expect(panel).toContainText('历史验收仅作来源引用');
    await expect(panel).toContainText('vendorNotes');
    await expect(panel.getByRole('region',{name:'当前仿真任务',exact:true})).toHaveCount(0);
    await expect(panel.getByText(/^原任务 ID：/)).toHaveCount(0);
    const loaded=await exported(edit.page,panel,'loaded-recipe');envelope(loaded);
    assert.deepEqual(loaded.vendorNotes,fixture.vendorNotes);
    assert.deepEqual(loaded.acceptanceReferences,fixture.acceptanceReferences);
    assert.deepEqual(loaded.station.execution,fixture.station.execution);
    assert.deepEqual(loaded.station.program,fixture.station.program);
    result.checks.push('recipe-import-retains-unknown-nested-metadata-and-historical-references','recipe-import-clears-historical-task-selection');

    await panel.getByLabel('工作站名称',{exact:true}).fill('配方浏览器核验：已编辑');
    await panel.getByRole('button',{name:/放料坐标系.*坐标系/}).click();
    await expect(panel.getByLabel('对象名称',{exact:true})).toHaveValue('放料坐标系');
    await panel.getByLabel('X（m）',{exact:true}).fill('0.235');
    await panel.getByLabel('Y（m）',{exact:true}).fill('0.145');
    const edited=await exported(edit.page,panel,'edited-recipe');
    assert.deepEqual(edited.station.nodes.find(node=>node.id==='place').position,[.235,.145,0]);
    assert.deepEqual(edited.vendorNotes,fixture.vendorNotes);
    assert.deepEqual(edited.acceptanceReferences,fixture.acceptanceReferences);
    await panel.getByRole('button',{name:'保存草稿',exact:true}).click();
    await panel.getByText('草稿与当前布局已保存，刷新页面可继续编辑。也可导出 JSON 备份。',{exact:true}).waitFor();
    await edit.page.reload();
    await expect(panel.getByLabel('工作站名称',{exact:true})).toHaveValue(edited.station.name,{timeout:90000});
    const reloaded=await exported(edit.page,panel,'reloaded-recipe');assert.deepEqual(reloaded,edited);
    await expect(panel.getByRole('region',{name:'当前仿真任务',exact:true})).toHaveCount(0);
    result.checks.push('edit-name-and-place-xy','save-reload-preserves-recipe-format-and-metadata');

    await panel.getByRole('button',{name:'复制为新任务',exact:true}).click();
    const copy=await exported(edit.page,panel,'copied-recipe');envelope(copy);
    assert.equal(copy.station.name,edited.station.name+' 副本');
    assert.deepEqual(copy.vendorNotes,edited.vendorNotes);
    assert.deepEqual(copy.acceptanceReferences,edited.acceptanceReferences);
    assert.deepEqual(copy.station.execution,edited.station.execution);
    await panel.getByLabel('工作站名称',{exact:true}).fill('独立副本编辑');
    await panel.getByRole('button',{name:'撤销',exact:true}).click();
    await expect(panel.getByLabel('工作站名称',{exact:true})).toHaveValue(copy.station.name);
    await panel.getByRole('button',{name:'撤销',exact:true}).click();
    await expect(panel.getByLabel('工作站名称',{exact:true})).toHaveValue(edited.station.name);
    assert.deepEqual(await exported(edit.page,panel,'undo-copy-original'),edited);
    result.checks.push('copy-retains-nested-recipe-metadata','copy-edit-and-undo-retain-original-document');
    result.copyScope='Browser verifies independent edit/history behavior and nested metadata retention; JS reference identity is covered by station unit tests.';

    for(const [name,mutate,field] of [
      ['units-mm',d=>{d.units='mm';},'units'],
      ['rotation',d=>{d.station.nodes[2].rotation=[0,0,0];},'station.nodes[2].rotation'],
      ['motion',d=>{d.station.nodes[2].motion={type:'linear_ping_pong',axis:[1,0,0],distance_m:.1,speed_m_s:.1};},'station.nodes[2].motion'],
      ['platform',d=>{d.compatibility.platform='px4';},'compatibility.platform'],
      ['negative-seconds',d=>{d.station.program[0].seconds=-1;},'station.program[0].seconds'],
    ]) {
      const invalid=clone(edited);invalid.station.name='MUST NOT LOAD '+name;mutate(invalid);
      await imported(panel,invalid,'qa-invalid-'+name+'.json');
      await expect(panel).toContainText('配方 '+field,{timeout:10000});
      await expect(panel).toContainText('当前草稿未改变');
      assert.deepEqual(await exported(edit.page,panel,'rejected-'+name),edited);
      result.checks.push('reject-'+name+'-without-changing-draft');
    }
    await panel.getByRole('region',{name:'SO101 开发工位样例'}).scrollIntoViewIfNeeded();
    await edit.page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
    await edit.ctx.close();

    const mobile=await context({width:390,height:844});
    await mobile.page.goto(base+'/so101-station-mobile');const narrow=panelFor(mobile.page);
    await expect(narrow.getByRole('button',{name:'导出工位配方',exact:true})).toBeVisible({timeout:90000});
    await narrow.getByRole('button',{name:'载入 X+20mm 布局',exact:true}).click();
    envelope(await exported(mobile.page,narrow,'mobile-recipe',true));
    await imported(narrow,fixture,'qa-mobile-recipe.json');
    await expect(narrow.getByLabel('工作站名称',{exact:true})).toHaveValue(fixture.station.name);
    for(const name of ['保存草稿','导出工位配方','导入 JSON']) {
      const button=narrow.getByRole('button',{name,exact:true});await button.scrollIntoViewIfNeeded();
      await expect(button).toBeEnabled();const bounds=await button.boundingBox();
      assert(bounds && bounds.x>=0 && bounds.x+bounds.width<=391);
    }
    assert(await mobile.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await narrow.getByRole('region',{name:'SO101 开发工位样例'}).scrollIntoViewIfNeeded();
    await mobile.page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    result.checks.push('390px-recipe-import-export-controls');await mobile.ctx.close();

    const race=await context({width:1600,height:1100},{race:true});
    await race.page.goto(base+'/so101-station');const racePanel=panelFor(race.page);
    const run=racePanel.getByRole('button',{name:'规划并运行仿真',exact:true});
    await expect(run).toBeEnabled({timeout:90000});
    const before=await exported(race.page,racePanel,'race-before');
    const racing=clone(fixture);racing.station.name='RACE MUST NOT IMPORT';
    await imported(racePanel,racing,'qa-race-recipe.json');
    await expect.poll(()=>race.page.evaluate(()=>window.__recipeReadPending)).toBe(true);
    await run.click();await expect.poll(()=>result.mockTaskPosts.length).toBe(1);
    const newId=result.mockTaskPosts[0].taskId;
    await expect(racePanel.getByRole('button',{name:'取消任务',exact:true})).toBeEnabled();
    await expect(racePanel.getByText('原任务 ID：'+newId,{exact:true})).toBeVisible();
    await race.page.evaluate(()=>window.__releaseRecipeRead());
    await expect(racePanel).toContainText('读取期间任务状态已变化');
    await expect(racePanel.getByRole('button',{name:'取消任务',exact:true})).toBeEnabled();
    await expect(racePanel.getByText('原任务 ID：'+newId,{exact:true})).toBeVisible();
    assert.deepEqual((await exported(race.page,racePanel,'race-after')).station,before.station);
    result.race={verified:true,taskId:newId,mockPostCount:result.mockTaskPosts.length,importRejected:true,cancelRetained:true,scope:'Isolated response mock. No backend task, no simulation or physical result.'};
    await racePanel.getByRole('region',{name:'当前仿真任务'}).scrollIntoViewIfNeeded();
    await race.page.screenshot({path:path.join(output,'race.png'),fullPage:true});
    result.checks.push('async-file-read-race-retains-new-task-id-and-cancel','race-import-refused-with-original-draft');
    await race.ctx.close();
    assert.deepEqual(result.realTaskWrites,[]);assert.deepEqual(result.pageErrors,[]);assert.deepEqual(result.errors,[]);
    result.checks.push('zero-real-task-writes','zero-page-errors');result.passed=true;
  } catch(error) {
    result.errors.push(error.stack??String(error));process.exitCode=1;
  } finally {
    persist();for(const ctx of contexts)await ctx.close().catch(()=>{});await browser.close();
    console.log(JSON.stringify({passed:result.passed,checks:result.checks,errors:result.errors,realTaskWrites:result.realTaskWrites.length,mockPosts:result.mockTaskPosts.length,race:result.race,output}));
  }
})();
