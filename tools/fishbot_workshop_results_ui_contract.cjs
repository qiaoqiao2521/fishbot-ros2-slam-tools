#!/usr/bin/env node
'use strict';
// Actual recovered workshop v2 failure and sensor files. No routes inject fixture data.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
async function main(){
 const args=Object.fromEntries(process.argv.slice(2).reduce((r,v,i,a)=>i%2?r:[...r,[v.replace(/^--/,''),a[i+1]]],[]));
 const base=args.base||'http://127.0.0.1:5194';assert.equal(new URL(base).hostname,'127.0.0.1');assert.ok(args.output);fs.mkdirSync(args.output,{recursive:true});
 const result={passed:false,checks:[],writes:[],errors:[],scope:'Actual recovered v2 workshop failure; real 16-line PointCloud2 capture, video and original-source trajectory; no new ROS/physics/inference/scoring'};
 const browser=await chromium.launch({executablePath:args.chromium||'/opt/google/chrome/chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',e=>result.errors.push(String(e)));page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))result.writes.push({method:r.method(),url:r.url()});});
 try{
  await page.goto(base+'/results');await page.locator('[data-result-experiment="f2-workshop-v2"]').click();
  const card=page.locator('#j100-vision-delivery'),sensor=page.locator('.sensor-experience-panel'),timing=page.locator('#workbench-delivery-timing');
  await card.getByRole('heading',{name:'新车间 v2 · 麦轮进场失败',exact:true}).waitFor();await sensor.locator('.sensor-panorama').waitFor();
  assert.equal(await page.locator('[data-result-group]').count(),4);assert.ok((await card.innerText()).includes('原评分未通过'));assert.ok((await card.innerText()).includes('A未派发'));assert.equal(await page.locator('.visual-evidence-panel').count(),0);
  assert.equal(await card.locator('video').count(),1);await page.waitForFunction(()=>document.querySelector('#j100-vision-delivery video')?.readyState>=1);
  const video=await card.locator('video').evaluate(v=>({duration:v.duration,width:v.videoWidth,height:v.videoHeight}));assert.ok(video.width>0&&video.duration>0);result.video=video;
  assert.equal(await card.getByRole('link',{name:'下载录像帧时间索引'}).getAttribute('href'),'/workbench/f2-workshop-v2/video-frame-index.json');
  result.checks.push('independent new experiment; four old configurations unchanged; original false/A unexecuted retained; actual video decodes with original frame index');
  await card.locator('.regression-viewport svg').waitFor();await timing.getByText('1fc93a47-74b7-4922-ab18-5feb18e4d744',{exact:false}).first().waitFor({state:'attached'});
  assert.ok((await sensor.textContent()).includes('1fec8b37-dc3e-4735-afc4-be435ae59e4f'));assert.equal(await sensor.getByLabel('选择传感器源帧').locator('option').count(),6);
  const first=await sensor.locator('.sensor-panorama circle').count();assert.equal(first,5051);
  await sensor.getByLabel('选择传感器源帧').selectOption('5');await sensor.getByText('1fec8b37-dc3e-4735-afc4-be435ae59e4f / 619',{exact:true}).waitFor({state:'attached'});assert.equal(await sensor.locator('.sensor-panorama circle').count(),5091);
  const index=await (await page.request.get(base+'/workbench/f2-workshop-v2/sensor-experience.json')).json();const raw=await (await page.request.get(base+'/workbench/f2-workshop-v2/frame-5.json')).text();const ns=raw.match(/"source_stamp_ns":(\d+)/)[1];assert.ok((await sensor.locator('.sensor-experience-identity').textContent()).includes(ns));
  assert.deepEqual(index.tf,{requested:6,matched_source:5,failed:1});assert.equal(index.sensor.lines,16);
  await sensor.locator('.sensor-experience-evidence > summary').click();await sensor.getByText('订阅发现不等于逐消息消费ACK',{exact:false}).waitFor();assert.ok((await sensor.innerText()).includes('/collision_monitor'));
  await sensor.getByLabel('真值 BOX 线框（只展示）',{exact:true}).uncheck();assert.equal(await sensor.locator('.sensor-panorama line[stroke="#b7791f"]').count(),0);await sensor.getByLabel('真值 BOX 线框（只展示）',{exact:true}).check();
  result.checks.push('actual six frames, task/episode match, 5051/5091 finite returns and exact source nanoseconds; TF5/6 and original subscribers preserved; truth layer toggles');
  await card.screenshot({path:path.join(args.output,'workshop-desktop.png')});await sensor.screenshot({path:path.join(args.output,'sensor-desktop.png')});
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await card.evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-130));await page.screenshot({path:path.join(args.output,'workshop-mobile.png')});await sensor.evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-130));await page.screenshot({path:path.join(args.output,'sensor-mobile.png')});
  result.checks.push('actual failed record and six-frame sensor panel on desktop/390px without horizontal overflow');
  await page.locator('[data-result-group="mecanum-3d"]').click();await card.getByText('28.68 s',{exact:true}).waitFor();assert.ok((await card.innerText()).includes('独立业务评分通过'));assert.equal(await page.locator('.sensor-experience-panel').count(),0);
  result.checks.push('old accepted mecanum3D record remains independently selectable and does not borrow new sensor data');
  assert.deepEqual(result.writes,[]);assert.deepEqual(result.errors,[]);result.passed=true;
 }finally{await browser.close();fs.writeFileSync(path.join(args.output,'ui-result.json'),JSON.stringify(result,null,2)+'\n');}
 console.log(JSON.stringify(result));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
