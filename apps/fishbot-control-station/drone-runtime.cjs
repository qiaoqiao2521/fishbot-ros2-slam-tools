// SPDX-License-Identifier: MPL-2.0
const path=require('node:path');
const os=require('node:os');
const {createTaskRuntime}=require('./task-runtime.cjs');
const {writeRecording}=require('./drone-recording.cjs');
function createDroneRuntime(options={}){
 const backend=options.backend??process.env.DRONE_BACKEND??'px4';
 const cerlab=backend==='cerlab';
 const sourceRoot=options.sourceRoot??(cerlab?process.env.CERLAB_ROOT??path.join(os.homedir(),'worktrees/drone-cerlab-20261031'):process.env.DRONE_ROOT??path.join(os.homedir(),'dev/ros2/projects/drone'));
 const pending=new Map();
 function ensureArtifacts(id,dir){
  if(pending.has(id))return pending.get(id);
  const promise=writeRecording(dir,options.sceneOptions?.()??{}).catch(error=>console.warn(`WARNING: flight recording ${id}: ${error.message}`)).finally(()=>pending.delete(id));
  pending.set(id,promise);return promise;
 }
 const runtime=createTaskRuntime({
  label:cerlab?'CERLAB':'PX4',service:'drone',apiPrefix:'/api/drone',sourceRoot,python:cerlab?'/usr/bin/python3':'/bin/bash',
  script:path.join(sourceRoot,cerlab?'cerlab/run_station.py':'scripts/run_executor.sh'),
  tasksRoot:process.env.DRONE_TASKS_DIR??path.join(__dirname,'workbench-tools/output/drone-tasks'),
  artifactKinds:['report','mcap'],artifactFiles:{report:'report.json',mcap:'flight.mcap'},
  // Lichtblick chooses its remote-file reader from the URL's file extension.
  artifactNames:{mcap:'flight.mcap'},
  message:'PX4 X500 本机仿真',returnHome:true,descriptionRefreshMs:5000,
  workerArgs:dir=>['--return-home-file',path.join(dir,'return-home.request')],
  onTaskFinished:ensureArtifacts,ensureArtifacts,
  ...options,
  validateSubmission(station,context){
   if(cerlab&&station?.flight?.planner!=='cerlab')return '当前执行器是 CERLAB，请载入 CERLAB 往返示例。';
   if(!cerlab&&station?.flight?.planner==='cerlab')return '当前服务尚未启用 CERLAB 执行器。';
   return options.validateSubmission?.(station,context);
  },
 });
 return {...runtime,backend};
}
module.exports={createDroneRuntime};
