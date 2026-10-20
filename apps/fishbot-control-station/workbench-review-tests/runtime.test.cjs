const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createSo101Runtime } = require('../so101-runtime.cjs');
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
 if(++n<10){save({status:'running',phase:'simulate'});return;}fs.writeFileSync(path.join(dir,'report.json'),JSON.stringify({passed:true}));save({status:'succeeded',report:{passed:true},artifacts:{report:path.join(dir,'report.json')}});clearInterval(interval);},30);`);
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
