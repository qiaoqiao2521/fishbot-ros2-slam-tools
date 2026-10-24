// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// HTTP-fixture UI acceptance only. Never a new physical task or grasp verdict.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const {chromium, expect} = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5186';
const output = process.env.STATION_QA_OUTPUT ?? path.join(__dirname, 'output/grasp-evidence');
const evidencePath = process.env.STATION_GRASP_EVIDENCE_FIXTURE;
const stationPath = process.env.STATION_RECIPE_FIXTURE ?? path.join(__dirname,'output/recipe-workflow/new-recipe-first-run.json');
const stationDocument = JSON.parse(fs.readFileSync(stationPath,'utf8'));
const station = stationDocument.station ?? stationDocument;
const clone = value => JSON.parse(JSON.stringify(value));
const fixtureId = 'qa-grasp-evidence-task';
let unconfirmed = {
  schema:'so101.physical-skill-evidence.v1', scope:'observation_only',
  observations:{count:1,last_elapsed_s:27.68},
  grasp:{postcondition_met:false,first_met_elapsed_s:null,evidence:null},
  attempt:{passed:null,error_type:null,failure_reason:null,safety_stop:null,
    planner_cleanup_error:null,planner_cleanup_errors:null}, events:[],
};
let confirmed;
if(evidencePath) {
  const raw=JSON.parse(fs.readFileSync(evidencePath,'utf8'));
  confirmed=raw.evidence ?? raw.skill_evidence ?? raw.report?.skill_evidence ?? raw;
} else {
  // Explicit synthetic UI input when no real replay artifact is supplied.
  confirmed=clone(unconfirmed);
  confirmed.grasp={postcondition_met:true,first_met_elapsed_s:27.68,
    evidence:{source:'PhysicalTaskMonitor.update',elapsed_s:27.68,time_s:27.68,
      stage:'hold',tip_forces_n:[.3,.4],lift_m:.03,floor_contact:false,
      place_floor_contact:false,hold_duration_s:1.}};
  confirmed.events=[{skill:'Grasp',event:'postcondition_met',observation_index:0,
    elapsed_s:27.68,evidence:clone(confirmed.grasp.evidence)}];
}
assert.equal(confirmed.schema,'so101.physical-skill-evidence.v1');
assert.equal(confirmed.scope,'observation_only');
assert.equal(confirmed.grasp.postcondition_met,true);
assert.equal(confirmed.grasp.first_met_elapsed_s.toFixed(2),'27.68');
function siblingReplay(name) {
  const file=evidencePath && path.join(path.dirname(evidencePath),name);
  return file && fs.existsSync(file)?{file,value:JSON.parse(fs.readFileSync(file,'utf8'))}:undefined;
}
const cancelReplay=siblingReplay('cancel-replay.json');
const lostReplay=siblingReplay('payload_lost-replay.json');
const ungraspedReplay=siblingReplay('ungrasped-replay.json');
if(ungraspedReplay)unconfirmed=ungraspedReplay.value.evidence;
fs.mkdirSync(output,{recursive:true});
const result={passed:false,scope:'HTTP-fixture UI acceptance; no new physics',
  fixtureEvidenceSource:evidencePath ?? 'explicit synthetic UI fixture',stationSource:stationPath,
  originalReplaySources:[cancelReplay?.file,lostReplay?.file,ungraspedReplay?.file].filter(Boolean),
  checks:[],pageErrors:[],errors:[],blockedWrites:[],taskGets:[],cases:[]};
