// SPDX-License-Identifier: MPL-2.0
const fs=require('node:fs');
const path=require('node:path');
const readline=require('node:readline');
const {createRequire}=require('node:module');
const upstream=createRequire(path.join(__dirname,'workbench/package.json'));
const {McapWriter}=upstream('@mcap/core');
const {sceneFor,schema,telemetrySchema,statusSchema}=require('./drone-scene.cjs');
async function writeRecording(dir,options={}){
 const input=path.join(dir,'telemetry.jsonl'),output=path.join(dir,'flight.mcap');
 if(fs.existsSync(output)||!fs.existsSync(input)||fs.statSync(input).size===0)return;
 const request=JSON.parse(fs.readFileSync(path.join(dir,'request.json'),'utf8'));
 const temporary=output+'.tmp',file=await fs.promises.open(temporary,'w');let offset=0n,count=0;
 try{
  const writer=new McapWriter({writable:{position:()=>offset,write:async data=>{
   let written=0;while(written<data.byteLength){const result=await file.write(data,written,data.byteLength-written,null);written+=result.bytesWritten;offset+=BigInt(result.bytesWritten);}
  }}});
  await writer.start({profile:'',library:'ros2-drone-workbench'});
  const channels={};
  for(const [key,name,definition] of [['scene','foxglove.SceneUpdate',schema],['telemetry','drone.Telemetry',telemetrySchema],['status','drone.Status',statusSchema]]){
   const schemaId=await writer.registerSchema({name,encoding:'jsonschema',data:Buffer.from(JSON.stringify(definition))});
   channels[key]=await writer.registerChannel({schemaId,topic:`/drone/live/${key}`,messageEncoding:'json',metadata:new Map()});
  }
  const lines=readline.createInterface({input:fs.createReadStream(input),crlfDelay:Infinity});
  const trajectory=[];let previous=-1;
  for await(const line of lines){
   let sample;try{sample=JSON.parse(line);}catch{console.warn('WARNING: skipped incomplete flight telemetry line');continue;}
   if(!Number.isFinite(sample.simulation_s)||sample.simulation_s<previous||!sample.pose?.position)continue;
   previous=sample.simulation_s;trajectory.push(sample.pose.position);
   const ns=BigInt(Math.max(0,Math.round(sample.simulation_s*1e9)));
   const values={scene:sceneFor(request.station,{...sample,trajectory},{...options,assetBase:''}),telemetry:sample.telemetry??{},status:{mode:'recording',taskId:request.id,status:sample.status,phase:sample.phase,simulation_s:sample.simulation_s}};
   for(const key of Object.keys(channels))await writer.addMessage({channelId:channels[key],sequence:count,logTime:ns,publishTime:ns,data:Buffer.from(JSON.stringify(values[key]))});
   count++;
  }
  await writer.end();await file.close();
  if(count)await fs.promises.rename(temporary,output);else await fs.promises.unlink(temporary);
 }catch(error){await file.close().catch(()=>{});await fs.promises.unlink(temporary).catch(()=>{});throw error;}
 return {frames:count,path:output};
}
module.exports={writeRecording};
