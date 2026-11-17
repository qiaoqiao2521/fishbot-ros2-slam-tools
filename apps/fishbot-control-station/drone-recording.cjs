// SPDX-License-Identifier: MPL-2.0
const fs=require('node:fs');
const path=require('node:path');
const readline=require('node:readline');
const {createRequire}=require('node:module');
const upstream=createRequire(path.join(__dirname,'workbench/package.json'));
const {McapWriter}=upstream('@mcap/core');
const {sceneFor,schema,telemetrySchema,statusSchema,stamp}=require('./drone-scene.cjs');
const pointCloudSchema=upstream('@foxglove/schemas/jsonschema').PointCloud;
const identity={position:{x:0,y:0,z:0},orientation:{x:0,y:0,z:0,w:1}};
function perceptionValues(sample,scene){
 const time=sample.simulation_s,p=sample.perception,cloud=p.cloud;
 const fresh=value=>value?.received_s!=null&&time-value.received_s>=0&&time-value.received_s<.5;
 // map is the author's local ENU frame, initialized at this world's takeoff origin.
 // Keep the actual points; do not align them to oracle obstacle boxes.
 const entities=scene.entities.filter(e=>!e.id.startsWith('observed-')&&!e.id.startsWith('obstacle-'));
 for(const kind of ['tracked','dynamic','predicted'])if(fresh(p[kind]))for(const box of p[kind].boxes){
  entities.push({id:`${kind}-${box.id}`,frame_id:'world',timestamp:stamp(time),lifetime:stamp(.5),frame_locked:false,metadata:[{key:'source',value:`/onboard_detector/${kind}_bboxes`},{key:'source_stamp',value:String(box.source_s??'unavailable')},{key:'track',value:box.text??''}],
   lines:[{type:2,pose:identity,thickness:.035,scale_invariant:false,points:box.points.map(([x,y,z])=>({x,y,z})),color:kind==='dynamic'?{r:1,g:.3,b:.4,a:1}:kind==='predicted'?{r:1,g:.45,b:.05,a:1}:{r:1,g:.8,b:.2,a:1},colors:[],indices:[]}]});
 }
 return {
  perceptionScene:{deletions:[{timestamp:stamp(time),type:1,id:''}],entities},
  cloud:{timestamp:stamp(fresh(cloud)?cloud.received_s:time),frame_id:'world',pose:identity,point_stride:12,
   fields:['x','y','z'].map((name,i)=>({name,offset:i*4,type:7})),data:fresh(cloud)?cloud.xyz_base64:''},
  perceptionStatus:{display_points:fresh(cloud)?cloud.display_points:0,input_points:cloud?.input_points??0,
   depth_source_s:p.depth?.source_s??0,depth_age_s:p.depth?.source_s!=null?time-p.depth.source_s:-1,
   cloud_receive_age_s:cloud?.received_s!=null?time-cloud.received_s:-1,
   cloud_source_stamp_available:cloud?.source_s!=null,
   tracked_boxes:fresh(p.tracked)?p.tracked.boxes.length:0,dynamic_boxes:fresh(p.dynamic)?p.dynamic.boxes.length:0,predicted_boxes:fresh(p.predicted)?p.predicted.boxes.length:0},
 };
}
// Both flight recordings and read-only diagnostic exports use the native MCAP writer.
async function writeFrames(output, definitions, frames){
 const temporary=`${output}.${process.pid}.tmp`,file=await fs.promises.open(temporary,'w');let offset=0n,count=0;
 try{
  const writer=new McapWriter({writable:{position:()=>offset,write:async data=>{
   let written=0;while(written<data.byteLength){const result=await file.write(data,written,data.byteLength-written,null);written+=result.bytesWritten;offset+=BigInt(result.bytesWritten);}
  }}});
  await writer.start({profile:'',library:'ros2-drone-workbench'});
  const channels={};
  for(const [key,definition] of Object.entries(definitions)){
   const schemaId=await writer.registerSchema({name:definition.name,encoding:'jsonschema',data:Buffer.from(JSON.stringify(definition.schema))});
   channels[key]=await writer.registerChannel({schemaId,topic:definition.topic,messageEncoding:'json',metadata:new Map()});
  }
  for await(const frame of frames){
   const ns=BigInt(Math.max(0,Math.round(frame.simulation_s*1e9)));
   for(const [key,value] of Object.entries(frame.values))await writer.addMessage({channelId:channels[key],sequence:count,logTime:ns,publishTime:ns,data:Buffer.from(JSON.stringify(value))});
   count++;
  }
  await writer.end();await file.close();await fs.promises.rename(temporary,output);
 }catch(error){await file.close().catch(()=>{});await fs.promises.unlink(temporary).catch(()=>{});throw error;}
 return {frames:count,path:output};
}
async function writeRecording(dir,options={}){
 const input=path.join(dir,'telemetry.jsonl'),output=path.join(dir,'flight.mcap');
 if(fs.existsSync(output)||!fs.existsSync(input)||fs.statSync(input).size===0)return;
 const request=JSON.parse(fs.readFileSync(path.join(dir,'request.json'),'utf8'));
 const definitions={};
 for(const [key,name,definition] of [['scene','foxglove.SceneUpdate',schema],['telemetry','drone.Telemetry',telemetrySchema],['status','drone.Status',statusSchema]]){
  definitions[key]={name,schema:definition,topic:`/drone/live/${key}`};
 }
 // Only perception-enabled tasks advertise the comparison channels.
 const head=readline.createInterface({input:fs.createReadStream(input),crlfDelay:Infinity});
 let hasPerception=false;
 try{for await(const line of head){try{hasPerception=!!JSON.parse(line).perception;break;}catch{}}}finally{head.close();head.input.destroy();}
 if(hasPerception){
  definitions.perceptionScene={name:'foxglove.SceneUpdate',schema,topic:'/drone/perception/scene'};
  definitions.cloud={name:'foxglove.PointCloud',schema:pointCloudSchema,topic:'/drone/perception/points'};
  definitions.perceptionStatus={name:'drone.PerceptionObservation',schema:{type:'object',properties:Object.fromEntries(['display_points','input_points','depth_source_s','depth_age_s','cloud_receive_age_s','tracked_boxes','dynamic_boxes','predicted_boxes'].map(k=>[k,{type:'number'}]))},topic:'/drone/perception/status'};
 }
 async function* frames(){
  const lines=readline.createInterface({input:fs.createReadStream(input),crlfDelay:Infinity});
  const trajectory=[];let previous=-1;
  for await(const line of lines){
   let sample;try{sample=JSON.parse(line);}catch{console.warn('WARNING: skipped incomplete flight telemetry line');continue;}
   if(!Number.isFinite(sample.simulation_s)||sample.simulation_s<previous||!sample.pose?.position)continue;
   previous=sample.simulation_s;trajectory.push(sample.pose.position);
   const values={scene:sceneFor(request.station,{...sample,trajectory},{...options,assetBase:''}),telemetry:sample.telemetry??{},status:{mode:'recording',taskId:request.id,status:sample.status,phase:sample.phase,simulation_s:sample.simulation_s}};
   if(sample.perception)Object.assign(values,perceptionValues(sample,values.scene));
   yield {simulation_s:sample.simulation_s,values};
  }
 }
 const result=await writeFrames(output,definitions,frames());
 if(!result.frames)await fs.promises.unlink(output);
 return result;
}
module.exports={writeRecording,writeFrames};