const panelFor=page=>page.getByTestId('panel-mouseenter-container RobotStation!so101station');
function task(status,phase,evidence,{nested=false,report={}}={}) {
  const value={id:fixtureId,status,phase,station:clone(station),
    simulation_s:status==='running'?27.68:(evidence?.observations.last_elapsed_s ?? 27.68),
    message:'HTTP fixture UI check only; no new physical execution',
    report:{passed:false,grasp_success:evidence?.grasp.postcondition_met===true,
      place_success:false,safety_stop:false,...report}};
  if(evidence) {
    if(nested)value.report.skill_evidence=clone(evidence);
    else value.skill_evidence=clone(evidence);
  }
  return value;
}
(async()=>{
  const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  const contexts=[];
  async function context(viewport,initial) {
    const ctx=await browser.newContext({viewport});contexts.push(ctx);
    let fixture=initial;
    await ctx.route('**/layouts/so101-station*.json',async route=>{
      const response=await route.fetch(),layout=await response.json();
      layout.configById['RobotStation!so101station'].executionTaskId=fixtureId;
      await route.fulfill({response,json:layout});
    });
    await ctx.route('**/api/so101/**',async route=>{
      const request=route.request(),url=new URL(request.url());
      if(!['GET','HEAD'].includes(request.method())) {
        result.blockedWrites.push({method:request.method(),url:request.url()});
        await route.abort('blockedbyclient');return;
      }
      if(url.pathname==='/api/so101/tasks' || url.pathname==='/api/so101/tasks/'+fixtureId) {
        result.taskGets.push({url:request.url(),status:fixture.status,phase:fixture.phase});
        await route.fulfill({json:url.pathname==='/api/so101/tasks'?{tasks:[fixture]}:fixture});
      } else if(url.pathname==='/api/so101/scene-mode') {
        // Keep mount in a read-only task scene; do not post editor previews.
        await route.fulfill({json:{mode:'task',taskId:fixtureId,status:fixture.status}});
      } else await route.continue();
    });
    const page=await ctx.newPage();page.on('pageerror',error=>result.pageErrors.push(error.message));
    return {ctx,page,setFixture:value=>{fixture=value;}};
  }
  async function verify(session,value,{statusLabel,label,name,initial=false}) {
    session.setFixture(value);
    const panel=panelFor(session.page);
    if(!initial) {
      const query=panel.getByRole('button',{name:'查询原任务',exact:true});
      await expect(query).toBeEnabled();await query.click();
    }
    const region=panel.getByRole('region',{name:'当前仿真任务',exact:true});
    await expect(region.getByText(statusLabel,{exact:true})).toBeVisible({timeout:90000});
    await expect(panel.getByText('原任务 ID：'+fixtureId,{exact:true})).toBeVisible();
    const evidence=region.getByTestId('physical-grasp-evidence');
    if(label===undefined)await expect(evidence).toHaveCount(0);
    else await expect(evidence).toHaveText(label);
    if(value.status!=='running') {
      await expect(panel.getByRole('button',{name:'取消任务',exact:true})).toBeDisabled();
      await expect(region).toContainText(value.report.passed?'物理验收：通过':'物理验收：未通过');
    }
    if(value.report.failure_reason==='payload_lost') {
      await region.getByText('本次任务原始物理报告',{exact:true}).click();
      await expect(region.locator('pre')).toContainText('"failure_reason": "payload_lost"');
      await expect(region.locator('pre')).toContainText('"passed": false');
    }
    result.cases.push({name,status:value.status,phase:value.phase,label,scope:'isolated HTTP fixture',
      reportPassed:value.report.passed,failureReason:value.report.failure_reason});
    result.checks.push(name);
    return {panel,region,evidence};
  }
  const pendingLabel='物理抓取证据：尚未确认；闭爪阶段不代表已抓住。';
  const labelFor=evidence=>`物理抓取证据：曾在 ${evidence.grasp.first_met_elapsed_s.toFixed(2)} s 确认持续持物；不代表本回合完成。`;
  const confirmedLabel=labelFor(confirmed);
  try {
    const desktop=await context({width:1600,height:1100},task('running','close',unconfirmed));
    await desktop.page.goto(base+'/so101-station');
    await verify(desktop,task('running','close',unconfirmed),{
      name:'running-close-not-confirmed',statusLabel:'正在运行 · close',label:pendingLabel,initial:true});
    await verify(desktop,task('running','hold',unconfirmed),{
      name:'running-hold-does-not-infer-grasp',statusLabel:'正在运行 · hold',label:pendingLabel});
    const current=await verify(desktop,task('running','hold',confirmed),{
      name:'confirmed-grasp-is-historical-not-whole-task-pass',statusLabel:'正在运行 · hold',label:confirmedLabel});
    await current.region.scrollIntoViewIfNeeded();
    await desktop.page.screenshot({path:path.join(output,'desktop-confirmed.png'),fullPage:true});
    const cancelEvidence=cancelReplay?.value.evidence ?? confirmed;
    const cancelled=task('cancelled','hold',cancelEvidence,{report:cancelReplay?
      {...cancelReplay.value.original_physical_acceptance,...cancelReplay.value.original_attempt_outcome}:
      {error_type:'Cancelled',failure_reason:'cancelled'}});
    const cancelledView=await verify(desktop,cancelled,{
      name:'later-cancelled-keeps-grasp-and-original-terminal',statusLabel:'已取消 · hold',label:labelFor(cancelEvidence)});
    await cancelledView.region.scrollIntoViewIfNeeded();
    await desktop.page.screenshot({path:path.join(output,'desktop-cancelled.png'),fullPage:true});
    const lossEvidence=lostReplay?.value.evidence ?? confirmed;
    const failed=task('failed','transport',lossEvidence,{nested:true,report:lostReplay?
      {...lostReplay.value.original_physical_acceptance,...lostReplay.value.original_attempt_outcome}:
      {failure_reason:'payload_lost'}});
    const failedView=await verify(desktop,failed,{
      name:'later-payload-lost-keeps-grasp-and-original-failure',statusLabel:'执行失败 · transport',label:labelFor(lossEvidence)});
    await failedView.region.scrollIntoViewIfNeeded();
    await desktop.page.screenshot({path:path.join(output,'desktop-failed.png'),fullPage:true});
    await verify(desktop,task('succeeded','done',undefined,{report:{passed:true,grasp_success:true,place_success:true}}),{
      name:'legacy-record-does-not-invent-new-evidence',statusLabel:'执行完成 · done'});
    await desktop.ctx.close();

    const mobile=await context({width:390,height:844},cancelled);
    await mobile.page.goto(base+'/so101-station-mobile');
    const narrow=await verify(mobile,cancelled,{
      name:'390px-cancelled-grasp-evidence',statusLabel:'已取消 · hold',label:labelFor(cancelEvidence),initial:true});
    await narrow.evidence.scrollIntoViewIfNeeded();const bounds=await narrow.evidence.boundingBox();
    assert(bounds && bounds.x>=0 && bounds.x+bounds.width<=391);
    assert(await mobile.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await mobile.page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    result.checks.push('390px-no-horizontal-overflow');await mobile.ctx.close();
    assert.deepEqual(result.blockedWrites,[]);assert.deepEqual(result.pageErrors,[]);
    result.checks.push('zero-post-or-other-write-attempts','zero-page-errors');result.passed=true;
  } catch(error) {
    result.errors.push(error.stack??String(error));process.exitCode=1;
  } finally {
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2)+'\n');
    for(const ctx of contexts)await ctx.close().catch(()=>{});await browser.close();
    console.log(JSON.stringify({passed:result.passed,checks:result.checks,errors:result.errors,
      writes:result.blockedWrites.length,pageErrors:result.pageErrors,output}));
  }
})();
