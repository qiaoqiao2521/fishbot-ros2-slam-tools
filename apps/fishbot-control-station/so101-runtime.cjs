// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
const path = require('node:path');
const os = require('node:os');
const {createTaskRuntime} = require('./task-runtime.cjs');
const {writeRecording} = require('./so101-recording.cjs');
function createSo101Runtime(options = {}) {
  const sourceRoot=options.sourceRoot ?? process.env.SO101_ROOT ?? path.join(os.homedir(),'dev/ros2/projects/so101');
  const python=options.python ?? process.env.SO101_PYTHON ?? path.join(os.homedir(),'.cache/so101-graspgenx/upstream/.venv/bin/python');
  const pending=new Map();
  function ensureArtifacts(id,dir) {
    if(pending.has(id))return pending.get(id);
    const promise=writeRecording(dir,{sourceRoot,python,taskId:id})
      .catch(error=>console.warn(`WARNING: SO101 recording ${id}: ${error.message}`))
      .finally(()=>pending.delete(id));
    pending.set(id,promise);return promise;
  }
  return createTaskRuntime({
    label:'SO101',apiPrefix:'/api/so101',sourceRoot,
    python,
    script:path.join(sourceRoot,'experiments/colab-twin/station_executor.py'),
    tasksRoot:process.env.SO101_TASKS_DIR ?? path.join(__dirname,'workbench-tools/output/station-tasks'),
    env:{MUJOCO_GL:'egl',MPLBACKEND:'agg'},
    message:'已连接 MuJoCo 抓放执行器；工位参数逐任务检查。',
    capabilities:['MuJoCo 仿真','RGB 定位与 IK/OMPL','抓取、放置、脱离与回位'],
    artifactKinds:['report','video','mcap'],
    artifactFiles:{mcap:'episode.mcap'},artifactNames:{mcap:'episode.mcap'},
    onTaskFinished:ensureArtifacts,ensureArtifacts,ensureArtifactsOnList:false,
    resumeCarry:true,
    ...options,
  });
}
module.exports={createSo101Runtime};
