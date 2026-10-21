// SPDX-License-Identifier: MPL-2.0
// Offline planning reuses persisted task identity; this worker cannot control PX4.
const path = require('node:path');
const os = require('node:os');
const {isDeepStrictEqual} = require('node:util');
const {createTaskRuntime} = require('./task-runtime.cjs');
function createDronePlanning(options={}) {
  const sourceRoot=options.sourceRoot??process.env.DRONE_ROOT??path.join(os.homedir(),'dev/ros2/projects/drone');
  const runtime=createTaskRuntime({
    label:'EGO 离线预演',service:'drone-planning',apiPrefix:'/api/drone',collection:'plans',
    sourceRoot,python:'/bin/bash',script:path.join(sourceRoot,'scripts/run_preview.sh'),
    tasksRoot:process.env.DRONE_PLANS_DIR??path.join(__dirname,'workbench-tools/output/drone-plans'),
    artifactKinds:['report'],artifactFiles:{report:'report.json'},descriptionRefreshMs:5000,
    ...options,
  });
  const handle=runtime.handle;
  return {...runtime,validateFlight(station,context) {
    if(station?.flight?.planner!=='ego')return undefined;
    const plan=runtime.task(context.planId);
    if(!plan||plan.status!=='succeeded'||plan.report?.valid!==true)
      return '请先完成 EGO 离线预演并确认有效轨迹，再显式起飞。';
    if(!isDeepStrictEqual(plan.station,station))return '场景已修改，请重新预演后起飞。';
    return undefined;
  },handle(req,res,serve) {
    const pathname=new URL(req.url,'http://localhost').pathname;
    if(pathname!=='/api/drone/plans'&&!pathname.startsWith('/api/drone/plans/'))return false;
    return handle(req,res,serve);
  }};
}
module.exports={createDronePlanning};
