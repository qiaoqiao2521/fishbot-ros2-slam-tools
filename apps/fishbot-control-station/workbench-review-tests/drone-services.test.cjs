const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const {createRequire}=require('node:module');
const upstream=createRequire(path.join(__dirname,'../workbench/package.json'));
const {FoxgloveClient}=upstream('@foxglove/ws-protocol');
const WebSocket=upstream('ws');
const {McapIndexedReader}=upstream('@mcap/core');
const {createSo101Live}=require('../so101-live.cjs');
const {createDroneLive}=require('../drone-live.cjs');
const {writeRecording}=require('../drone-recording.cjs');
const {createDroneRuntime}=require('../drone-runtime.cjs');

async function until(check){for(let i=0;i<200;i++){const value=check();if(value)return value;await new Promise(r=>setTimeout(r,20));}throw new Error('Timed out waiting for contract');}
const station={name:'flight fixture',platform:'px4',nodes:[{id:'wp',kind:'target',parent:'world',position:[1,2,3]}],program:[]};
test('SO101 and drone streams coexist; draft updates cannot replace the actual flight',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'drone-stream-'));
 const script=path.join(root,'experiments/colab-twin/station_scene.py');fs.mkdirSync(path.dirname(script),{recursive:true});
 fs.writeFileSync(script,"console.log(JSON.stringify({meshes:[],mesh_directory:'.',scene:{entities:[]}}))");
 const tasks=new Map([['flight1',{station,status:'running',phase:'waypoint',simulation_s:2,pose:{position:[4,5,6],orientation:{x:0,y:0,z:0,w:1}},telemetry:{altitude_m:6,speed_m_s:1}}]]);
 const runtime={paths:{sourceRoot:root,python:process.execPath,tasksRoot:path.join(root,'tasks')},task:id=>tasks.get(id)};
 const arm=createSo101Live({runtime}),drone=createDroneLive({runtime});
 const server=http.createServer((req,res)=>{res.writeHead(404);res.end();});
 arm.attach(server,{routeUpgrade:false});drone.attach(server);
 server.on('upgrade',(req,socket,head)=>{
  const p=new URL(req.url,'http://localhost').pathname;
  if(p==='/api/so101/scene')arm.handleUpgrade(req,socket,head);
  else if(p==='/api/drone/scene')drone.handleUpgrade(req,socket,head);
  else socket.destroy();
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const sockets=[];t.after(async()=>{sockets.forEach(s=>s.terminate());await new Promise(r=>server.close(r));fs.rmSync(root,{recursive:true,force:true});});
 function connect(platform){
  const ws=new WebSocket(`ws://127.0.0.1:${server.address().port}/api/${platform}/scene`,FoxgloveClient.SUPPORTED_SUBPROTOCOL);
  sockets.push(ws);const client=new FoxgloveClient({ws}),topics=new Map(),messages=[];
  client.on('advertise',channels=>channels.forEach(c=>topics.set(client.subscribe(c.id),c.topic)));
  client.on('message',m=>messages.push({topic:topics.get(m.subscriptionId),value:JSON.parse(new TextDecoder().decode(m.data))}));
  return {messages,ws};
 }
 const armWire=connect('so101'),flightWire=connect('drone');
 drone.selectTask('flight1');
 await until(()=>armWire.messages.length&&flightWire.messages.length);
 drone.preview({...station,nodes:[{id:'base',kind:'robot',position:[99,99,99]}]});
 const actual=await until(()=>flightWire.messages.find(m=>m.topic==='/drone/live/scene'&&m.value.entities.some(e=>e.id==='x500-pose-marker')));
 assert.equal(actual.value.entities.find(e=>e.id==='x500-pose-marker').cubes[0].pose.position.x,4);
 assert.equal(drone.state().mode,'task');
 assert.equal(armWire.ws.readyState,WebSocket.OPEN);
 assert.ok(flightWire.messages.every(m=>m.topic.startsWith('/drone/')));
 assert.ok(armWire.messages.every(m=>m.topic.startsWith('/so101/')));
 for(const [suffix,origin]of [['/api/unknown/scene',undefined],['/api/drone/scene','http://unrelated.example']]){
  const rejected=new WebSocket(`ws://127.0.0.1:${server.address().port}${suffix}`,FoxgloveClient.SUPPORTED_SUBPROTOCOL,{origin});
  rejected.on('error',()=>{});sockets.push(rejected);
  await new Promise(resolve=>rejected.on('close',resolve));
 }
 assert.equal(armWire.ws.readyState,WebSocket.OPEN);
 assert.equal(flightWire.ws.readyState,WebSocket.OPEN);
 tasks.set('flight1',{...tasks.get('flight1'),status:'cancelled',phase:'landed'});
 await until(()=>flightWire.messages.find(m=>m.topic==='/drone/live/status'&&m.value.status==='cancelled'));
 assert.equal(drone.state().taskId,'flight1');
});

