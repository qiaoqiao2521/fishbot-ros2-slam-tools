// SPDX-License-Identifier: MPL-2.0
// Terminal task artifact adapter. The converter reads saved samples only.
const fs=require('node:fs');
const path=require('node:path');
const {execFile}=require('node:child_process');
async function writeRecording(dir,options={}){
 const output=path.join(dir,'episode.mcap');
 const trajectory=path.join(dir,'episode/trajectory.json');
 const report=path.join(dir,'episode/report.json');
 if(!fs.existsSync(trajectory)||!fs.existsSync(report))return;
 try{
  const request=JSON.parse(await fs.promises.readFile(path.join(dir,'request.json'),'utf8'));
  if(options.taskId!==undefined&&request.id!==options.taskId)throw new Error('request UUID differs from selected task');
  let receipt;
  try{receipt=JSON.parse(await fs.promises.readFile(path.join(dir,'episode.recording.json'),'utf8'));}catch{}
  if(fs.existsSync(output)&&receipt?.task_id===request.id)return {path:output,existing:true,...receipt};
  const samples=JSON.parse(await fs.promises.readFile(trajectory,'utf8'));
  if(!Array.isArray(samples)||samples.length===0)return;
  if(!options.sourceRoot||!options.python)throw new Error('recording sourceRoot/python is not configured');
  const script=path.join(__dirname,'workbench-tools/so101_to_mcap.py');
  const result=await new Promise((resolve,reject)=>execFile(options.python,[script,'--task-dir',dir,'--source-root',options.sourceRoot,'--task-id',request.id],{
   cwd:options.sourceRoot,env:{...process.env,MUJOCO_GL:'egl',MPLBACKEND:'agg'},timeout:120000,maxBuffer:1024*1024,
  },(error,stdout,stderr)=>{
   if(error){reject(new Error(stderr.trim().slice(-1600)||error.message));return;}
   if(stderr.trim())console.warn(`WARNING: SO101 recording ${request.id}: ${stderr.trim().slice(-1600)}`);
   try{resolve(JSON.parse(stdout.trim().split('\n').at(-1)));}catch{reject(new Error('recording converter returned unreadable metadata'));}
  }));
  return fs.existsSync(output)?{...result,path:output}:undefined;
 }catch(error){console.warn(`WARNING: SO101 recording ${options.taskId??path.basename(dir)}: ${error.message}`);return;}
}
module.exports={writeRecording};
