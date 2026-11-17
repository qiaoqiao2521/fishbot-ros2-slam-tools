const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const {createDronePlanning}=require('../drone-planning.cjs');
const {createDroneLive}=require('../drone-live.cjs');
const {sceneFor}=require('../drone-scene.cjs');

const station={name:'offline',platform:'px4',flight:{planner:'ego'},nodes:[
 {id:'box',kind:'obstacle',parent:'world',position:[3,0,1],size:[1,1,2]},
],program:[]};
test('offline plan retains original ID, snapshot and collection without dispatching flight',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'drone-plan-'));
 const script=path.join(root,'planner.cjs');
 fs.writeFileSync(script,`const fs=require('fs'),path=require('path');
 if(process.argv.includes('--describe-json')){console.log('{"ready":true}');process.exit(0);}
 const dir=process.argv[process.argv.indexOf('--output-dir')+1];
 fs.appendFileSync(path.join(${JSON.stringify(root)},'invocations'),'plan\\n');
 fs.writeFileSync(path.join(dir,'report.json'),JSON.stringify({valid:true,planner:'EGO-Swarm',flight_control:false,points:[[0,0,2],[1,0,2]]}));
 fs.writeFileSync(path.join(dir,'status.json'),JSON.stringify({status:'succeeded',report:'report.json'}));`);
 const plans=createDronePlanning({sourceRoot:root,python:process.execPath,script,tasksRoot:path.join(root,'plans')});
 const server=http.createServer(async(req,res)=>{if(!await plans.handle(req,res,()=>{})){res.writeHead(404);res.end();}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(async()=>{await new Promise(r=>server.close(r));fs.rmSync(root,{recursive:true,force:true});});
 const base=`http://127.0.0.1:${server.address().port}`;
 assert.equal((await fetch(`${base}/api/drone/tasks`)).status,404);
 const id='offline-plan-123';
 const submit=()=>fetch(`${base}/api/drone/plans`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({taskId:id,station})});
 assert.equal((await submit()).status,202);
 let plan;
 for(let i=0;i<100;i++){
  plan=await(await fetch(`${base}/api/drone/plans/${id}`)).json();
  if(plan.status==='succeeded')break;
  await new Promise(r=>setTimeout(r,20));
 }
 assert.equal(plan.status,'succeeded');
 assert.equal(plan.report.flight_control,false);
 assert.equal(plan.artifacts.report,`/api/drone/plans/${id}/artifacts/report`);
 assert.equal((await submit()).status,200);
 assert.equal(fs.readFileSync(path.join(root,'invocations'),'utf8'),'plan\n');
 assert.equal(plans.validateFlight(station,{planId:id}),undefined);
 assert.match(plans.validateFlight({...station,name:'changed'},{planId:id}),/重新预演/);
 assert.match(plans.validateFlight(station,{}),/离线预演/);
 assert.equal(plans.validateFlight({...station,flight:{planner:'waypoint'}},{}),undefined);
});

test('invalid completed curves remain visible in red; edits expire the old plan',()=>{
 const invalid={planner:'EGO-Swarm',valid:false,points:[[0,0,2],[3,0,2]],unsafe_point_indices:[1]};
 const planning={task:id=>id==='bad-plan'?{station,status:'failed',report:invalid}:undefined};
 const runtime={paths:{sourceRoot:'/nonexistent'},task:()=>undefined};
 const live=createDroneLive({runtime,planning});
 live.preview(station,'bad-plan');
 assert.equal(live.state().planId,'bad-plan');
 const scene=sceneFor(station,{}, {preview:true,plan:invalid});
 assert.equal(scene.entities.find(e=>e.id==='ego-offline-trajectory').lines[0].color.r,1);
 assert.equal(scene.entities.find(e=>e.id==='ego-offline-trajectory').lines[0].color.g,.12);
 assert.deepEqual(scene.entities.find(e=>e.id==='obstacle-box').metadata,[{key:'station_node_id',value:'box'}]);
 assert.throws(()=>live.preview({...station,name:'changed'},'bad-plan'),/旧草稿/);
 live.preview({...station,name:'changed'});
 assert.equal(live.state().planId,undefined);
});

test('failed plans without curve points still display unsafe PX4 columns',()=>{
 const plan={valid:false,points:[],px4_vertical_columns:[
  {phase:'takeoff',start:[0,0,0],end:[0,0,2],valid:false},
 ]};
 const scene=sceneFor(station,{}, {preview:true,plan});
 assert.ok(!scene.entities.some(e=>e.id==='ego-offline-trajectory'));
 const column=scene.entities.find(e=>e.id==='px4-preview-takeoff');
 assert.ok(column);
 assert.equal(column.lines[0].color.r,1);
 assert.equal(column.lines[0].color.g,.12);
});

test('moving obstacles show measured positions; absent measurements are not invented',()=>{
 const moving={...station,nodes:[{...station.nodes[0],
  motion:{type:'linear_ping_pong',axis:[0,1,0],distance_m:2,speed_m_s:.3}}]};
 assert.ok(!sceneFor(moving,{},{}).entities.some(e=>e.id==='obstacle-box'));
 assert.equal(sceneFor(moving,{}, {preview:true}).entities.find(e=>e.id==='obstacle-box').cubes[0].pose.position.y,0);
 const measured=sceneFor(moving,{obstacles:[{id:'box',position:[3,1.2,1],size:[1,1,2]}]},{});
 assert.equal(measured.entities.find(e=>e.id==='obstacle-box').cubes[0].pose.position.y,1.2);
 const disabled={...station,nodes:[{...station.nodes[0],enabled:false}]};
 assert.ok(!sceneFor(disabled,{}, {preview:true}).entities.some(e=>e.id==='obstacle-box'));
});
