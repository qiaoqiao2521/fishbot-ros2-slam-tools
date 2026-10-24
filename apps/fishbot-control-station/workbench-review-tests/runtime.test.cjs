const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { createSo101Runtime } = require('../so101-runtime.cjs');
const { createTaskRuntime } = require('../task-runtime.cjs');
const station={name:'test',nodes:[],program:[]};
async function until(check) {for(let i=0;i<100;i++){if(check()) return;await new Promise(r=>setTimeout(r,30));}throw new Error('Task did not finish');}
function fixture() {
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'so101-runtime-'));
 const script=path.join(root,'worker.cjs');
 fs.writeFileSync(script,`const fs=require('node:fs'),path=require('node:path');
 if(process.argv.includes('--describe-json')){console.log(JSON.stringify({message:'test CLI',capabilities:['simulation']}));process.exit(0);}
 const value=name=>process.argv[process.argv.indexOf(name)+1];const dir=value('--output-dir');const request=JSON.parse(fs.readFileSync(value('--station')));let n=0;
 const save=v=>{fs.writeFileSync(path.join(dir,'tmp.json'),JSON.stringify(v));fs.renameSync(path.join(dir,'tmp.json'),path.join(dir,'status.json'));};
 fs.appendFileSync(path.join(dir,'started.txt'),'once\\n');
 const interval=setInterval(()=>{if(fs.existsSync(value('--cancel-file'))){save({status:'cancelled',phase:'stopped',report:{passed:false}});clearInterval(interval);return;}
 const gated=request.station.skillControl?.mode==='hold-before-carry';
 if(gated&&!fs.existsSync(path.join(dir,'carry-resume.request'))){save({status:'running',phase:'hold',carry_gate:{mode:'hold-before-carry',state:'waiting'}});return;}
 if(++n<10){save({status:'running',phase:gated?'transport':'simulate',...(gated?{carry_gate:{mode:'hold-before-carry',state:'released'}}:{})});return;}fs.writeFileSync(path.join(dir,'report.json'),JSON.stringify({passed:true}));save({status:'succeeded',report:{passed:true},artifacts:{report:path.join(dir,'report.json')}});clearInterval(interval);},30);`);
 return {root, runtime:createSo101Runtime({python:process.execPath,script,sourceRoot:root,tasksRoot:path.join(root,'tasks')})};
}
test('same task ID starts one process; input snapshot and final report survive adapter restart',async()=>{
 const {root,runtime}=fixture();
 try {
  const first=runtime.submit('task-test-1234',station);assert.equal(first.code,202);
  const again=runtime.submit('task-test-1234',{...station,name:'changed'});assert.equal(again.code,200);
  await until(()=>runtime.task('task-test-1234')?.status==='succeeded');
  assert.equal(runtime.task('task-test-1234').station.name,'test');
  assert.equal(fs.readFileSync(path.join(root,'tasks/task-test-1234/started.txt'),'utf8'),'once\n');
  assert.equal(runtime.task('task-test-1234').artifacts.report,'/api/so101/tasks/task-test-1234/artifacts/report');
  const restored=createSo101Runtime({python:process.execPath,script:path.join(root,'worker.cjs'),sourceRoot:root,tasksRoot:path.join(root,'tasks')});
  assert.equal(restored.listTasks()[0].status,'succeeded');
 } finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('independent tasks run in parallel and cancelling one preserves the other',async()=>{
 const {root,runtime}=fixture();
 try{
  runtime.submit('task-cancel-1234',station);runtime.submit('task-continue-1234',station);
  assert.equal(runtime.cancel('task-cancel-1234').code,200);
  await until(()=>runtime.task('task-cancel-1234')?.status==='cancelled' && runtime.task('task-continue-1234')?.status==='succeeded');
  assert.equal(runtime.task('task-cancel-1234').report.passed,false);
  assert.equal(runtime.cancel('missing-task-123').code,404);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('invalid requests do not create task directories',()=>{
 const {root,runtime}=fixture();
 try{
  assert.equal(runtime.submit('../outside',station).code,400);
  assert.equal(runtime.submit(undefined,station).code,400);
  assert.equal(runtime.submit('task-bad-1234',{}).code,400);
  assert.deepEqual(runtime.listTasks(),[]);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('resume-carry writes one marker on the original HTTP task and never restarts its worker',async()=>{
 const {root,runtime}=fixture(); const id='task-carry-1234';
 const server=http.createServer((request,response)=>{void runtime.handle(request,response,()=>{});});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const url=`http://127.0.0.1:${server.address().port}/api/so101/tasks/${id}/resume-carry`;
 try{
  assert.equal(runtime.runtime().resume_carry,true);
  runtime.submit(id,{...station,skillControl:{mode:'hold-before-carry'}});
  await until(()=>runtime.task(id)?.carry_gate?.state==='waiting');
  const marker=path.join(root,'tasks',id,'carry-resume.request');
  const first=await fetch(url,{method:'POST'});assert.equal(first.status,200);
  const value=await first.json();assert.equal(value.id,id);assert.equal(value.carryResumeRequested,true);
  const stamp=fs.statSync(marker,{bigint:true}).mtimeNs;
  await until(()=>runtime.task(id)?.carry_gate?.state==='released');
  const repeat=await fetch(url,{method:'POST'});assert.equal(repeat.status,200);
  assert.equal((await repeat.json()).id,id);
  assert.equal(fs.statSync(marker,{bigint:true}).mtimeNs,stamp);
  await until(()=>runtime.task(id)?.status==='succeeded');
  assert.equal(fs.readFileSync(path.join(root,'tasks',id,'started.txt'),'utf8'),'once\n');
  assert.equal((await fetch(url,{method:'POST'})).status,409);
  assert.equal(runtime.task(id).report.passed,true);
 }finally{
  runtime.cancel(id);await until(()=>!runtime.task(id)||['succeeded','failed','cancelled'].includes(runtime.task(id).status));
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  fs.rmSync(root,{recursive:true,force:true});
 }
});
test('resume-carry rejects early, malformed, terminal and unsupported requests without task changes',()=>{
 const {root,runtime}=fixture();
 const seed=(id,control,gate,status='running')=>{
  const dir=path.join(root,'tasks',id);fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir,'request.json'),JSON.stringify({submittedAt:'2026-10-24',station:{...station,skillControl:control}}));
  fs.writeFileSync(path.join(dir,'status.json'),JSON.stringify({status,carry_gate:gate,report:{passed:false,failure_reason:'original'}}));
  return dir;
 };
 try{
  for(const [id,control,gate,status] of [
   ['task-early-1234',{mode:'hold-before-carry'},{mode:'hold-before-carry',state:'pending'},'running'],
   ['task-wrong-1234',{mode:'unknown'},{mode:'hold-before-carry',state:'waiting'},'running'],
   ['task-default-1234',undefined,{mode:'hold-before-carry',state:'waiting'},'running'],
   ['task-bad-gate-1234',{mode:'hold-before-carry'},{mode:'unknown',state:'waiting'},'running'],
   ['task-ended-1234',{mode:'hold-before-carry'},{mode:'hold-before-carry',state:'waiting'},'cancelled'],
  ]){
   const dir=seed(id,control,gate,status);const before=fs.readFileSync(path.join(dir,'status.json'),'utf8');
   assert.equal(runtime.resumeCarry(id).code,409);
   assert.equal(fs.existsSync(path.join(dir,'carry-resume.request')),false);
   assert.equal(fs.readFileSync(path.join(dir,'status.json'),'utf8'),before);
   assert.equal(fs.existsSync(path.join(dir,'process.json')),false);
  }
  const id='task-no-capability-1234';const dir=seed(id,{mode:'hold-before-carry'},{mode:'hold-before-carry',state:'waiting'});
  const unsupported=createTaskRuntime({...runtime.paths,label:'Drone',apiPrefix:'/api/drone'});
  assert.equal(unsupported.runtime().resume_carry,false);
  assert.equal(unsupported.resumeCarry(id).code,405);
  assert.equal(fs.existsSync(path.join(dir,'carry-resume.request')),false);
  assert.equal(runtime.resumeCarry('missing-task-1234').code,404);
  const cancelledId='task-cancel-requested-1234';
  const cancelledDir=seed(cancelledId,{mode:'hold-before-carry'},{mode:'hold-before-carry',state:'waiting'});
  runtime.cancel(cancelledId);
  const cancellation=fs.readFileSync(path.join(cancelledDir,'cancel.request'),'utf8');
  assert.equal(runtime.resumeCarry(cancelledId).code,409);
  assert.equal(fs.existsSync(path.join(cancelledDir,'carry-resume.request')),false);
  assert.equal(fs.readFileSync(path.join(cancelledDir,'cancel.request'),'utf8'),cancellation);
  assert.equal(runtime.task(cancelledId).status,'running');
  assert.equal(runtime.task(cancelledId).report.failure_reason,'original');
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
