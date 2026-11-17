// Real browser -> local task adapter -> existing MuJoCo executor acceptance.
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const {createRequire}=require('node:module');
const upstream=createRequire(path.join(__dirname,'../workbench/package.json'));
const {chromium,expect}=upstream('@playwright/test');
const base=process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
const carryAction=process.env.STATION_QA_CARRY_ACTION;
(async()=>{
 if(carryAction!==undefined){
  assert(['resume','cancel'].includes(carryAction),'STATION_QA_CARRY_ACTION must be resume or cancel');
  assert(process.env.STATION_DOCUMENT,'Carry QA requires the original station-carry-m2.json via STATION_DOCUMENT');
 }
 const out=process.env.STATION_QA_OUTPUT ?? path.join(__dirname,'output/station-execution');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:process.env.STATION_CHROME_BIN ?? '/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 const result={passed:false,tasks:[],posts:[],pageErrors:[]};
 if(carryAction)result.carry={schema:'so101.browser-carry-qa.v1',action:carryAction,physicalPassed:null,polls:[],snapshots:[],responseReadErrors:[]};
 const save=()=>fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 const responseReads=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  page.on('pageerror',error=>result.pageErrors.push(error.message));
  const postRows=new Map();
  page.on('request',request=>{if(request.method()==='POST' && request.url().includes('/api/so101/tasks')){
   const row={url:request.url(),body:request.postDataJSON()};
   if(carryAction){row.requestedAt=new Date().toISOString();postRows.set(request,row);}
   result.posts.push(row);
  }});
  if(carryAction){
   page.on('response',response=>{
    const row=postRows.get(response.request());if(!row)return;
    const reading=(async()=>{
     row.response={status:response.status(),receivedAt:new Date().toISOString()};
     try{const text=await response.text();try{row.response.body=JSON.parse(text);}catch{row.response.text=text;}}
     catch(error){row.response.readError=String(error);result.carry.responseReadErrors.push({url:row.url,error:String(error)});}
    })();responseReads.push(reading);
   });
   page.on('requestfailed',request=>{const row=postRows.get(request);if(row)row.requestFailure=request.failure();});
  }
  await page.goto(base+'/so101-station');
  const panel=page.getByTestId('panel-mouseenter-container RobotStation!so101station');
  const run=panel.getByRole('button',{name:'规划并运行仿真',exact:true});
  await expect(run).toBeEnabled({timeout:90000});
  let selectedScene;
  if(process.env.STATION_SAMPLE){
   const sample=process.env.STATION_SAMPLE;
   assert(['x-plus20','x-minus20'].includes(sample),'Unknown STATION_SAMPLE; no task submitted');
   assert(!process.env.STATION_DOCUMENT,'Choose a scene or import a document, not both');
   const control=panel.getByTestId('so101-scene-'+sample);
   const beforePosts=result.posts.length;
   await control.click();await expect(control).toHaveAttribute('aria-pressed','true');
   assert.equal(result.posts.length,beforePosts,'Selecting a scene must not start a task');
   const downloaded=page.waitForEvent('download');
   await panel.getByRole('button',{name:'导出 JSON',exact:true}).click();
   const exported=path.join(out,'scene-export.json');await(await downloaded).saveAs(exported);
   const station=JSON.parse(fs.readFileSync(exported,'utf8')).station;
   const sourceRoot=process.env.SO101_ROOT??path.join(require('node:os').homedir(),'dev/ros2/_delivery/so101-colab-20261001');
   const fixture=path.join(sourceRoot,'experiments/colab-twin/scenarios/workspace-station',sample+'.json');
   const expected=JSON.parse(fs.readFileSync(fixture,'utf8')).station;
   assert.deepEqual(station,expected,'Web scene must preserve the existing workcell input');
   selectedScene={id:sample,exported,fixture,station};result.scene=selectedScene;save();
   await expect.poll(async()=>page.evaluate(scene=>{
    const saved=value=>value&&typeof value==='object'&&
     ((value.station?.name===scene.name&&JSON.stringify(value.station.execution)===JSON.stringify(scene.execution)&&value.executionTaskId==='')||Object.values(value).some(saved));
    return Object.values(localStorage).some(raw=>{try{return saved(JSON.parse(raw));}catch{return false;}});
   },station),{timeout:15000}).toBe(true);
   await page.reload();await expect(control).toHaveAttribute('aria-pressed','true',{timeout:60000});
   await expect(panel.getByTestId('so101-current-scene')).toHaveAttribute('data-scene-id',sample);
   assert.equal(result.posts.length,beforePosts,'Scene refresh must not dispatch a task');
   result.scene.selectionRefresh=true;
   await page.screenshot({path:path.join(out,'selected-scene.png'),fullPage:true});save();
  }
  if(process.env.STATION_DOCUMENT){
   const fixture=path.resolve(process.env.STATION_DOCUMENT);
   const document=JSON.parse(fs.readFileSync(fixture,'utf8'));
   if(carryAction)assert.equal(document.station.skillControl?.mode,'hold-before-carry','Carry QA must use the declared original carry recipe');
   await panel.locator('input[type=file]').setInputFiles(fixture);
   await expect(panel.getByLabel('工作站名称',{exact:true})).toHaveValue(document.station.name);
   const downloaded=page.waitForEvent('download');
   await panel.getByRole('button',{name:'导出 JSON',exact:true}).click();
   const exported=path.join(out,'browser-export.json');await(await downloaded).saveAs(exported);
   const imported=JSON.parse(fs.readFileSync(exported,'utf8')).station;
   const stepIds=imported.program.map(step=>step.id);
   assert(stepIds.every(id=>typeof id==='string' && id.length>0) && new Set(stepIds).size===stepIds.length,'Imported steps must keep unique editor IDs');
   const executionContent=station=>({...station,program:station.program.map(({id,...step})=>step)});
   assert.deepEqual(executionContent(imported),executionContent(document.station),'Import/export must preserve every field except regenerated step editor IDs');
   result.importedFixture=fixture;result.browserExport=exported;result.importComparison={ignoredFields:['program[].id'],uniqueStepIds:true};save();
  }
  if(carryAction){
   const gate=panel.getByRole('checkbox',{name:'夹起后等待接续',exact:true});
   await expect(gate).toBeChecked();await gate.check();await expect(gate).toBeChecked();
   result.carry.recipeCheckboxChecked=true;save();
  }
  const submitted=page.waitForResponse(response=>response.url()===base+'/api/so101/tasks' && response.request().method()==='POST');
  const carrySubmission=carryAction?submitted.then(async response=>({known:true,status:response.status(),state:await response.json()}),
   error=>({known:false,error:String(error)})):undefined;
  await run.click();let first;
  if(carryAction){
   const observed=await carrySubmission;
   result.carry.submissionResponse={known:observed.known,status:observed.status,error:observed.error};
   const originalPost=result.posts.filter(p=>p.url===base+'/api/so101/tasks');assert.equal(originalPost.length,1);
   const originalId=originalPost[0].body.taskId;assert.equal(typeof originalId,'string');assert(originalId.length>0);
   if(observed.known){assert.equal(observed.status,202);first=observed.state;}
   else{
    // The submitted request already owns an ID even when its response is unknown.
    const response=await page.request.get(base+'/api/so101/tasks/'+originalId);
    assert.equal(response.status(),200);first=await response.json();
   }
   assert.equal(first.id,originalId);
   assert.deepEqual(originalPost[0].body.station,JSON.parse(fs.readFileSync(result.browserExport,'utf8')).station);
  }else first=await(await submitted).json();
  if(selectedScene){
   assert.deepEqual(first.station,selectedScene.station,'Submitted scene must match its browser export');
   const sceneRequest=result.posts.find(p=>p.url===base+'/api/so101/tasks');
   assert.deepEqual(sceneRequest.body.station,selectedScene.station);
   result.scene.taskId=first.id;
   await expect(panel.getByTestId('so101-scene-x-minus20')).toBeDisabled();
   await expect(panel.getByTestId('so101-scene-x-plus20')).toBeDisabled();
   result.scene.switchDisabledWhileRunning=true;
  }
  result.tasks.push({id:first.id});save();
  await expect(panel).toContainText(first.id);
  await expect.poll(async()=>{const state=await(await page.request.get(base+'/api/so101/tasks/'+first.id)).json();return state.simulation_s??0;},{timeout:60000}).toBeGreaterThan(1);
  await page.reload();
  await expect(panel).toContainText(first.id,{timeout:60000});
  assert.equal(result.posts.filter(p=>!p.url.endsWith('/cancel')).length,1,'Reload must not submit a second task');
  if(carryAction){
   const terminal=new Set(['succeeded','failed','cancelled']);
   const getTask=async phase=>{
    const response=await page.request.get(base+'/api/so101/tasks/'+first.id);
    assert.equal(response.status(),200);const state=await response.json();assert.equal(state.id,first.id);
    result.tasks[0]=state;
    result.carry.polls.push({phase,observedAt:new Date().toISOString(),http:response.status(),id:state.id,
     status:state.status,phaseName:state.phase,simulation_s:state.simulation_s,
     gateState:state.carry_gate?.state,waiting_since_s:state.carry_gate?.waiting_since_s,
     released_at_s:state.carry_gate?.released_at_s,cancelRequested:state.cancelRequested,
     carryResumeRequested:state.carryResumeRequested});save();return state;
   };
   const snapshot=async(label,state)=>{
    const stateFile=path.join(out,`carry-${label}-state.json`),imageFile=path.join(out,`carry-${label}.png`);
    fs.writeFileSync(stateFile,JSON.stringify(state,null,2));
    result.carry.snapshots.push({label,state:stateFile,screenshot:imageFile});save();
    await panel.getByRole('region',{name:'当前仿真任务'}).scrollIntoViewIfNeeded();
    await page.screenshot({path:imageFile,fullPage:true});
   };
   let waiting;
   await expect.poll(async()=>{waiting=await getTask('waiting');return waiting.carry_gate?.state==='waiting'||terminal.has(waiting.status);},
    {timeout:90000,intervals:[200,300]}).toBe(true);
   assert(!terminal.has(waiting.status),'Original task ended before the carry action');
   assert.equal(waiting.carry_gate?.mode,'hold-before-carry');assert.equal(waiting.carry_gate.state,'waiting');
   assert.equal(waiting.station.skillControl?.mode,'hold-before-carry');
   await expect(panel.getByTestId('carry-gate-status')).toContainText('等待接续搬运',{timeout:5000});
   await snapshot('waiting',waiting);
   const suffix=carryAction==='resume'?'resume-carry':'cancel';
   const actionUrl=base+'/api/so101/tasks/'+first.id+'/'+suffix;
   const actionResponse=page.waitForResponse(response=>response.url()===actionUrl&&response.request().method()==='POST',
    {timeout:10000}).then(response=>({known:true,status:response.status()}),error=>({known:false,error:String(error)}));
   result.carry.actionRequestedAt=new Date().toISOString();save();
   await panel.getByRole('button',{name:carryAction==='resume'?'接续搬运':'取消任务',exact:true}).click();
   result.carry.actionResponse=await actionResponse;save();
   if(result.carry.actionResponse.known)assert.equal(result.carry.actionResponse.status,200);
   // An unknown response is observed through GET of this ID; never click or POST again.
   const afterAction=await getTask('action');await snapshot('action',afterAction);
   let state;
   await expect.poll(async()=>{state=await getTask('terminal');return terminal.has(state.status);},
    {timeout:180000,intervals:[500,1000]}).toBe(true);
   await snapshot('terminal',state);
   assert.equal(state.status,carryAction==='resume'?'succeeded':'cancelled');
   assert.equal(state.report.passed,carryAction==='resume');assert.equal(state.report.safety_stop,false);
   if(carryAction==='resume'){
    assert.equal(state.report.controller_done,true);assert.equal(state.report.place_success,true);
    assert(state.carry_gate.released_at_s>=waiting.carry_gate.waiting_since_s);
   }else{
    assert.equal(state.cancelled,true);assert.equal(state.report.error_type,'Cancelled');
    assert.equal(typeof state.report.failure_reason,'string');assert(state.report.failure_reason.length>0);
   }
   result.carry.physicalPassed=state.report.passed;
   result.carry.physicalOutcome=carryAction==='resume'?'original_full_physical_pass':'original_cancelled_physical_failure';
   const video=await page.request.get(base+state.artifacts.video,{headers:{Range:'bytes=0-511'}});
   assert.equal(video.status(),206);assert((await video.body()).length>0);
   const report=await(await page.request.get(base+state.artifacts.report)).json();assert.deepEqual(report,state.report);
   await expect(panel.getByRole('region',{name:'当前仿真任务'})).toContainText(carryAction==='resume'?'执行完成':'已取消',{timeout:10000});
   await page.screenshot({path:path.join(out,carryAction==='resume'?'success.png':'cancelled.png'),fullPage:true});
   await Promise.allSettled(responseReads);
   assert.equal(result.posts.filter(p=>p.url===base+'/api/so101/tasks').length,1);
   assert.equal(result.posts.filter(p=>p.url===actionUrl).length,1);assert.equal(result.posts.length,2);
   assert.equal(result.posts[0].body.taskId,first.id);
   for(const post of result.posts)if(post.response?.body?.id!==undefined)assert.equal(post.response.body.id,first.id);
   assert.deepEqual(result.pageErrors,[]);
   result.passed=true;result.checks=['single-original-task','refresh-restores-original-task-no-repost',
    'declared-recipe-and-real-checkbox','original-gate-and-page-waiting','one-browser-'+suffix+'-same-id',
    'unknown-response-get-only','original-physical-'+(carryAction==='resume'?'full-pass':'cancelled-failure'),
    'original-report-and-video','no-page-errors'];save();
   console.log(JSON.stringify({passed:true,action:carryAction,task:state.id,status:state.status,physicalPassed:state.report.passed}));return;
  }
  await expect.poll(async()=>{const state=await(await page.request.get(base+'/api/so101/tasks/'+first.id)).json();result.tasks[0]=state;save();return state.status;},{timeout:180000,intervals:[1000,1500]}).toBe('succeeded');
  const state=result.tasks[0];assert.equal(state.report.passed,true);assert.equal(state.report.safety_stop,false);
  assert.equal(state.report.controller_done,true);assert.equal(state.report.place_success,true);
  const video=await page.request.get(base+state.artifacts.video,{headers:{Range:'bytes=0-511'}});
  assert.equal(video.status(),206);assert((await video.body()).length>0);
  const report=await(await page.request.get(base+state.artifacts.report)).json();assert.equal(report.passed,true);
  await expect(panel.getByRole('region',{name:'当前仿真任务'})).toContainText('执行完成',{timeout:10000});
  await panel.getByRole('region',{name:'当前仿真任务'}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'success.png'),fullPage:true});
  if(process.env.STATION_SINGLE_RUN==='1'){
   assert.equal(result.posts.length,1);assert.deepEqual(result.pageErrors,[]);
   result.passed=true;result.checks=['browser-started-full-grasp-place-detach-return','refresh-restores-original-task-no-repost','original-physical-report','new-video-range-read','no-page-errors'];save();
   console.log(JSON.stringify({passed:true,task:state.id,status:state.status,simulation_s:state.simulation_s}));
   return;
  }
  const secondResponse=page.waitForResponse(response=>response.url()===base+'/api/so101/tasks' && response.request().method()==='POST');
  await run.click();const second=await(await secondResponse).json();result.tasks.push({id:second.id});save();
  await expect.poll(async()=>{const s=await(await page.request.get(base+'/api/so101/tasks/'+second.id)).json();return s.simulation_s??0;},{timeout:60000}).toBeGreaterThan(2);
  await panel.getByRole('button',{name:'取消任务',exact:true}).click();
  await expect.poll(async()=>{const s=await(await page.request.get(base+'/api/so101/tasks/'+second.id)).json();result.tasks[1]=s;save();return s.status;},{timeout:90000,intervals:[500,1000]}).toBe('cancelled');
  await expect(panel.getByRole('region',{name:'当前仿真任务'})).toContainText('已取消',{timeout:10000});
  await page.screenshot({path:path.join(out,'cancelled.png'),fullPage:true});
  assert.equal(result.posts.filter(p=>!p.url.endsWith('/cancel')).length,2);
  assert.equal(result.posts.filter(p=>p.url.endsWith('/cancel')).length,1);
  assert.deepEqual(result.pageErrors,[]);
  result.passed=true;result.checks=['browser-started-full-grasp-place-detach-return','refresh-restores-original-task-no-repost','original-physical-report','new-video-range-read','browser-cooperative-cancel','distinct-task-ids','no-page-errors'];save();
  console.log(JSON.stringify({passed:true,tasks:result.tasks.map(t=>({id:t.id,status:t.status,simulation_s:t.simulation_s,result:t.result})),posts:result.posts.length}));
 }catch(error){if(carryAction)result.carry.failure={name:error.name,message:error.message,stack:error.stack};throw error;
 }finally{await Promise.allSettled(responseReads);save();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
