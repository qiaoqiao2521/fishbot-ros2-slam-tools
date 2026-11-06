#!/usr/bin/env node
'use strict';
// Explicitly UI-only route fixtures. No public evidence, simulator, ROS or score is generated.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
async function main() {
  const args = Object.fromEntries(process.argv.slice(2).reduce((rows,v,i,a)=>i%2?rows:[...rows,[v.replace(/^--/,''),a[i+1]]],[]));
  const base = args.base || 'http://127.0.0.1:5194'; assert.equal(new URL(base).hostname,'127.0.0.1'); assert.ok(args.output);
  fs.mkdirSync(args.output,{recursive:true});
  const result = { passed:false, checks:[], writes:[], errors:[], scope:'UI-only injected visual-chain and sensor-frame fixtures; never physical or task acceptance' };
  const browser = await chromium.launch({ executablePath:args.chromium || '/opt/google/chrome/chrome', headless:true,args:['--no-sandbox','--disable-dev-shm-usage'] });
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  page.on('pageerror',e=>result.errors.push(String(e)));
  page.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))result.writes.push({method:r.method(),url:r.url()});});
  const actual = await (await page.request.get(base+'/workbench/j100-vision-v5-result.json')).json();
  assert.equal(actual.orders[0].passed,false);
  const taskId=actual.orders[0].task_id;
  const identity={scene_sha256:'UI-only-scene',manifest_sha256:'UI-only-manifest',episode_id:'UI-only-episode',sequence:'42'};
  const frame=(sequence)=>({identity:{...identity,sequence},source_s:12.4,source_stamp_ns:'1793930000000000123',frame_id:'lidar3d_link',truth_to_control:false,observed:{source:'actual_received_PointCloud2 (UI-only fixture)',topic:'/sensors/lidar3d/points',points:[[1,0,.1],[.8,.3,.2],[-1,.01,.2],[-1,-.01,.3]],width:4000,height:1,valid_points:4},truth:{frame_id:'lidar3d_link',reference_only:true,omitted_nonbox_collision_geometries:5,boxes:[{id:'UI-only-box',vertices:[[-2,-.1,-.1],[-2,-.1,.1],[-2,.1,-.1],[-2,.1,.1],[-1,-.1,-.1],[-1,-.1,.1],[-1,.1,-.1],[-1,.1,.1]]}]},actual_tf:{source_frame:'lidar3d_link',target_frame:'map',source_stamp_ns:'1793930000000000123',translation_m:[1,2,0],quaternion_xyzw:[0,0,0,1]}});
  let wrongRun=false, missingDepth=false, missingFrame=false;
  const visual=()=>({schema:'fishbot.visual-chain.v1',run_id:wrongRun?'UI-only-other-run':actual.run_id,scene_id:'UI-only-scene',new_execution:false,rescored:false,warnings:['UI-only route fixture; not actual robot inference or physical evidence.'],entries:[{id:'UI-only-capture',task_id:taskId,arm_id:'load',cargo_id:'UI-only-cargo',phase:'load',observation:{sequence:42,stamp:12.4,episode_id:identity.episode_id,frame:'UI-only-camera',point_count:4},images:{rgb:'/workbench/ui-evidence/rgb.svg',depth:missingDepth?'/workbench/ui-evidence/depth-missing.svg':'/workbench/ui-evidence/depth.svg',mask:null,grasp_overlay:'/workbench/ui-evidence/candidate.svg'},points:{frame:'UI-only-camera',xyz:[[.1,.1,.2],[.12,.14,.3],[.16,.11,.4],[.11,.16,.5]]},selected:{index:51,score:.82,origin:'UI-only-obb'},inference:{status:'UI-only-inference_completed',request_wall_s:1.3,total_s:2.1,candidate_count:408},milestones:{lift:{source_s:14,image:'/workbench/ui-evidence/lift.svg',measured_lift_m:.04,original_passed:false},placement:null}}],queries:[{id:'UI-only-query',outcome:'UI-only-timeout',timeout_s:30,stages:[{stage:'planner_init_started',elapsed_wall_s:.1},{stage:'planner_init_completed',elapsed_wall_s:10},{stage:'official_inference_request_started',elapsed_wall_s:11},{stage:'official_inference_response_received',elapsed_wall_s:12.3},{stage:'query_timeout',elapsed_wall_s:30.1}]}]});
  const sensor={schema:'fishbot.sensor-experience.v1',status:'complete (UI-only fixture)',read_only:true,new_execution:false,rescored:false,truth_to_control:false,frame_id:'lidar3d_link',sensor:{scan_pattern:'livox_mid360_csv_stride5',lines:1,horizontal_samples:4000,rate_hz:10,angular_downsample:5,nominal_hardware_points_per_s:200000},frames:[42,43,44].map((n,i)=>({url:'frame-'+i+'.json',identity:{...identity,sequence:String(n)},source_s:12.4+i,valid_points:4})),actual_subscribers:[{node:'/global_costmap/global_costmap',type:'sensor_msgs/msg/PointCloud2'}],message_counts:{pointcloud:10,metadata:11,physics:50},tf:{requested:3,matched_source:3,failed:0},warnings:['UI-only route fixture; not actual PointCloud2 consumer acceptance.']};
  await page.route('**/workbench/**',async route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname==='/workbench/j100-vision-result.json')return route.fulfill({json:{...actual,preferred_recording:null,recordings:[],assets:{...actual.assets,visual_chain:'/workbench/ui-evidence/visual-chain.json',sensor_experience:'/workbench/ui-evidence/sensor-experience.json'}}});
    if(pathname==='/workbench/ui-evidence/visual-chain.json')return route.fulfill({json:visual()});
    if(pathname==='/workbench/ui-evidence/sensor-experience.json')return route.fulfill({json:sensor});
    if(pathname==='/workbench/ui-evidence/depth-missing.svg')return route.fulfill({status:404,body:''});
    if(pathname.startsWith('/workbench/ui-evidence/')&&pathname.endsWith('.svg'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#dbe8f7"/><text x="40" y="220" font-size="32">UI-only fixture</text></svg>'});
    const match=pathname.match(/^\/workbench\/ui-evidence\/frame-(\d)\.json$/);
    if(match){const i=Number(match[1]);if(i===1&&missingFrame)return route.fulfill({status:404,body:''});const data=frame(i===2?'999':String(42+i));return route.fulfill({contentType:'application/json',body:JSON.stringify(data).replaceAll('"1793930000000000123"','1793930000000000123')});}
    return route.continue();
  });
  const chain=page.locator('.visual-evidence-panel'), lidar=page.locator('.sensor-experience-panel');
  try {
    await page.goto(base+'/results');await chain.getByText('UI-only-inference_completed',{exact:false}).waitFor();await lidar.locator('.sensor-panorama').waitFor();
    assert.ok((await page.locator('#j100-vision-delivery').innerText()).includes('原评分未通过'));
    for(const title of ['RGB／深度输入','实际可见点云','所选抓取候选','实际抬升','实际放货'])assert.equal(await chain.getByRole('heading',{name:title,exact:true}).count(),1);
    await chain.getByText('实际放货采样画面未提供',{exact:true}).waitFor();await chain.getByText('原分项评分未通过',{exact:false}).waitFor();
    const images=chain.locator('img');assert.ok(await images.count()>=3);for(const image of await images.all())await image.scrollIntoViewIfNeeded();await page.waitForFunction(()=>[...document.querySelectorAll('.visual-evidence-panel img')].every(i=>i.complete&&i.naturalWidth>0));
    result.checks.push('five visual stages, actual whole-task false retained, missing placement and failed lift not shown as success; UI-only images load');
    const cloud=chain.locator('.visual-evidence-cloud svg');const before=await cloud.locator('circle').nth(1).getAttribute('cy');await chain.getByRole('button',{name:'XZ 投影',exact:true}).click();const after=await cloud.locator('circle').nth(1).getAttribute('cy');assert.notEqual(before,after);
    await chain.getByRole('button',{name:'XY 投影',exact:true}).click();
    await chain.locator('.visual-query-section > summary').click();await chain.locator('.visual-query > summary').click();await chain.getByText('累计 30.100 s',{exact:true}).waitFor();
    result.checks.push('visible-cloud XY/XZ switches recorded point projection; raw query 30.100s event visible without assigning CPU cause');
    const ns=lidar.locator('.sensor-experience-identity');assert.ok((await ns.textContent()).includes('1793930000000000123'));
    const svg=lidar.locator('.sensor-panorama');assert.equal(await svg.locator('circle').count(),4);
    const truthLines=svg.locator('line[stroke="#b7791f"]');assert.ok(await truthLines.count()>0);
    await lidar.getByLabel('实际点云',{exact:true}).uncheck();assert.equal(await svg.locator('circle').count(),0);await lidar.getByLabel('实际点云',{exact:true}).check();
    await lidar.getByLabel('真值 BOX 线框（只展示）',{exact:true}).uncheck();assert.equal(await truthLines.count(),0);await lidar.getByLabel('真值 BOX 线框（只展示）',{exact:true}).check();
    for(const line of await truthLines.all()){const a=Number(await line.getAttribute('x1')),b=Number(await line.getAttribute('x2'));assert.ok(Math.abs(a-b)<=360);}
    await lidar.getByLabel('选择传感器源帧').selectOption('1');await lidar.getByText('UI-only-episode / 43',{exact:true}).waitFor({state:'attached'});assert.ok((await ns.textContent()).includes('1793930000000000123'));
    result.checks.push('sensor layers independently toggle, seam edges do not cross panorama, frame changes preserve exact raw nanosecond integer');
    await lidar.getByLabel('选择传感器源帧').selectOption('2');await lidar.getByText('当前帧不参与叠加',{exact:false}).waitFor();assert.equal(await svg.count(),0);
    await lidar.getByLabel('选择传感器源帧').selectOption('0');await svg.waitFor();
    wrongRun=true;await chain.getByRole('button',{name:'刷新材料',exact:true}).click();await chain.getByText('与当前配送运行不一致',{exact:false}).waitFor();assert.equal(await chain.locator('img').count(),0);
    wrongRun=false;await chain.getByRole('button',{name:'刷新材料',exact:true}).click();await chain.locator('img').first().waitFor();
    result.checks.push('mismatched sensor sequence and visual run are not overlaid or borrowed from another record');
    await page.setViewportSize({width:390,height:844});await chain.locator('.visual-evidence-cloud svg').waitFor();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await chain.evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-130));await page.screenshot({path:path.join(args.output,'visual-mobile.png')});
    await lidar.evaluate(e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-130));await page.screenshot({path:path.join(args.output,'sensor-mobile.png')});
    await page.setViewportSize({width:1440,height:1100});await chain.screenshot({path:path.join(args.output,'visual-desktop.png')});await lidar.screenshot({path:path.join(args.output,'sensor-desktop.png')});
    result.checks.push('390px has no horizontal overflow; desktop/mobile visual and sensor panels captured');
    missingDepth=true;await chain.getByRole('button',{name:'刷新材料',exact:true}).click();await chain.getByText('米制深度的显示映射加载失败',{exact:true}).waitFor();assert.ok(await chain.getByText('UI-only-inference_completed',{exact:false}).count()>0);
    missingFrame=true;await lidar.getByLabel('选择传感器源帧').selectOption('1');await lidar.getByText('该帧不可读取（HTTP 404）',{exact:false}).waitFor();assert.equal(await lidar.locator('.sensor-panorama').count(),0);assert.ok((await page.locator('#j100-vision-delivery').innerText()).includes('原评分未通过'));
    result.checks.push('single image/frame 404 degrades only that material; original task summary remains');
    assert.deepEqual(result.writes,[]);assert.deepEqual(result.errors,[]);result.passed=true;
  }finally{await browser.close();fs.writeFileSync(path.join(args.output,'ui-result.json'),JSON.stringify(result,null,2)+'\n');}
  console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
