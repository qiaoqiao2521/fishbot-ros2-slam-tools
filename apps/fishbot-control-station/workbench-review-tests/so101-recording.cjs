// SPDX-License-Identifier: MPL-2.0
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const {test}=require('node:test');
const {writeRecording}=require('../so101-recording.cjs');
function fixture(t,id='task-a'){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'so101-recording-'));
 t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 fs.mkdirSync(path.join(dir,'episode'));
 fs.writeFileSync(path.join(dir,'request.json'),JSON.stringify({id}));
 fs.writeFileSync(path.join(dir,'status.json'),JSON.stringify({status:'cancelled',skill_evidence:{grasp:true}}));
 fs.writeFileSync(path.join(dir,'episode/report.json'),JSON.stringify({passed:false}));
 fs.writeFileSync(path.join(dir,'episode/trajectory.json'),JSON.stringify([{elapsed_s:.02,q6:[0,0,0,0,0,0]}]));
 const python=path.join(dir,'converter-stub');
 fs.writeFileSync(python,`#!/usr/bin/env node
const fs=require('node:fs'),path=require('node:path');
const args=process.argv.slice(2),dir=args[args.indexOf('--task-dir')+1],id=args[args.indexOf('--task-id')+1];
fs.writeFileSync(path.join(dir,'episode.mcap'),id);
fs.writeFileSync(path.join(dir,'episode.recording.json'),JSON.stringify({task_id:id,status:'converted'}));
console.log(JSON.stringify({task_id:id,samples:1}));
`,{mode:0o755});
 return {dir,options:{sourceRoot:dir,python,taskId:id}};
}
test('two tasks keep their own artifact and preserve cancellation/report evidence',async t=>{
 const a=fixture(t,'alpha'),b=fixture(t,'beta');
 const before=fs.readFileSync(path.join(a.dir,'status.json'),'utf8');
 const [ra,rb]=await Promise.all([writeRecording(a.dir,a.options),writeRecording(b.dir,b.options)]);
 assert.equal(ra.task_id,'alpha');assert.equal(rb.task_id,'beta');
 assert.equal(fs.readFileSync(ra.path,'utf8'),'alpha');assert.equal(fs.readFileSync(rb.path,'utf8'),'beta');
 assert.equal(fs.readFileSync(path.join(a.dir,'status.json'),'utf8'),before);
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(a.dir,'episode/report.json'))),{passed:false});
});
test('empty trajectory does not create an artifact',async t=>{
 const {dir,options}=fixture(t);fs.writeFileSync(path.join(dir,'episode/trajectory.json'),'[]');
 assert.equal(await writeRecording(dir,options),undefined);assert.equal(fs.existsSync(path.join(dir,'episode.mcap')),false);
});
test('wrong selected task warns and leaves state unchanged',async t=>{
 const {dir,options}=fixture(t),before=fs.readFileSync(path.join(dir,'status.json'),'utf8');
 assert.equal(await writeRecording(dir,{...options,taskId:'another-task'}),undefined);
 assert.equal(fs.existsSync(path.join(dir,'episode.mcap')),false);
 assert.equal(fs.readFileSync(path.join(dir,'status.json'),'utf8'),before);
});
test('missing converter degrades without replacing the task result',async t=>{
 const {dir,options}=fixture(t),before=fs.readFileSync(path.join(dir,'status.json'),'utf8');
 assert.equal(await writeRecording(dir,{...options,python:path.join(dir,'missing-python')}),undefined);
 assert.equal(fs.readFileSync(path.join(dir,'status.json'),'utf8'),before);
});
test('same-task receipt permits reuse but a copied other-task artifact is rebuilt',async t=>{
 const {dir,options}=fixture(t);await writeRecording(dir,options);
 assert.equal((await writeRecording(dir,options)).existing,true);
 fs.writeFileSync(path.join(dir,'episode.mcap'),'stale-other-task');
 fs.writeFileSync(path.join(dir,'episode.recording.json'),JSON.stringify({task_id:'other-task'}));
 await writeRecording(dir,options);
 assert.equal(fs.readFileSync(path.join(dir,'episode.mcap'),'utf8'),'task-a');
});
