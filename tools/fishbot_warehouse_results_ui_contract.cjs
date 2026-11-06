#!/usr/bin/env node
'use strict';
// Actual warehouse v3 MID scan and compile-timeout evidence. No UI-only routes or task execution.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
async function main(){
 const args=Object.fromEntries(process.argv.slice(2).reduce((r,v,i,a)=>i%2?r:[...r,[v.replace(/^--/,''),a[i+1]]],[]));
 const base=args.base||'http://127.0.0.1:5194';assert.equal(new URL(base).hostname,'127.0.0.1');assert.ok(args.output);fs.mkdirSync(args.output,{recursive:true});
 const result={passed:false,checks:[],writes:[],errors:[],scope:'Actual recovered warehouse v3 failure; six MID-360-style source frames, original compile-timeout query, native interface receipt and recorded video; no new ROS/physics/model/scoring'};
 const browser=await chromium.launch({executablePath:args.chromium||'/opt/google/chrome/chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',e=>result.errors.push(String(e)));page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))result.writes.push({method:r.method(),url:r.url()});});
 try{
  await page.goto(base+'/results');await page.locator('[data-result-experiment="f2-warehouse-v3"]').click();
  const card=page.locator('#j100-vision-delivery'),sensor=page.locator('.sensor-experience-panel'),chain=page.locator('.visual-evidence-panel'),timing=page.locator('#workbench-delivery-timing');
  await card.getByRole('heading',{name:'新仓库 v3 · 机械臂模型编译超时',exact:true}).waitFor();await sensor.locator('.sensor-panorama').waitFor();await chain.getByText('本运行没有已记录的RGB-D输入或模型候选',{exact:false}).waitFor();
  assert.equal(await page.locator('[data-result-group]').count(),4);assert.equal(await page.locator('[data-result-experiment="f2-workshop-v2"]').count(),1);assert.ok((await card.innerText()).includes('原评分未通过'));assert.ok((await card.innerText()).includes('A未派发'));
  assert.equal(await chain.locator('img').count(),0);assert.equal(await chain.getByRole('heading',{name:'所选抓取候选',exact:true}).count(),0);
  await chain.locator('.visual-query-section > summary').click();await chain.locator('.visual-query > summary').click();await chain.getByText('原30秒到期',{exact:true}).waitFor();await chain.getByText('机械臂模型编译开始',{exact:true}).waitFor();await chain.locator('.visual-query li').filter({hasText:'query_deadline_reached'}).getByText('累计 30.010 s',{exact:true}).waitFor();await chain.locator('.visual-query li').filter({hasText:'rig_model_compile_started'}).getByText('累计 23.688 s',{exact:true}).waitFor();assert.ok(!(await chain.innerText()).includes('模型推理请求'));
  await timing.getByText('f7472568-86da-4471-a9e6-531742adc3cc',{exact:false}).first().waitFor({state:'attached'});
  result.checks.push('original failed B and unexecuted A remain; empty entries have no invented RGB-D/candidates, real query ends30.010s after rig compile starts23.688s; matching timing task');
  assert.equal(await sensor.getByLabel('选择传感器源帧').locator('option').count(),6);assert.equal(await sensor.locator('.sensor-panorama circle').count(),1439);assert.ok((await sensor.innerText()).includes('MID-360式扫描'));
  await sensor.getByLabel('选择传感器源帧').selectOption('1');await sensor.getByText('e2677d31-a2e4-4bfe-9a19-4a802cffa1ff / 209',{exact:true}).waitFor({state:'attached'});assert.equal(await sensor.locator('.sensor-panorama circle').count(),1395);
  const capture=await (await page.request.get(base+'/workbench/f2-warehouse-v3/sensor-experience.json')).json();const native=await (await page.request.get(base+'/workbench/f2-warehouse-v3/native-lidar-consumer.json')).json();assert.equal(capture.sensor.horizontal_samples,4000);assert.equal(capture.sensor.lines,1);assert.deepEqual(capture.tf,{requested:6,matched_source:4,failed:2});assert.equal(native.target_cloud.points,1);assert.equal(native.tf.successful_lookups,1);assert.equal(native.global_parameters['lidar3d_voxel_layer.enabled'],true);
  assert.ok((await card.innerText()).includes('静态collision_map'));assert.ok((await card.innerText()).includes('不能把57个lethal cells归因为3D独有贡献'));
  await card.locator('.vision-result-evidence > summary').click();assert.equal(await card.getByRole('link',{name:'下载原生雷达链路回执'}).getAttribute('href'),'/workbench/f2-warehouse-v3/native-lidar-consumer.json');
  result.checks.push('real MID4000x1 and changing1439/1395 finite returns; captureTF4/6 separate from nativeTF1/1; original VoxelLayer receipt downloadable with static-map/no-exclusive-causality caveat');
  await page.waitForFunction(()=>document.querySelector('#j100-vision-delivery video')?.readyState>=1);const video=await card.locator('video').evaluate(v=>({duration:v.duration,width:v.videoWidth,height:v.videoHeight}));assert.equal(video.duration,130);result.video=video;
  await chain.screenshot({path:path.join(args.output,'compile-query-desktop.png')});await sensor.screenshot({path:path.join(args.output,'mid360-desktop.png')});
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await sensor.evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-130));const bounds=await sensor.locator('.sensor-panorama').boundingBox();assert.ok(bounds.y+bounds.height<844);await page.screenshot({path:path.join(args.output,'mid360-mobile.png')});await card.evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-130));await page.screenshot({path:path.join(args.output,'warehouse-mobile.png')});
  result.checks.push('actual130s sampling video decodes; desktop query/sensor and390px view without overflow, same-view real MID plot fits first screen');
  await page.locator('[data-result-experiment="f2-workshop-v2"]').click();await card.getByRole('heading',{name:'新车间 v2 · 麦轮进场失败',exact:true}).waitFor();assert.equal(await page.locator('.visual-evidence-panel').count(),0);
  await page.locator('[data-result-group="mecanum-3d"]').click();await card.getByText('28.68 s',{exact:true}).waitFor();assert.ok((await card.innerText()).includes('独立业务评分通过'));
  result.checks.push('existing v2 failure and historical successful group remain separate from v3 warehouse');assert.deepEqual(result.writes,[]);assert.deepEqual(result.errors,[]);result.passed=true;
 }finally{await browser.close();fs.writeFileSync(path.join(args.output,'ui-result.json'),JSON.stringify(result,null,2)+'\n');}
 console.log(JSON.stringify(result));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