test('recorded MCAP preserves source time, pose and indexed backward reads',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'drone-recording-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 fs.writeFileSync(path.join(root,'request.json'),JSON.stringify({id:'fixture-flight',station}));
 const samples=[1,2,3].map(n=>({simulation_s:n+.125,pose:{position:[n,2*n,3*n],orientation:{x:0,y:0,z:0,w:1}},telemetry:{altitude_m:3*n,speed_m_s:1},phase:'waypoint'}));
 fs.writeFileSync(path.join(root,'telemetry.jsonl'),samples.map(s=>JSON.stringify(s)).join('\n')+'\n');
 const model={url:'/api/drone/meshes/meshes/x500.dae',pose:{position:{x:0,y:0,z:0},orientation:{x:0,y:0,z:0,w:1}}};
 assert.equal((await writeRecording(root,{assetBase:'http://127.0.0.1:5187',models:[model]})).frames,3);
 const bytes=fs.readFileSync(path.join(root,'flight.mcap'));
 const reader=await McapIndexedReader.Initialize({readable:{size:async()=>BigInt(bytes.length),read:async(offset,size)=>bytes.subarray(Number(offset),Number(offset+size))}});
 const values=[];for await(const m of reader.readMessages({topics:['/drone/live/scene'],reverse:true,validateCrcs:true}))values.push(m);
 assert.deepEqual(values.map(m=>m.logTime),[3125000000n,2125000000n,1125000000n]);
 const recordedModel=JSON.parse(Buffer.from(values[0].data)).entities.find(e=>e.id==='x500').models[0];
 assert.equal(recordedModel.pose.position.z,9);
 assert.equal(recordedModel.url,model.url);
 assert.equal(reader.channelsById.size,3);
});

test('drone discovery notices a newly built planner without restarting the server',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'drone-discovery-'));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const script=path.join(root,'describe.cjs');
 const save=planners=>fs.writeFileSync(script,`console.log(JSON.stringify({ready:true,planners:${JSON.stringify(planners)}}))`);
 save(['waypoint']);
 const runtime=createDroneRuntime({sourceRoot:root,python:process.execPath,script,tasksRoot:path.join(root,'tasks'),descriptionRefreshMs:0});
 assert.deepEqual(runtime.runtime().executor.planners,['waypoint']);
 save(['waypoint','ego']);
 assert.deepEqual(runtime.runtime().executor.planners,['waypoint','ego']);
});

