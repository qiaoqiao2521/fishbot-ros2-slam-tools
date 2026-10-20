// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
const path = require('node:path');
const os = require('node:os');
const {createTaskRuntime} = require('./task-runtime.cjs');
function createSo101Runtime(options = {}) {
  const sourceRoot=options.sourceRoot ?? process.env.SO101_ROOT ?? path.join(os.homedir(),'dev/ros2/projects/so101');
  return createTaskRuntime({
    label:'SO101',apiPrefix:'/api/so101',sourceRoot,
    python:process.env.SO101_PYTHON ?? path.join(os.homedir(),'.cache/so101-graspgenx/upstream/.venv/bin/python'),
    script:path.join(sourceRoot,'experiments/colab-twin/station_executor.py'),
    tasksRoot:process.env.SO101_TASKS_DIR ?? path.join(__dirname,'workbench-tools/output/station-tasks'),
    env:{MUJOCO_GL:'egl',MPLBACKEND:'agg'},
    message:'已连接固定八步抓放模板。',
    capabilities:['MuJoCo 仿真','RGB 定位与 IK/OMPL','抓取、放置、脱离与回位'],
    ...options,
  });
}
module.exports={createSo101Runtime};
