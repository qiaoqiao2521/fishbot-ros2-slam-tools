// Real browser -> local task adapter -> existing MuJoCo executor acceptance.
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const {createRequire}=require('node:module');
const upstream=createRequire(path.join(__dirname,'../workbench/package.json'));
const {chromium,expect}=upstream('@playwright/test');
const base=process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
(async()=>{
 const out=process.env.STATION_QA_OUTPUT ?? path.join(__dirname,'output/station-execution');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 const result={passed:false,tasks:[],posts:[],pageErrors:[]};
 const save=()=>fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  page.on('pageerror',error=>result.pageErrors.push(error.message));
  page.on('request',request=>{if(request.method()==='POST' && request.url().includes('/api/so101/tasks'))result.posts.push({url:request.url(),body:request.postDataJSON()});});
  await page.goto(base+'/so101-station');
  const panel=page.getByTestId('panel-mouseenter-container RobotStation!so101station');
  const run=panel.getByRole('button',{name:'规划并运行仿真',exact:true});
  await expect(run).toBeEnabled({timeout:90000});
  if(process.env.STATION_SAMPLE){
   const samples={'x-plus20':'载入 X+20mm 布局','x-minus20':'载入 X−20mm 布局'};
   const name=samples[process.env.STATION_SAMPLE];
   assert(name,'Unknown STATION_SAMPLE; no task submitted');
   await panel.getByRole('button',{name,exact:true}).click();
  }
  const submitted=page.waitForResponse(response=>response.url()===base+'/api/so101/tasks' && response.request().method()==='POST');
  await run.click();const first=await(await submitted).json();result.tasks.push({id:first.id});save();
  await expect(panel).toContainText(first.id);
  await expect.poll(async()=>{const state=await(await page.request.get(base+'/api/so101/tasks/'+first.id)).json();return state.simulation_s??0;},{timeout:60000}).toBeGreaterThan(1);
  await page.reload();
  await expect(panel).toContainText(first.id,{timeout:60000});
  assert.equal(result.posts.filter(p=>!p.url.endsWith('/cancel')).length,1,'Reload must not submit a second task');
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
 }finally{save();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