test('MCAP task links select the native file reader and retain range-readable aliases',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'drone-artifacts-'));
 const id='recording-flight-123',dir=path.join(root,id);fs.mkdirSync(dir);
 fs.writeFileSync(path.join(dir,'request.json'),JSON.stringify({id,station}));
 fs.writeFileSync(path.join(dir,'status.json'),JSON.stringify({status:'succeeded'}));
 fs.writeFileSync(path.join(dir,'telemetry.jsonl'),JSON.stringify({simulation_s:1,pose:{position:[0,0,2]},telemetry:{altitude_m:2}})+'\n');
 const runtime=createDroneRuntime({sourceRoot:root,tasksRoot:root});
 const serveHandler=upstream('serve-handler');
 const server=http.createServer((req,res)=>runtime.handle(req,res,serveHandler));
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{await new Promise(r=>server.close(r));fs.rmSync(root,{recursive:true,force:true});});
 const base=`http://127.0.0.1:${server.address().port}`;
 const value=await (await fetch(`${base}/api/drone/tasks/${id}`)).json();
 assert.equal(path.extname(value.artifacts.mcap),'.mcap');
 for(const suffix of ['','/flight.mcap']){
  const response=await fetch(`${base}/api/drone/tasks/${id}/artifacts/mcap${suffix}`,{headers:{Range:'bytes=0-7'}});
  assert.equal(response.status,206);
  assert.equal(Buffer.from(await response.arrayBuffer()).toString('hex'),'894d434150300d0a');
 }
 assert.equal((await fetch(`${base}/api/drone/tasks/${id}/artifacts/mcap/other.mcap`)).status,404);
});

test('return-home and cancellation are requests, not immediate completed flight states',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'drone-controls-'));
 const script=path.join(root,'worker.cjs');
 fs.writeFileSync(script,`const fs=require('fs'),path=require('path');
 if(process.argv.includes('--describe-json')){console.log(JSON.stringify({ready:true}));process.exit(0);}
 const arg=n=>process.argv[process.argv.indexOf(n)+1],dir=arg('--output-dir');
 const save=s=>{fs.writeFileSync(path.join(dir,'status.tmp'),JSON.stringify(s));fs.renameSync(path.join(dir,'status.tmp'),path.join(dir,'status.json'));};
 save({status:'running',phase:'waypoint'});let landed=false;
 const timer=setInterval(()=>{if(fs.existsSync(arg('--return-home-file')))save({status:'running',phase:'returning_home'});
 if(fs.existsSync(arg('--cancel-file'))){if(!landed){save({status:'cancelling',phase:'landing'});landed=true;}else{save({status:'cancelled',phase:'landed',telemetry:{armed:false,landed:true}});clearInterval(timer);}}},80);`);
 const runtime=createDroneRuntime({sourceRoot:root,python:process.execPath,script,tasksRoot:path.join(root,'tasks')});
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 assert.equal(runtime.submit('flight-control-123',station).code,202);
 await until(()=>runtime.task('flight-control-123').status==='running');
 assert.equal(runtime.returnHome('flight-control-123').value.status,'running');
 await until(()=>runtime.task('flight-control-123').phase==='returning_home');
 assert.equal(runtime.cancel('flight-control-123').value.status,'running');
 await until(()=>runtime.task('flight-control-123').status==='cancelled');
 assert.equal(runtime.task('flight-control-123').telemetry.armed,false);
 assert.equal(runtime.submit('flight-control-123',{...station,name:'new'}).value.station.name,station.name);
});


test('CERLAB scenes preserve native obstacle orientation and never display the X500 asset',()=>{
 const {sceneFor}=require('../drone-scene.cjs');
 const orientation={x:0,y:0,z:Math.SQRT1_2,w:Math.SQRT1_2};
 const scene=sceneFor({nodes:[],program:[]},{backend:'cerlab',simulation_s:1,
  pose:{position:[1,2,1],orientation},obstacles:[{id:'wall',position:[-.75,0,1.25],size:[5.15,.15,2.5],orientation,source:'author_world_sdf'}]},
  {models:[{url:'x500.dae'}]});
 assert.equal(scene.entities.some(e=>e.models?.length),false);
 assert.deepEqual(scene.entities.find(e=>e.id==='observed-wall').cubes[0].pose.orientation,orientation);
 assert.match(scene.entities.find(e=>e.id==='x500-pose-marker').texts[0].text,/IRIS/);
});
