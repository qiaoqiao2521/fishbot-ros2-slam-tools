// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// Standard Foxglove transport. Geometry/FK and task state remain owned by MuJoCo.
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID}=require('node:crypto');
const {execFile}=require('node:child_process');
const {createRequire}=require('node:module');
const upstream=createRequire(path.join(__dirname,'workbench/package.json'));
const {FoxgloveServer}=upstream('@foxglove/ws-protocol');
const {WebSocketServer}=upstream('ws');
const schema=JSON.parse(fs.readFileSync(path.join(__dirname,'workbench-tools/schemas/SceneUpdate.json'),'utf8'));
function send(res,code,value){res.writeHead(code,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));}
async function body(req){let text='';for await(const chunk of req)text+=chunk;try{return JSON.parse(text);}catch{throw new Error('请提交有效的工作站 JSON。');}}
function createSo101Live({runtime}){
 const {python,sourceRoot,tasksRoot}=runtime.paths;
 const script=path.join(sourceRoot,'experiments/colab-twin/station_scene.py');
 const temporary=path.join(path.dirname(tasksRoot),'live-previews');fs.mkdirSync(temporary,{recursive:true});
 const foxglove=new FoxgloveServer({name:'SO101 MuJoCo live scene',supportedEncodings:['json']});
 const sockets=new WebSocketServer({noServer:true,handleProtocols:protocols=>foxglove.handleProtocols(protocols)});
 const channels={scene:foxglove.addChannel({topic:'/so101/live/scene',encoding:'json',schemaName:'foxglove.SceneUpdate',schema:JSON.stringify(schema)})};
 const number={type:'number'};
 for(const [key,topic,properties] of [
  ['joints','/so101/live/joints',{position:{type:'object',properties:Object.fromEntries(['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper'].map(k=>[k,number]))}}],
  ['contact','/so101/live/contact',{fixed_finger_n:number,moving_finger_n:number}],
  ['status','/so101/live/status',{mode:{type:'string'},taskId:{type:'string'},phase:{type:'string'},simulation_s:number,status:{type:'string'}}],
 ])channels[key]=foxglove.addChannel({topic,encoding:'json',schemaName:`so101.Live${key}`,schema:JSON.stringify({type:'object',properties})});
 let model,loading,previewScene,previewRevision=0,mode='draft',taskId,lastScene,sourceEpoch=0,previousIds=new Set(),error='',origin='';
 function pythonJSON(args){return new Promise((resolve,reject)=>execFile(python,[script,...args],{cwd:sourceRoot,env:{...process.env,MUJOCO_GL:'egl'},timeout:20000,maxBuffer:8*1024*1024},(failure,stdout,stderr)=>{
  if(failure){reject(new Error(stderr.trim().slice(-1500)||failure.message));return;}
  try{resolve(JSON.parse(stdout.trim().split('\n').at(-1)));}catch{reject(new Error('几何工具返回了无法读取的数据。'));}
 }));}
 async function loadModel(){
  if(model)return model;if(loading)return loading;
  loading=pythonJSON(['--model-json']).then(value=>{model=value;previewScene??=value.scene;error='';return value;}).catch(failure=>{error=failure.message;throw failure;}).finally(()=>{loading=undefined;});
  return loading;
 }
 async function preview(station){
  const revision=++previewRevision;const file=path.join(temporary,`${randomUUID()}.json`);fs.writeFileSync(file,JSON.stringify({station}));
  try{const scene=await pythonJSON(['--preview',file]);if(revision===previewRevision){previewScene=scene.scene??scene;error='';}return state();}
  finally{try{fs.unlinkSync(file);}catch{}}
 }
 function selectTask(id){sourceEpoch++;if(taskId!==id||mode!=='task'){mode='task';taskId=id;lastScene=undefined;}return state();}
 function state(){const task=mode==='task'&&taskId?runtime.task(taskId):undefined;
  return {mode,taskId:mode==='task'?taskId:undefined,status:task?.status??'preview',phase:task?.phase??'preview',simulation_s:task?.scene_time_s??task?.simulation_s,
    scene_seq:task?.scene_seq,sourceEpoch,ready:!!(mode==='task'?task?.scene:previewScene),message:error||undefined};}
 function publish(key,value,ns){foxglove.sendMessage(channels[key],ns,Buffer.from(JSON.stringify(value)));}
 function stream(){
  try{
   let task;const status=state();
   if(mode==='task'&&taskId){task=runtime.task(taskId);lastScene=task?.scene;}
   else lastScene=previewScene;
   const milliseconds=Date.now(),ns=BigInt(milliseconds)*1000000n,stamp={sec:Math.floor(milliseconds/1000),nsec:(milliseconds%1000)*1000000};
   const entities=(lastScene?.entities??[]).map(entity=>({...entity,timestamp:stamp,metadata:[...(entity.metadata??[]),{key:'view_mode',value:mode},{key:'task_id',value:mode==='task'?taskId:''}],models:(entity.models??[]).map(primitive=>({...primitive,url:primitive.url?.startsWith('/')?origin+primitive.url:primitive.url}))}));
   const ids=new Set(entities.map(e=>e.id));const deletions=[...previousIds].filter(id=>!ids.has(id)).map(id=>({timestamp:stamp,type:0,id}));previousIds=ids;
   publish('scene',{deletions,entities},ns);publish('status',status,ns);
   if(Array.isArray(task?.q6)&&task.q6.length===6)publish('joints',{position:Object.fromEntries(['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper'].map((name,i)=>[name,task.q6[i]]))},ns);
   if(Array.isArray(task?.tip_forces_n)&&task.tip_forces_n.length===2)publish('contact',{fixed_finger_n:task.tip_forces_n[0],moving_finger_n:task.tip_forces_n[1]},ns);
  }catch(failure){console.warn('WARNING: Live scene frame skipped:',failure.message);}
 }
 const timer=setInterval(stream,100);timer.unref();
 foxglove.on('error',failure=>console.warn('WARNING: Foxglove scene connection:',failure.message));
 function handleUpgrade(request,socket,head){
  const url=new URL(request.url,'http://localhost');const allowedOrigin=request.headers.origin;
  if(url.pathname!=='/api/so101/scene'||(allowedOrigin&&allowedOrigin!==origin)){socket.destroy();return;}
  sockets.handleUpgrade(request,socket,head,connection=>foxglove.handleConnection(connection,`${request.socket.remoteAddress}:${request.socket.remotePort}`));
 }
 function attach(server,{routeUpgrade=true}={}){
  server.on('listening',()=>{const address=server.address();origin=`http://127.0.0.1:${address.port}`;});
  if(routeUpgrade)server.on('upgrade',handleUpgrade);
  server.on('close',()=>{clearInterval(timer);sockets.close();});
  void loadModel().catch(failure=>console.warn('WARNING: Initial SO101 geometry unavailable:',failure.message));
 }
 async function handle(req,res,serveHandler){
  const url=new URL(req.url,'http://localhost');
  if(!['/api/so101/preview','/api/so101/scene-mode','/api/so101/scene-state'].includes(url.pathname)&&!url.pathname.startsWith('/api/so101/meshes/'))return false;
  try{
   const host=new URL(`http://${req.headers.host??'localhost'}`);
   if(!['127.0.0.1','localhost','[::1]'].includes(host.hostname)||(req.headers.origin&&req.headers.origin!==host.origin)){send(res,403,{error:'请从本机工作台访问三维场景。'});return true;}
   if(req.method==='GET'&&url.pathname==='/api/so101/scene-mode'){send(res,200,state());return true;}
   if(req.method==='GET'&&url.pathname==='/api/so101/scene-state'){send(res,200,{...state(),scene:lastScene});return true;}
   if(req.method==='POST'&&url.pathname==='/api/so101/preview'){const value=await body(req);send(res,200,await preview(value.station));return true;}
   if(req.method==='POST'&&url.pathname==='/api/so101/scene-mode'){
    const value=await body(req);
    if(value.mode==='draft'){
      // A late preview response never changes modes. Only this explicit action does.
      const requestedEpoch=++sourceEpoch;
      if(value.station)await preview(value.station);await loadModel();
      if(requestedEpoch!==sourceEpoch){send(res,200,state());return true;}
      mode='draft';lastScene=previewScene;send(res,200,state());return true;
    }
    if(value.mode==='task'&&typeof value.taskId==='string'&&runtime.task(value.taskId)){send(res,200,selectTask(value.taskId));return true;}
    send(res,400,{error:'请选择已存在的任务或编辑预览。'});return true;
   }
   if(['GET','HEAD'].includes(req.method)&&url.pathname.startsWith('/api/so101/meshes/')){
    const value=await loadModel();const name=decodeURIComponent(url.pathname.slice('/api/so101/meshes/'.length));
    const mesh=value.meshes.find(item=>item.file===name&&path.basename(item.file)===item.file);
    if(!mesh){send(res,404,{error:'未找到原SO101模型资源。'});return true;}
    req.url=`/${mesh.file}`;await serveHandler(req,res,{public:value.mesh_directory,directoryListing:false,cleanUrls:false,etag:true});return true;
   }
   send(res,405,{error:'该三维接口不支持此请求方法。'});
  }catch(failure){error=failure.message;send(res,400,{error:failure.message,mode,taskId});}
  return true;
 }
 return {attach,handleUpgrade,handle,preview,selectTask,state,stream,loadModel};
}
module.exports={createSo101Live};
