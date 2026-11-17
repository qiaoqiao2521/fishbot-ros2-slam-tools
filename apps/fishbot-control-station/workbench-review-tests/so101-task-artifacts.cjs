// SPDX-License-Identifier: MPL-2.0
// HTTP contract tests; fixture bytes are not a physical recording.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const {createRequire}=require('node:module');
const serve=createRequire(path.join(__dirname,'../workbench/web/package.json'))('serve-handler');
const {createTaskRuntime}=require('../task-runtime.cjs');
const {createSo101Runtime}=require('../so101-runtime.cjs');

async function fixture(t,so101=true){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'so101-artifacts-'));
 const ids=['a2-task-alpha','a2-task-beta'];
 for(const [i,id] of ids.entries()){
  const dir=path.join(root,id);fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir,'request.json'),JSON.stringify({id,submittedAt:`2026-11-06T00:00:0${i}Z`,station:{nodes:[],program:[]}}));
  fs.writeFileSync(path.join(dir,'report.json'),JSON.stringify({passed:i===0,task_id:id}));
  fs.writeFileSync(path.join(dir,'episode.mcap'),`fixture ${id}`);
  fs.writeFileSync(path.join(dir,'status.json'),JSON.stringify({status:i?'cancelled':'succeeded',report:'report.json',artifacts:{report:'report.json'},skill_evidence:{task_id:id,events:[{skill:'Grasp'}]}}));
 }
 const ensured=[];
 const options={sourceRoot:root,python:process.execPath,script:__filename,tasksRoot:root,apiPrefix:'/api/so101',label:'SO101',ensureArtifacts:id=>ensured.push(id)};
 const runtime=so101?createSo101Runtime(options):createTaskRuntime(options);
 const server=http.createServer(async(req,res)=>{if(!await runtime.handle(req,res,serve)){res.writeHead(404);res.end();}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{await new Promise(resolve=>server.close(resolve));fs.rmSync(root,{recursive:true,force:true});});
 return {root,ids,ensured,base:`http://127.0.0.1:${server.address().port}/api/so101/tasks`};
}

test('SO101 history lists do not convert every terminal task; selected GET uses its own ID',async t=>{
 const f=await fixture(t);
 const list=await(await fetch(f.base)).json();assert.equal(list.tasks.length,2);assert.deepEqual(f.ensured,[]);
 const alpha=await(await fetch(`${f.base}/${f.ids[0]}`)).json();
 assert.deepEqual(f.ensured,[f.ids[0]]);assert.equal(alpha.report.task_id,f.ids[0]);assert.equal(alpha.report.passed,true);
 assert.equal(alpha.skill_evidence.task_id,f.ids[0]);
 assert.equal(alpha.artifacts.mcap,`/api/so101/tasks/${f.ids[0]}/artifacts/mcap/episode.mcap`);
 const body=await(await fetch(`http://127.0.0.1:${new URL(f.base).port}${alpha.artifacts.mcap}`)).text();
 assert.equal(body,`fixture ${f.ids[0]}`);
 const beta=await(await fetch(`${f.base}/${f.ids[1]}`)).json();
 assert.equal(beta.status,'cancelled');assert.equal(beta.report.passed,false);assert.equal(beta.skill_evidence.task_id,f.ids[1]);
 assert.notEqual(alpha.artifacts.mcap,beta.artifacts.mcap);
 assert.equal((await fetch(`${f.base}/${f.ids[0]}/artifacts/mcap/another.mcap`)).status,404);
});

test('missing recording stays absent and an outside-task artifact is never served',async t=>{
 const f=await fixture(t);fs.unlinkSync(path.join(f.root,f.ids[0],'episode.mcap'));
 const alpha=await(await fetch(`${f.base}/${f.ids[0]}`)).json();assert.equal(alpha.artifacts.mcap,undefined);
 const dir=path.join(f.root,f.ids[1]);
 const status=JSON.parse(fs.readFileSync(path.join(dir,'status.json'),'utf8'));
 status.artifacts.mcap=path.join(f.root,'outside.mcap');fs.writeFileSync(status.artifacts.mcap,'outside');
 fs.writeFileSync(path.join(dir,'status.json'),JSON.stringify(status));
 const beta=await(await fetch(`${f.base}/${f.ids[1]}`)).json();assert.equal(beta.artifacts.mcap,undefined);
 assert.equal((await fetch(`${f.base}/${f.ids[1]}/artifacts/mcap/episode.mcap`)).status,404);
});

test('existing generic runtime retains list-time artifact generation for other platforms',async t=>{
 const f=await fixture(t,false);await fetch(f.base);assert.deepEqual([...f.ensured].sort(),[...f.ids].sort());
});
