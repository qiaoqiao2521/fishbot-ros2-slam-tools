// SPDX-License-Identifier: MPL-2.0
// SceneUpdate construction only: positions and rotations come from the executor.
const fs=require('node:fs');
const path=require('node:path');
const schema=JSON.parse(fs.readFileSync(path.join(__dirname,'workbench-tools/schemas/SceneUpdate.json'),'utf8'));
const telemetrySchema={type:'object',properties:{
 altitude_m:{type:'number'},speed_m_s:{type:'number'},armed:{type:'boolean'},landed:{type:'string'},
}};
const statusSchema={type:'object',properties:{
 mode:{type:'string'},taskId:{type:'string'},phase:{type:'string'},status:{type:'string'},simulation_s:{type:'number'},
}};
const identity={x:0,y:0,z:0,w:1};
const xyz=value=>Array.isArray(value)?{x:value[0],y:value[1],z:value[2]}:value;
function stamp(seconds=0){const ns=Math.max(0,Math.round(seconds*1e9));return {sec:Math.floor(ns/1e9),nsec:ns%1e9};}
function position(node,nodes){
 const result=[...(node.position??[0,0,0])],seen=new Set([node.id]);let parent=node.parent;
 while(parent&&parent!=='world'&&!seen.has(parent)){
  seen.add(parent);const found=nodes.find(n=>n.id===parent);if(!found)break;
  found.position.forEach((n,i)=>result[i]+=n);parent=found.parent;
 }
 return result;
}
function entity(id,seconds,parts){return {id,frame_id:'world',timestamp:stamp(seconds),lifetime:{sec:0,nsec:0},frame_locked:false,metadata:[],...parts};}
function line(points,color,thickness=.025){return {type:0,pose:{position:{x:0,y:0,z:0},orientation:identity},thickness,scale_invariant:false,points:points.map(xyz),color,colors:[],indices:[]};}
function sceneFor(station={},sample={},options={}){
 const seconds=sample.simulation_s??0,nodes=station.nodes??[],entities=[];
 entities.push(entity('drone-ground',seconds,{cubes:[{pose:{position:{x:0,y:0,z:-.06},orientation:identity},size:{x:20,y:20,z:.1},color:{r:.68,g:.72,b:.77,a:.5}}]}));
 for(const node of nodes){
  const p=xyz(position(node,nodes));
  if(node.kind==='target') entities.push(entity(`target-${node.id}`,seconds,{
   spheres:[{pose:{position:p,orientation:identity},size:{x:.14,y:.14,z:.14},color:{r:.1,g:.55,b:1,a:1}}],
   texts:[{pose:{position:{...p,z:p.z+.2},orientation:identity},billboard:true,font_size:.18,scale_invariant:false,color:{r:.1,g:.2,b:.3,a:1},text:node.name??node.id}],
  }));
  if(node.kind==='obstacle'&&node.enabled!==false){
   const observed=sample.obstacles?.find(obstacle=>obstacle.id===node.id);
   // A moving body's command is not its observed pose. Until observed, omit it.
   if(!options.preview&&node.motion&&!observed)continue;
   entities.push(entity(`obstacle-${node.id}`,seconds,{
    metadata:[{key:'station_node_id',value:node.id}],
    cubes:[{pose:{position:observed?xyz(observed.position):p,orientation:identity},
     size:xyz(observed?.size??node.size??[1,1,2]),color:{r:.85,g:.35,b:.12,a:1}}],
   }));
  }
 }
 const goalPath=(station.program??[]).flatMap(step=>{
  const node=nodes.find(n=>n.id===step.target);
  return node&&['takeoff','waypoint'].includes(step.action)?[position(node,nodes)]:[];
 });
 if(goalPath.length>1)entities.push(entity('planned-waypoints',seconds,{lines:[line(goalPath,{r:.15,g:.55,b:1,a:.6},.015)]}));
 if(options.plan?.points?.length>1){
  const plan=options.plan, unsafe=new Set(plan.unsafe_point_indices??[]);
  const lines=[];
  for(let i=1;i<plan.points.length;i++){
   const invalid=unsafe.has(i-1)||unsafe.has(i);
   lines.push(line([plan.points[i-1],plan.points[i]],invalid?{r:1,g:.12,b:.1,a:1}:{r:1,g:.78,b:.05,a:1},.04));
  }
  entities.push(entity('ego-offline-trajectory',seconds,{lines,metadata:[
   {key:'planner',value:plan.planner??'EGO-Swarm'},{key:'flight_control',value:'false'},
  ]}));
 }
  for(const column of options.plan?.px4_vertical_columns??[]){
   entities.push(entity(`px4-preview-${column.phase}`,seconds,{
    lines:[line([column.start,column.end],column.valid?{r:.55,g:.6,b:.65,a:.8}:{r:1,g:.12,b:.1,a:1},.025)],
    metadata:[{key:'controller',value:'PX4 vertical column'},{key:'flight_control',value:'false'}],
   }));
  }
 if(sample.trajectory?.length>1)entities.push(entity('actual-trajectory',seconds,{lines:[line(sample.trajectory,{r:.1,g:.8,b:.4,a:1},.035)]}));
 let pose=sample.pose;
 if(options.preview)pose={position:position(nodes.find(n=>n.kind==='robot')??{position:[0,0,0]},nodes),orientation:identity};
 if(pose?.position){
  const vehiclePose={position:xyz(pose.position),orientation:pose.orientation??identity};
  const models=options.models?.map(model=>({...model,url:options.assetBase+model.url,pose:composePose(vehiclePose,model.pose)}));
  if(models?.length) entities.push(entity('x500',seconds,{models}));
  else entities.push(entity('x500-pose-marker',seconds,{
   cubes:[{pose:vehiclePose,size:{x:.25,y:.16,z:.1},color:{r:.15,g:.25,b:.35,a:1}}],
   texts:[{pose:{position:{...vehiclePose.position,z:vehiclePose.position.z+.35},orientation:identity},billboard:true,font_size:.18,scale_invariant:false,color:{r:.15,g:.25,b:.35,a:1},text:'X500 位姿（模型加载中）'}],
  }));
 }
 return {deletions:[],entities};
}
function composePose(parent,local={position:{x:0,y:0,z:0},orientation:identity}){
 const a=parent.orientation,b=local.orientation;
 const q={x:a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,y:a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,z:a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w,w:a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z};
 const p=local.position,u={x:a.x,y:a.y,z:a.z},dot=u.x*p.x+u.y*p.y+u.z*p.z,uu=u.x*u.x+u.y*u.y+u.z*u.z;
 return {orientation:q,position:{
  x:parent.position.x+2*dot*u.x+(a.w*a.w-uu)*p.x+2*a.w*(u.y*p.z-u.z*p.y),
  y:parent.position.y+2*dot*u.y+(a.w*a.w-uu)*p.y+2*a.w*(u.z*p.x-u.x*p.z),
  z:parent.position.z+2*dot*u.z+(a.w*a.w-uu)*p.z+2*a.w*(u.x*p.y-u.y*p.x),
 }};
}
module.exports={sceneFor,schema,telemetrySchema,statusSchema,stamp,composePose};
