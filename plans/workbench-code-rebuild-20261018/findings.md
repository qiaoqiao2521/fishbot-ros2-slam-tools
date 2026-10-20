# 实施发现

- 官方源码归档固定为 `95713edb309d77589b130286642ab149995a5f7b`，17,376,926 字节，2,297 个源文件；来源和摘要在 `apps/fishbot-control-station/workbench/UPSTREAM.md`。
- 本机 Node 22.23.2；上游 packageManager 为 Yarn 4.17.0。AGENTS 的 Yarn 3.6.3 文案已落后于固定配置。
- 直接启动 Yarn 被上游 wrapper 拒绝，因为缺 Corepack。实际 Corepack 启动又受 `/home/muqiao/package.json` 的 ESM 作用域影响，报 `Dynamic require of util`。隔离 `COREPACK_HOME` 并声明其 CommonJS 作用域后，Yarn 4.17.0 正常启动。没有修改该主目录配置。
- 源码依赖使用 shared Panel、MessagePipeline 与 Player。最小任务面板直接使用原接口；注册、默认布局和深链已有实现，不新增状态总线。
- 原 FishBot 对话仍在修运动规划。新工作树使用明确已提交基线，尚未引入其未提交源码或修改运行服务。

## Knowledge

采用 CapMesh PIT-004 的依赖/发布周期隔离与现有任务身份复用。收尾为 already_covered；不把一次构建故障提升为新通用平台。

## P2/P3 已核实的接入合同

- `GET /api/v1/runtime`、`/sim-api/runtime`、`/coop-api/runtime`、`/voice-api/runtime` 已有只读身份与能力入口。它们由各自服务拥有，不能按端口或domain拼成同一环境。本轮查源码，未宣称CY进程可达。
- 原 `frontend/src/lib/runtime-context.ts` 的 RuntimeRegistry 和 runtimeFetch 可移入原生面板；原 `frontend/src/lib/cooperation.ts` 的 CooperationController 可在应用层单例复用。只做路径和配置适配，面板订阅同一个owner。
- `POST /coop-api/start` 只接受 `scope=dock|transport`（`tools/cooperation_core.py:163-192`）。transport包含车体停靠、机械臂装车和车体运输，不是独立SO101 full_cycle。
- `/coop-api/state?task_id=`只返回当前快照，客户端必须核对返回ID；历史最多10条。取消接纳、canceling和实际停稳必须分别显示。实例请求头 `X-Fishbot-Instance` 沿用原合同。
- 模型catalog是静态历史结果目录，不等于可以启动任意模型的运行时注册表。不得把已有录制成功当成按钮触发的新推理。
- SO101 `experiments/graspgenx-demo/full_cycle.py` 已有严格绑定motion plan/preflight的CLI。其 `--output` 参数指已审核候选目录；实际产物另建子目录。当前未找到独立HTTP runtime/start/cancel/task lookup与协作取消hook。
- 下一步由根与SO101模块owner接回现有CLI生命周期；不得以杀进程冒充取消落盘，也不得用协同transport接口替代独立抓放。FishBot原根仍在验证运动路径，合并须等其可交付基线，保留在途改动。

## 视觉人工审查

浏览器full-a的9项行为检查通过，但默认三维坐标轴尺度过大、相机中心使用错误字段，人工视觉验收未通过。已依原CameraStateSettings改用targetOffset，并将坐标轴缩到0.03；最终验收须绑定修改后的布局。

桌面保留五面板。手机使用同一底座的双面板布局，集中录像和阶段结果。新用户默认秒显示并折叠侧栏，原持久化偏好保持优先。

full-b仍有初始物体贴边，已将相机distance调到0.8m。mobile-a发现无viewport声明，CSS实际宽980px；该轮不计手机通过。已用原HtmlWebpackPlugin配置增加device-width，验收脚本明确核对实际390×844，并检查物体起点/持物/落定三处的完整可见边界。

最终 full-c 和 mobile-b 分别通过 11、9 项检查，根已目视核验截图。手机底部次要同步/速度选项有裁切；已验证的是录像、报告、播放暂停和阶段定位，不包括完整手机编辑。实际跨回合换源及实时连接留后续。


## 2026-10-20 现有执行器接入结论

旧GraspGenX full_cycle以冻结motion-plan/preflight为入口，不适合直接接受编辑草稿。现有 run_visual_grasp.run_physical_episode 已有RGB定位、IK/OMPL、物理控制和原评分，仅缺场景/进度/取消等注入点。本轮新增可选hook和薄station_executor，无需另写控制器，也没有引入内容哈希门锁。

FishBot coop-api的transport仍是车臂协同任务，不能替代SO101独立抓放。新 `/api/so101/` 适配只有本机CLI生命周期和产物读取，worker status.json是执行状态来源，未新增通用调度/认证平台。网页运行输入是独立快照；后续编辑不会修改已启动任务。

固定八步模板当前只支持方块XY各±10mm和50×56×130mm附加障碍。设计目标高度与执行器指间高度不同，运行能力描述明确映射；不支持的节点、世界位置、步骤重排和时长会具体拒绝。第一次新CLI释放后再接触失败，复用已有floor_yaw/28mm后新CLI及浏览器实际完整回合均通过，原物理阈值保持。
