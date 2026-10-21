// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// Loopback HTTP adapter for simulator CLIs. The worker owns
// phase/status.json and physical results; this module owns submission identity.
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
const VALID_ID = /^[a-zA-Z0-9][a-zA-Z0-9_-]{7,79}$/;
function readJSON(file) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return undefined; } }
function writeJSON(file, value) {
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n');
  fs.renameSync(temporary, file);
}
function send(response, code, value) {
  response.writeHead(code, {'Content-Type':'application/json; charset=utf-8', 'Cache-Control':'no-store'});
  response.end(JSON.stringify(value));
}
async function bodyJSON(request) {
  let body = ''; let bytes = 0;
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > 1024 * 1024) throw new Error('工作站文档超过 1 MiB，请减少内嵌内容。');
    body += chunk;
  }
  try { return JSON.parse(body); } catch { throw new Error('请求不是有效 JSON。'); }
}
function createTaskRuntime(options) {
  const {sourceRoot, python, script, tasksRoot, apiPrefix, label} = options;
  const collection = options.collection ?? 'tasks';
  const collectionRoute = `/${collection}`;
  const itemRoute = new RegExp(`^/${collection}/([^/]+)(?:/(cancel|return-home|artifacts/([a-z]+)(?:/([^/]+))?))?$`);
  const artifactKinds = options.artifactKinds ?? ['report','video'];
  fs.mkdirSync(tasksRoot, {recursive:true});
  const instanceId = randomUUID(); const children = new Map();
  let description; let describedAt = 0;
  function runtime() {
    const ready = fs.existsSync(python) && fs.existsSync(script);
    if (ready && (!description || description.ready === false || Date.now() - describedAt >= (options.descriptionRefreshMs ?? Infinity))) {
      const result = spawnSync(python, [script, '--describe-json'], {encoding:'utf8', timeout:10000, env:{...process.env, ...options.env}});
      description = undefined; describedAt = Date.now();
      if (result.status === 0) { try { description = JSON.parse(result.stdout.trim().split('\n').at(-1)); } catch {} }
      if (!description) return {ready:false, instance_id:instanceId, mode:'simulation', message:`执行器预检未通过，请检查 ${label} 环境。`, error:result.error?.message ?? result.stderr?.slice(-1000)};
    }
    return {ready:ready && description?.ready !== false, instance_id:instanceId, service:options.service ?? 'station', mode:'simulation', task_lookup:true, cancel:true,
      message:ready ? description?.message ?? options.message : `未找到 ${label} 执行脚本或 Python 环境。`,
      capabilities:description?.capabilities ?? options.capabilities ?? [], limits:description?.limits, executor:description};
  }
  function taskDir(id) { if (typeof id !== 'string' || !VALID_ID.test(id)) return undefined; return path.join(tasksRoot, id); }
  function artifactPath(id, kind) {
    const dir = taskDir(id); if (!dir) return undefined;
    const state = readJSON(path.join(dir,'status.json')) ?? {};
    const provided = state.artifact_paths?.[kind] ?? state.artifacts?.[kind] ?? state[`${kind}_path`] ?? options.artifactFiles?.[kind];
    if (typeof provided !== 'string') return undefined;
    try {
      const file = fs.realpathSync(path.resolve(dir,provided)); const base = fs.realpathSync(dir) + path.sep;
      return file.startsWith(base) && fs.statSync(file).isFile() ? file : undefined;
    } catch { return undefined; }
  }
  function task(id) {
    const dir = taskDir(id); if (!dir) return undefined;
    const request = readJSON(path.join(dir,'request.json')); if (!request) return undefined;
    const state = readJSON(path.join(dir,'status.json')) ?? {status:'pending', phase:'starting', message:'执行器正在启动。'};
    const artifacts = {};
    for (const kind of artifactKinds) if (artifactPath(id,kind)) {
      const filename=options.artifactNames?.[kind];
      artifacts[kind] = `${apiPrefix}${collectionRoute}/${id}/artifacts/${kind}${filename?`/${encodeURIComponent(filename)}`:''}`;
    }
    // Worker filenames remain local; the browser receives same-origin artifact URLs.
    const { artifact_paths:_paths, artifacts:_artifacts, ...rest } = state;
    const reportFile = artifactPath(id,'report');
    const report = typeof rest.report === 'string' && reportFile ? readJSON(reportFile) ?? rest.result : rest.report ?? rest.result;
    return {...rest, report, id, submittedAt:request.submittedAt, station:request.station, artifacts,
      cancelRequested:fs.existsSync(path.join(dir,'cancel.request'))};
  }
  function listTasks() {
    return fs.readdirSync(tasksRoot, {withFileTypes:true}).filter(entry=>entry.isDirectory() && VALID_ID.test(entry.name))
      .flatMap(entry=>{ const value=task(entry.name); return value ? [value] : []; })
      .sort((a,b)=>b.submittedAt.localeCompare(a.submittedAt));
  }
  function submit(id, station, context={}) {
    const dir = taskDir(id); if (!dir) return {code:400, value:{error:'任务 ID 格式无效。'}};
    const existing = task(id); if (existing) return {code:200, value:existing};
    const invalid = options.validateSubmission?.(station, context);
    if (invalid) return {code:400, value:{error:invalid}};
    const available = runtime(); if (!available.ready) return {code:503, value:{error:available.message}};
    if (!station || !Array.isArray(station.nodes) || !Array.isArray(station.program)) return {code:400, value:{error:'工作站需要 nodes 和 program 数组。'}};
    try { fs.mkdirSync(dir); } catch (error) {
      if (error.code === 'EEXIST') return {code:200, value:task(id) ?? {id,status:'pending',message:'同一任务正在创建，请查询原 ID。'}};
      throw error;
    }
    writeJSON(path.join(dir,'request.json'), {id, submittedAt:new Date().toISOString(), station,
      ...(context.planId ? {planId:context.planId} : {})});
    writeJSON(path.join(dir,'status.json'), {status:'pending',phase:'starting',message:'等待执行器读取工作站。'});
    const log = fs.openSync(path.join(dir,'worker.log'),'a');
    const child = spawn(python, [script, '--station',path.join(dir,'request.json'),'--output-dir',dir,'--cancel-file',path.join(dir,'cancel.request'),...(options.workerArgs?.(dir) ?? [])], {
      cwd:sourceRoot, detached:true, stdio:['ignore',log,log], env:{...process.env,...options.env,PYTHONUNBUFFERED:'1'},
    });
    fs.closeSync(log); children.set(id,child);
    writeJSON(path.join(dir,'process.json'), {pid:child.pid,serverInstanceId:instanceId});
    const failed = (error) => {
      if (!fs.existsSync(path.join(dir,'request.json'))) return;
      const state=readJSON(path.join(dir,'status.json')) ?? {};
      if (!TERMINAL.has(state.status)) {
        try { writeJSON(path.join(dir,'status.json'), {...state,status:'failed',phase:'worker_exit',message:error}); }
        catch (failure) { console.warn(`WARNING: Task ${id} could not save its failure: ${failure.message}`); }
      }
    };
    child.on('error',error=>failed(`执行器无法启动：${error.message}`));
    child.on('close',(code,signal)=>{
      children.delete(id);
      if (!fs.existsSync(path.join(dir,'request.json'))) return;
      const state=readJSON(path.join(dir,'status.json')) ?? {};
      if (!TERMINAL.has(state.status)) failed(`执行器结束但未提交终态（exit=${code}, signal=${signal ?? 'none'}）。请查看保留日志。`);
      Promise.resolve(options.onTaskFinished?.(id,dir)).catch(error=>console.warn(`WARNING: ${label} task artifact: ${error.message}`));
    });
    options.onTaskCreated?.(id);
    return {code:202,value:task(id)};
  }
  function cancel(id) {
    const current=task(id); if (!current) return {code:404,value:{error:'未找到原任务。'}};
    if (!TERMINAL.has(current.status)) fs.writeFileSync(path.join(taskDir(id),'cancel.request'),'cancel requested\n');
    return {code:200,value:task(id)};
  }
  function returnHome(id) {
    const current=task(id); if (!current) return {code:404,value:{error:'未找到原任务。'}};
    if (!options.returnHome) return {code:405,value:{error:'该执行器不支持返航。'}};
    if (!TERMINAL.has(current.status)) fs.writeFileSync(path.join(taskDir(id),'return-home.request'),'return home requested\n');
    return {code:200,value:task(id)};
  }
  async function handle(request,response,serveHandler) {
    const pathname=new URL(request.url,'http://localhost').pathname;
    if (!pathname.startsWith(`${apiPrefix}/`)) return false;
    const route=pathname.slice(apiPrefix.length);
    try {
      const host=new URL(`http://${request.headers.host ?? 'localhost'}`);
      if (!['127.0.0.1','localhost','[::1]'].includes(host.hostname) ||
          (request.headers.origin && request.headers.origin !== host.origin)) {
        send(response,403,{error:'请从本机工作台页面访问执行器。'}); return true;
      }
      if (route==='/runtime' && request.method==='GET') {send(response,200,runtime());return true;}
      if (route===collectionRoute && request.method==='GET') {
        const tasks=listTasks();
        for(const value of tasks) if(TERMINAL.has(value.status)) await options.ensureArtifacts?.(value.id,taskDir(value.id));
        send(response,200,{tasks:options.ensureArtifacts?listTasks():tasks});return true;
      }
      if (route===collectionRoute && request.method==='POST') {
        const body=await bodyJSON(request); const result=submit(body.taskId,body.station,body);send(response,result.code,result.value);return true;
      }
      const match=itemRoute.exec(route);
      if (match && VALID_ID.test(match[1])) {
        const id=match[1];
        if (request.method==='GET' && !match[2]) {
          let value=task(id);
          if(value&&TERMINAL.has(value.status)&&options.ensureArtifacts){await options.ensureArtifacts(id,taskDir(id));value=task(id);}
          send(response,value?200:404,value??{error:'未找到原任务。'});return true;
        }
        if (request.method==='POST' && match[2]==='cancel') {const result=cancel(id);send(response,result.code,result.value);return true;}
        if (request.method==='POST' && match[2]==='return-home') {const result=returnHome(id);send(response,result.code,result.value);return true;}
        if (['GET','HEAD'].includes(request.method) && artifactKinds.includes(match[3])) {
          const file=artifactPath(id,match[3]);
          if (!file || (match[4] && decodeURIComponent(match[4]) !== path.basename(file))) {send(response,404,{error:'该任务尚未生成此产物。'});return true;}
          request.url=`/${path.basename(file)}`;
          await serveHandler(request,response,{public:path.dirname(file),directoryListing:false,cleanUrls:false,etag:true});return true;
        }
      }
      send(response,404,{error:`未知 ${label} 接口。`});
    } catch(error) {send(response,request.method==='POST'?400:500,{error:error.message});}
    return true;
  }
  return {handle,runtime,task,listTasks,submit,cancel,returnHome,paths:{sourceRoot,python,script,tasksRoot}};
}
module.exports={createTaskRuntime};
