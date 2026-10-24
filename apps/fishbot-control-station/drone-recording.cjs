// SPDX-License-Identifier: MPL-2.0
const fs=require('node:fs');
const path=require('node:path');
const readline=require('node:readline');
const {createRequire}=require('node:module');
const upstream=createRequire(path.join(__dirname,'workbench/package.json'));
const {McapWriter}=upstream('@mcap/core');
const {sceneFor,schema,telemetrySchema,statusSchema}=require('./drone-scene.cjs');
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
 async function* frames(){
  const lines=readline.createInterface({input:fs.createReadStream(input),crlfDelay:Infinity});
  const trajectory=[];let previous=-1;
  for await(const line of lines){
   let sample;try{sample=JSON.parse(line);}catch{console.warn('WARNING: skipped incomplete flight telemetry line');continue;}
   if(!Number.isFinite(sample.simulation_s)||sample.simulation_s<previous||!sample.pose?.position)continue;
   previous=sample.simulation_s;trajectory.push(sample.pose.position);
   const values={scene:sceneFor(request.station,{...sample,trajectory},{...options,assetBase:''}),telemetry:sample.telemetry??{},status:{mode:'recording',taskId:request.id,status:sample.status,phase:sample.phase,simulation_s:sample.simulation_s}};
   yield {simulation_s:sample.simulation_s,values};
  }
 }
 const result=await writeFrames(output,definitions,frames());
 if(!result.frames)await fs.promises.unlink(output);
 return result;
}
module.exports={writeRecording,writeFrames};
