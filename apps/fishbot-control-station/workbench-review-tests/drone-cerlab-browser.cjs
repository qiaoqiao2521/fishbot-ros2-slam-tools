// Existing task entry -> native CERLAB -> indexed MCAP playback. No synthetic flight.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createRequire}=require('node:module');
const requireWorkbench=createRequire(path.join(__dirname,'../workbench/package.json'));
const {chromium,expect}=requireWorkbench('@playwright/test');
const {McapIndexedReader}=requireWorkbench('@mcap/core');
const {PNG}=requireWorkbench('pngjs');
const base=process.env.STATION_TEST_URL??'http://127.0.0.1:5187';
const output=process.env.CERLAB_QA_OUTPUT??path.join(__dirname,'output/cerlab-browser');
fs.mkdirSync(output,{recursive:true});
const cancelRun=process.env.CERLAB_CANCEL==='1';
const result={passed:false,posts:[],replayWrites:[],pageErrors:[],checks:[]};
const save=()=>fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2));
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}});
 page.on('pageerror',e=>result.pageErrors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/drone/tasks')){result.posts.push({url:r.url(),body:r.postDataJSON()});save();}});
 const getTask=async id=>{const r=await page.request.get(`${base}/api/drone/tasks/${id}`,{timeout:60000});assert(r.ok());return r.json();};
 try{
  let task;
  if(process.env.CERLAB_REPLAY_TASK_ID){task=await getTask(process.env.CERLAB_REPLAY_TASK_ID);}
  else{
   await page.goto(base+'/drone-station');
   let panel=page.getByTestId('panel-mouseenter-container RobotStation!dronestation');
   await expect(panel.getByRole('button',{name:'载入 CERLAB 往返示例',exact:true})).toBeVisible({timeout:90000});
   await panel.getByRole('button',{name:'载入 CERLAB 往返示例',exact:true}).click();
   const pending=page.waitForResponse(r=>r.url()===base+'/api/drone/tasks'&&r.request().method()==='POST');
   await panel.getByRole('button',{name:'起飞并执行仿真',exact:true}).click();
   const response=await pending;assert.equal(response.status(),202);
   task=await response.json();result.id=task.id;save();
   await expect.poll(async()=>{task=await getTask(result.id);return ['waypoint','return_home'].includes(task.phase)||['failed','succeeded'].includes(task.status);},{timeout:150000,intervals:[1000]}).toBe(true);
   assert.notEqual(task.status,'failed',task.message);
   await page.reload();
   panel=page.getByTestId('panel-mouseenter-container RobotStation!dronestation');
   await expect(panel.getByRole('button',{name:'查询原任务',exact:true})).toBeVisible({timeout:60000});
   assert.equal(result.posts.filter(p=>p.url===base+'/api/drone/tasks').length,1);
   assert.equal((await getTask(result.id)).id,result.id);
   result.checks.push('airborne-refresh-keeps-original-task-without-resubmission');save();
   const liveScene=page.getByTestId('panel-mouseenter-container 3D!dronelive');
   await expect.poll(async()=>{
    const png=PNG.sync.read(await liveScene.screenshot());let green=0;
    for(let i=0;i<png.data.length;i+=4)if(png.data[i+1]>100&&png.data[i+1]>png.data[i]*1.3&&png.data[i+1]>png.data[i+2]*1.2)green++;
    return green;
   },{timeout:30000}).toBeGreaterThan(5);
   result.checks.push('live-3d-shows-observed-flight-trail');
   await page.screenshot({path:path.join(output,'live.png'),fullPage:true});
   if(cancelRun){
    await panel.getByRole('button',{name:'取消并请求返航降落',exact:true}).click();
   }
   await expect.poll(async()=>{task=await getTask(result.id);result.last={id:task.id,status:task.status,phase:task.phase,message:task.message};save();return ['succeeded','failed','cancelled'].includes(task.status);},{timeout:240000,intervals:[1000]}).toBe(true);
  }
  result.task=task;result.id=task.id;save();
  assert.equal(task.status,cancelRun?'cancelled':'succeeded',task.message);
  assert.equal(task.report.landed_disarmed,true);
  assert.equal(task.report.backend,'cerlab');
  assert.equal(task.report.safety_qualified,false);
  assert(task.artifacts.mcap);
  result.checks.push(cancelRun?'web-cancel-returns-and-confirms-landed-disarmed':'web-submitted-native-flight-reaches-goals-and-observed-landing');
  const artifact=new URL(task.artifacts.mcap,base).href;
  const range=await page.request.get(artifact,{headers:{Range:'bytes=0-511'}});assert.equal(range.status(),206);
  const bytes=await (await page.request.get(artifact)).body();
  const reader=await McapIndexedReader.Initialize({readable:{size:async()=>BigInt(bytes.length),read:async(o,n)=>bytes.subarray(Number(o),Number(o+n))}});
  let count=0,first,last,airborne;
  for await(const m of reader.readMessages({topics:['/drone/live/scene'],validateCrcs:true})){
   const scene=JSON.parse(Buffer.from(m.data));
   const vehicle=scene.entities.find(e=>e.id==='x500-pose-marker');
   if(!vehicle)continue;
   const f={ns:m.logTime.toString(),s:Number(m.logTime)/1e9,z:vehicle.cubes[0].pose.position.z};
   first??=f;last=f;if(!airborne||f.z>airborne.z)airborne=f;count++;
   assert.match(vehicle.texts[0].text,/IRIS/);
  }
  assert(count>20);assert(airborne.z>.7);assert(last.z<.15);
  const reverse=[];for await(const m of reader.readMessages({topics:['/drone/live/status'],reverse:true})) {reverse.push(m.logTime);if(reverse.length===2)break;}
  assert(reverse[0]>=reverse[1]);result.mcap={frames:count,first,last,airborne,bytes:bytes.length};
  const replay=await browser.newContext({viewport:{width:1600,height:1100}});
  await replay.route('**/*',route=>{const r=route.request();if(!['GET','HEAD'].includes(r.method())){result.replayWrites.push(r.url());return route.abort();}return route.continue();});
  await replay.routeWebSocket('**/*',ws=>{result.replayWrites.push('websocket:'+ws.url());ws.close();});
  const view=await replay.newPage();
  result.replayUrl=base+'/?'+new URLSearchParams({ds:'remote-file','ds.url':artifact,layoutUrl:base+'/layouts/drone-review.json'});
  await view.goto(result.replayUrl);
  const timeInput=view.getByTestId('PlaybackTime-text').locator('input');
  await expect(timeInput).toBeVisible({timeout:90000});
  await expect(view.getByTestId('play-button')).toBeEnabled();
  const scenePanel=view.getByTestId('panel-mouseenter-container 3D!dronelive');
  for(const [name,frame]of [['initial',first],['airborne',airborne],['landed',last],['rewound',first]]){
   await timeInput.fill(frame.s.toFixed(9));await timeInput.press('Enter');await timeInput.blur();
   await expect.poll(async()=>Number(await timeInput.inputValue())).toBeCloseTo(frame.s,5);
   await scenePanel.screenshot({path:path.join(output,`replay-${name}.png`)});
  }
  const initialTime=Number(await timeInput.inputValue());
  await view.getByTestId('play-button').click();
  await expect.poll(async()=>Number(await timeInput.inputValue())).toBeGreaterThan(initialTime+.1);
  await view.getByTestId('play-button').click();
  assert.deepEqual(result.replayWrites,[]);
  result.checks.push('native-mcap-seek-rewind-and-play-with-zero-control-writes');
  result.passed=true;save();
 }catch(e){result.error=e.stack;save();throw e;}
 finally{await browser.close();}
 console.log(JSON.stringify({passed:result.passed,id:result.id,checks:result.checks,output}));
})().catch(e=>{console.error(e);process.exitCode=1;});
