// SPDX-License-Identifier: MPL-2.0
const fs=require('node:fs');
const path=require('node:path');
const {isDeepStrictEqual}=require('node:util');
const {createRequire}=require('node:module');
const upstream=createRequire(path.join(__dirname,'workbench/package.json'));
const {FoxgloveServer}=upstream('@foxglove/ws-protocol');
const {WebSocketServer}=upstream('ws');
const {sceneFor,schema,telemetrySchema,statusSchema,stamp}=require('./drone-scene.cjs');
function createDroneLive({runtime,planning}){
 const foxglove=new FoxgloveServer({name:'PX4 Gazebo flight',supportedEncodings:['json']});
 const sockets=new WebSocketServer({noServer:true,handleProtocols:protocols=>foxglove.handleProtocols(protocols)});
 const channels={};
 for(const [key,name,definition]of [['scene','foxglove.SceneUpdate',schema],['telemetry','drone.Telemetry',telemetrySchema],['status','drone.Status',statusSchema]])
  channels[key]=foxglove.addChannel({topic:`/drone/live/${key}`,encoding:'json',schemaName:name,schema:JSON.stringify(definition)});
 let mode='draft',taskId,planId,plan,station={nodes:[],program:[]},origin='',sourceEpoch=0,previousIds=new Set(),lastScene;
 function modelInfo(){
  if(runtime.backend==='cerlab')return {models:[],files:[]};
  try{return JSON.parse(fs.readFileSync(path.join(runtime.paths.sourceRoot,'assets/x500-scene.json'),'utf8'));}
  catch{return {models:[],files:[]};}
 }
 function sceneOptions(){return {models:modelInfo().models,assetBase:origin,...(runtime.backend==='cerlab'?{vehicleName:'IRIS / CERLAB'}:{})};}
 function state(){
  const task=mode==='task'&&taskId?runtime.task(taskId):undefined;
  return {mode,taskId:mode==='task'?taskId:undefined,planId:mode==='draft'?planId:undefined,sourceEpoch,ready:mode==='draft'||!!task?.pose,
   status:task?.status??'preview',phase:task?.phase??'preview',simulation_s:task?.simulation_s};
 }
 function selectTask(id){taskId=id;mode='task';sourceEpoch++;return state();}
 function preview(value,id){
  // A completed calculation belongs to its input snapshot, never to a later edit.
  if(id){
   const candidate=planning?.task(id);
   if(!candidate?.report||!['succeeded','failed'].includes(candidate.status))throw new Error('预演尚未完成。');
   if(!isDeepStrictEqual(candidate.station,value))throw new Error('预演对应旧草稿，请重新预演。');
   planId=id;plan=candidate.report;
  }else if(!isDeepStrictEqual(station,value)){planId=undefined;plan=undefined;}
  station=JSON.parse(JSON.stringify(value));return state();
 }
 function stream(){
  try{
   const task=mode==='task'&&taskId?runtime.task(taskId):undefined;
   lastScene=sceneFor(task?.station??station,task??{}, {...sceneOptions(),preview:mode==='draft',plan:mode==='draft'?plan:undefined});
   const seconds=task?.simulation_s??0;
   const ids=new Set(lastScene.entities.map(entity=>entity.id));
   lastScene.deletions=[...previousIds].filter(id=>!ids.has(id)).map(id=>({timestamp:stamp(seconds),type:0,id}));previousIds=ids;
   for(const entity of lastScene.entities)entity.metadata.push({key:'view_mode',value:mode},{key:'task_id',value:taskId??''});
   const ns=BigInt(Math.max(0,Math.round(seconds*1e9)));
   for(const [key,value]of Object.entries({scene:lastScene,telemetry:task?.telemetry??{},status:state()}))
    foxglove.sendMessage(channels[key],ns,Buffer.from(JSON.stringify(value)));
  }catch(error){console.warn(`WARNING: flight scene frame skipped: ${error.message}`);}
 }
 const timer=setInterval(stream,100);timer.unref();
 foxglove.on('error',error=>console.warn(`WARNING: flight scene socket: ${error.message}`));
 function handleUpgrade(request,socket,head){
  if(new URL(request.url,'http://localhost').pathname!=='/api/drone/scene'||(request.headers.origin&&request.headers.origin!==origin)){socket.destroy();return;}
  sockets.handleUpgrade(request,socket,head,connection=>foxglove.handleConnection(connection,request.socket.remoteAddress));
 }
 function attach(server){
  server.on('listening',()=>{origin=`http://127.0.0.1:${server.address().port}`;});
  server.on('close',()=>{clearInterval(timer);sockets.close();});
 }
 function send(res,code,value){res.writeHead(code,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));}
 async function handle(req,res,serveHandler){
  const url=new URL(req.url,'http://localhost');
  if(!['/api/drone/preview','/api/drone/scene-mode','/api/drone/scene-state'].includes(url.pathname)&&!url.pathname.startsWith('/api/drone/meshes/'))return false;
  try{
   const host=new URL(`http://${req.headers.host??'localhost'}`);
   if(!['127.0.0.1','localhost','[::1]'].includes(host.hostname)||(req.headers.origin&&req.headers.origin!==host.origin)){send(res,403,{error:'请从本机工作台访问三维场景。'});return true;}
   if(req.method==='GET'&&url.pathname==='/api/drone/scene-mode'){send(res,200,state());return true;}
   if(req.method==='GET'&&url.pathname==='/api/drone/scene-state'){stream();send(res,200,{...state(),scene:lastScene});return true;}
   if(req.method==='POST'){
    let text='';for await(const chunk of req){text+=chunk;if(Buffer.byteLength(text)>1024*1024)throw new Error('场景 JSON 超过 1 MiB。');}
    const value=JSON.parse(text);
    if(url.pathname==='/api/drone/preview'){if(!Array.isArray(value.station?.nodes))throw new Error('缺少场景节点。');send(res,200,preview(value.station,value.planId));return true;}
    if(url.pathname==='/api/drone/scene-mode'){
     if(value.mode==='draft'){if(value.station)preview(value.station);mode='draft';taskId=undefined;sourceEpoch++;send(res,200,state());return true;}
     if(value.mode==='task'&&runtime.task(value.taskId)){send(res,200,selectTask(value.taskId));return true;}
     throw new Error('请选择已有任务或编辑预览。');
    }
   }
   if(['GET','HEAD'].includes(req.method)&&url.pathname.startsWith('/api/drone/meshes/')){
    const name=decodeURIComponent(url.pathname.slice('/api/drone/meshes/'.length)),info=modelInfo();
    if(!info.files?.includes(name)){send(res,404,{error:'未找到官方模型资源。'});return true;}
    req.url=`/${name}`;await serveHandler(req,res,{public:info.directory,directoryListing:false,cleanUrls:false,etag:true});return true;
   }
   send(res,405,{error:'不支持的三维操作。'});
  }catch(error){send(res,400,{error:error.message});}
  return true;
 }
 return {attach,handleUpgrade,handle,state,preview,selectTask,stream,sceneOptions};
}
module.exports={createDroneLive};
