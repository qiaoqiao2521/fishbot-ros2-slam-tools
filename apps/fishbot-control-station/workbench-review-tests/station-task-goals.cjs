// Frozen-code acceptance: original task -> copy -> edit/save/reload -> new goal.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');const {createRequire}=require('node:module');
const {chromium,expect}=createRequire(path.join(__dirname,'../workbench/package.json'))('@playwright/test');
const base=process.env.STATION_TEST_URL??'http://127.0.0.1:5187';
const out=path.join(__dirname,'output/station-task-goals');fs.mkdirSync(out,{recursive:true});
const result={passed:false,checks:[],tasks:[],posts:[],pageErrors:[]};
const save=()=>fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100},acceptDownloads:true});
  page.on('pageerror',e=>result.pageErrors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/so101/tasks'))result.posts.push({url:r.url(),body:r.postDataJSON()});});
  await page.goto(base+'/so101-station');
  const panel=page.getByTestId('panel-mouseenter-container RobotStation!so101station');
  const run=panel.getByRole('button',{name:'规划并运行仿真',exact:true});
  const copy=panel.getByRole('button',{name:'复制为新任务',exact:true});
  await expect(run).toBeEnabled({timeout:90000});
  async function download(){const pending=page.waitForEvent('download');await panel.getByRole('button',{name:'导出 JSON',exact:true}).click();return JSON.parse(fs.readFileSync(await(await pending).path(),'utf8'));}
  async function execute(){
   const pending=page.waitForResponse(r=>r.url()===base+'/api/so101/tasks'&&r.request().method()==='POST');
   await run.click();const submitted=await(await pending).json();const index=result.tasks.length;result.tasks.push(submitted);save();
   await expect(copy).toBeDisabled();await expect(panel.getByRole('button',{name:'取消任务',exact:true})).toBeEnabled();
   await expect.poll(async()=>{const s=await(await page.request.get(base+'/api/so101/tasks/'+submitted.id)).json();result.tasks[index]=s;save();return s.status;},{timeout:180000,intervals:[1000,1500]}).toMatch(/^(succeeded|failed|cancelled)$/);
   const task=result.tasks[index];assert.equal(task.status,'succeeded',task.report?.failure_reason??task.message);assert.equal(task.report.passed,true);assert.equal(task.report.controller_done,true);assert.equal(task.report.safety_stop,false);assert.equal(task.report.place_success,true);
   await expect(copy).toBeEnabled({timeout:10000});return task;
  }
  const original=await execute();
  assert.deepEqual(original.report.place_goal_xy_m,[.24,.14]);
  result.checks.push('original-default-task-full-cycle');save();
  const originalStation=structuredClone(original.station);
  await copy.click();await expect(panel.getByLabel('对象名称',{exact:true})).toHaveValue('放料坐标系');
  await expect(panel).not.toContainText(original.id);
  await panel.getByLabel('X（m）',{exact:true}).fill('0.20');
  await panel.getByLabel('Y（m）',{exact:true}).fill('0.20');
  await expect(panel.getByLabel('Z（m）',{exact:true})).toBeDisabled();
  await panel.getByRole('button',{name:'保存草稿',exact:true}).click();
  const draft=await download();
  assert.deepEqual(draft.station.nodes.find(n=>n.id==='place').position,[.2,.2,0]);
  assert.deepEqual(draft.station.program,originalStation.program);
  await page.reload();await expect(run).toBeEnabled({timeout:60000});
  assert.deepEqual(await download(),draft);
  await expect(panel).not.toContainText(original.id);
  assert.equal(result.posts.length,1,'Copy, editing, saving and reloading must not start motion');
  const unchanged=await(await page.request.get(base+'/api/so101/tasks/'+original.id)).json();
  assert.deepEqual(unchanged.station,originalStation,'Original task snapshot remains unchanged');
  await page.screenshot({path:path.join(out,'saved-new-goal.png')});
  result.checks.push('deep-copy-original-submission','edit-place-xy-and-save','reload-restores-complete-draft-without-old-result','copy-edit-save-reload-zero-motion','original-task-snapshot-unchanged');save();
  const moved=await execute();assert.notEqual(moved.id,original.id);
  assert.deepEqual(moved.report.place_goal_xy_m,[.2,.2]);
  assert.deepEqual(moved.layout.place_xy_m,[.2,.2]);
  assert(Math.hypot(moved.object_xyz_m[0]-.2,moved.object_xyz_m[1]-.2)<.01,'Actual free payload must settle near the new goal');
  assert(moved.object_xyz_m[1]>.19,'New payload lies outside the old tray acceptance region');
  assert.equal(moved.scene_final,true);assert.equal(result.posts.length,2);
  await page.screenshot({path:path.join(out,'new-goal-success.png')});
  await copy.click();const next=await download();assert.deepEqual(next.station.nodes.find(n=>n.id==='place').position,[.2,.2,0]);
  await expect(panel).not.toContainText(moved.id);assert.equal(result.posts.length,2);
  assert.deepEqual(result.pageErrors,[]);
  result.checks.push('new-id-same-program-different-goal','actual-payload-in-new-tray-outside-old-region','new-goal-grasp-place-detach-return','copy-completed-task-reusable-again','active-copy-disabled-cancel-preserved','no-page-errors');result.passed=true;save();
  console.log(JSON.stringify({passed:true,checks:result.checks,tasks:result.tasks.map(t=>({id:t.id,status:t.status,goal:t.report.place_goal_xy_m,simulation_s:t.simulation_s,wall_s:t.report.wall_s}))}));
 }finally{save();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
