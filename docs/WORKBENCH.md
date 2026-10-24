# FishBot 工作台

打开网页控制站的 `/workbench`，进入地图与巡逻工作面。`/simulation` 是同一工作面的兼容入口。`/` 为控制总览，`/radar` 为二维／三维只读观测，`/cooperation` 为车臂协同。最近成果及原评分移至 `/results`，左侧“成果验收”可达。

桌面使用 Dockview 分栏；手机使用画布与底部对象、属性、任务面板。关闭视图只释放视图资源，原任务 owner 保持。布局缓存只保存显示配置；刷新、切页和重建布局不派发运动。

选择航点后可编辑坐标和朝向；选择墙后可平移、旋转；禁区保持轴对齐并支持平移。修改先进入草稿，保存和发布仍需显式操作。规则草稿按标签页恢复；旧版本冲突必须核对，不自动覆盖服务端。三维扫描是雷达局部 XY 摘要，没有源 TF 时不会伪装成地图坐标点云。

## 能看什么

| 能力 | 已验证的收获 | 保留边界 |
|---|---|---|
| 地图与导航 | 选点、规则、路线、派发时捕获返航点、原生RViz | 后续验收限合成仿真；当前运行状态到操作页查看 |
| 车臂运输 | 同桥取消恢复与两轮完整运输，新三回合独立评分通过 | 使用ideal工位观测；不能补齐旧RGB失败 |
| RGB停靠 | 实际后向RGB、AprilTag/IPPE、观测/动作/物理分层评分 | 原56例为38完成、7正确取消、11失败，严格资格尚未全通过 |
| 空间场景生成 | 官方单例16实体，人工校正六墙后原FishBot CPU100步 | GT18实体；重建精度、起点净空与导航尚未验证 |
| 视频过程分析 | 单个CC0样本375解码帧、29采样、1候选事件和持久复核 | 不代表人数精度、身份、家庭泛化、RTSP或设备部署 |
| Arena组合评测 | L4预检20步、两组各23步、取证与回收链闭合 | zero_action两组success均false，不算抓放或训练提升 |

原56例明细可按全部、完成、正确取消、失败筛选。案例采用中文名称，原ID、原因和评分指纹保留。新增三回合单列，取消不计任务完成，旧失败不被新成功覆盖。

## 语音任务

成果验收页的“语音任务”跳到同页面板。先显式连接服务，再输入文字、上传音频或录音。转写只生成预览，核对意图和参数后点击确认执行。停止录音不会自动派发；页面失焦或离开会丢弃录音并关闭麦克风。任务取消绑定原ID，原生动作终态与停稳反馈分别判断。

该面板默认绑定独占仿真域121，可通过服务器 profile 指定已启动服务的实际域，不改六项冻结成果。首次打开没有自动请求或写操作；只有用户主动操作才连接或提交。真实ASR、启动配置、未配置回充和验收边界见[语音入口](VOICE.md)。

## 人工控制

控制总览从当前mission服务读取人工控制能力。仅`passage_manual`运行配置提供租约式按住行驶；未启用时显示原因，不改走旧Java速度接口。键盘控制需显式开启，只作用于控制区域，输入框不触发行驶。

松手、失焦、隐藏或离开页面会释放当前手势。服务端还会独立检查命令有效期。明确停止绑定原任务与控制权，解除后仍需新的显式操作。页面分别显示发送回执、控制权、守卫清理和连续静止，不用“HTTP成功”代表车已停住。

人工控制与导航使用同一执行环境；兼容控制站的旧遥测折叠为独立来源，不作为当前人工动作反馈。完整合同与验收入口见[运行合同](RUNTIME_CONTEXT.md#人工控制合同)。

## 快照与当前入口

`frontend/public/workbench/recent-results.json` 是唯一经过审定的成果快照源。页面直接读取它，网页和手机可下载同源JSON。数据绑定冻结日期、来源版本、原报告及59份评分指纹；不包含本机绝对路径、地图、媒体、原始日志或凭据。未来更新必须回源报告审定，不按页面“成功”或进程退出码改判。

“检查本机工具”仅发GET。Vite开发/预览代理固定映射到SpatialLM `/api/health` 与视频 `/api/run`；响应身份、闭合运行状态、HTTP拒绝和连接失败分别显示。初始未检查，不自动轮询，不启动服务、推理、导出、审批或ROS任务。显示的是上次检查时刻，不是持续心跳。代理透传HTTP方法；只读检查由页面GET与上游只读路径共同约束，不宣称代理层强制GET。

编辑器与复核台继续在原页面处理导出和审批。两者只绑定电脑loopback；手机的localhost指手机自身，因此不开放错误的本机直链。当前前端若部署到其他服务器，需显式配置这些只读代理；快照无需依赖分析服务在线。

## 配送回归与只读双轨迹

`/regression`读取两次真实回合的配送投影。左右共用原世界坐标、源时间锚点和显示边界；Ghost不平移轨迹，缺帧处断开。货物中心与机械臂关节投影来自保存数据；原任务、episode、检查点和原生Goal终态可展开核对。失败、未知与保护介入分别保留，不从回放画面重新判分。

复用原耗时导入器生成私有摘要；在项目根、已有规划Python环境运行：

```bash
python -B tools/cooperation_comparison.py \
  --run /absolute/private/run-a --run /absolute/private/run-b \
  --label 基线 --label 候选 --group baseline --group candidate \
  --output /absolute/private/new-comparison
```

命令只读原记录，在独立目录生成`comparison.json`、可重建SQLite与10Hz展示流。通用日志回放仍在既定Lichtblick工作台；此页只处理配送对齐和证据投影，不接ROS动作。

前端开发/预览服务通过`FISHBOT_REGRESSION_REPORT=/absolute/private/comparison.json`选择该文件。默认读取`~/.cache/fishbot/continuous-twin/latest/comparison.json`。`/workbench/continuous-comparison.json`仅允许GET，浏览器不能选择服务器文件路径。也可直接导入8MiB以内的本地JSON；404或语法错误保留已有报告。

该页面不派发实验。正式矩阵编辑、原owner派发、5+5与留出/完整回验仍按[连续孪生计划](../plans/continuous-twin-regression-20261024/task_plan.md)推进；当前两次R2原参数路线均未通过，不能把对照页验收当成配送成功。原始记录与详细轨迹默认本地保留，不随代码公开。

## 启动与验证

条件：已安装项目现有Node/npm依赖，端口空闲。从前端目录启动：

```bash
FRONTEND_PORT=5180 npm run dev -- --host 127.0.0.1 --strictPort
```

工作台入口为 `http://127.0.0.1:5180/workbench`，成果入口为 `/results`。成果区的历史工具地址为场景编辑器 `http://127.0.0.1:8867/` 和视频复核台 `http://127.0.0.1:18089/`；是否在线由显式检查确认。启动原工具分别见 [SpatialLM](../experiments/spatiallm/README.md) 与 [视频仓库使用说明](https://github.com/qiaoqiao2521/uw-yolo-code-assets/blob/908f5bd8e40241bb74ec1bf384205c638edf7b1d/docs/OFFLINE_VIDEO_EVENTS.md)。语音仿真使用独立配置，见[启动说明](VOICE.md#启动)。

前端运行 `npm test`、`npm run typecheck`、`npm run lint`、`npm run build`。项目 `./fishbot.sh check-feedback` 已纳入工作台数据与页面合同。实际桌面/390px只读QA验证过滤、五区导航、同源快照、两个本机页面与零写请求；记录在项目外缓存，具体进度见 [本轮计划](../plans/workbench-harvest-20261015/progress.md)。

## 配置与重构验收

需要选择服务时，从前端目录使用服务器配置启动：

```bash
FRONTEND_PORT=5182 \
FISHBOT_WORKBENCH_PROFILE=/absolute/private/workbench.json \
npm run dev
```

先按 [示例](../apps/fishbot-control-station/config/workbench.example.json) 填写实际服务端口和 domain。端口必须互不冲突；所有代理目的地固定为 `127.0.0.1`。运行身份仍由各服务读回，不用配置值冒充发现结果。该命令只启动网页，不启动仿真或发送动作。

需要试验新的人工控制时，在项目根用独占domain和全新输出目录启动：

```bash
fishbot_manual_run="$HOME/.cache/fishbot/manual-$(date +%Y%m%dT%H%M%S)-$$"
FISHBOT_MUJOCO_DOMAIN_ID=129 ./tools/fishbot_mujoco.sh headless \
  nav:=true bridge:=true bridge_port:=9097 web_port:=5182 \
  control_profile:=passage_manual manual_output_dir:="$fishbot_manual_run"
```

将网页profile中的mission设为端口9097/domain129。启动器先检查domain为空，再生成一次性参数和身份；已经消耗的输出目录不能用于接管旧任务。启动不派发动作。通过页面读回运行实例和能力后，才显式按住行驶或派发任务。该配置的整组实测完成状态以本轮进度为准。

新工作面已完成真实导航、返航、原任务恢复和同实例两轮运输。硬件生产浏览器的100ms交互与30分钟长测已通过；人工控制八项和文字语音预览、确认、原UUID取消四项也已通过。文字语音验收不计ASR精度。实验ROS实例已清理；运行新任务需显式启动匹配环境。不把当前结果写回旧冻结快照。三维生命周期和真实ROS验收见 [重构进度](../plans/workbench-rebuild-20261018/progress.md)。旧成果和旧失败保持原判定。前端合同、真实导航和独立物理评分分别记录，不能相互替代。

## 本机可选的 DDS 启动配置

在项目根执行。以下配置只影响本命令环境，不改网卡、路由器、VPN或系统ROS安装。首次解包使用固定官方包；缺包或哈希不符会失败，不自动换版本。版本与来源见[依赖说明](DEPENDENCIES.md)。

```bash
fishbot_dds_prefix="$HOME/.cache/fishbot/dds-cyclone"
python3 tools/fishbot_mujoco_bootstrap.py \
  --runtime "$fishbot_dds_prefix" \
  --packages-file tools/config/fishbot_cyclonedds_packages.json --no-link
export FISHBOT_MUJOCO_DOMAIN_ID=129
source tools/fishbot_mujoco_env.sh
export AMENT_PREFIX_PATH="$fishbot_dds_prefix/opt/ros/jazzy:$AMENT_PREFIX_PATH"
export LD_LIBRARY_PATH="$fishbot_dds_prefix/opt/ros/jazzy/lib:$fishbot_dds_prefix/opt/ros/jazzy/lib/x86_64-linux-gnu:$fishbot_dds_prefix/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$PWD/tools/config/fishbot_cyclonedds_localhost.xml"
export ROS_STATIC_PEERS=''
fishbot_manual_run="$HOME/.cache/fishbot/manual-$(date +%Y%m%dT%H%M%S)-$$"
ros2 launch fishbot_mujoco sim.launch.py ros_domain_id:=129 \
  nav:=true bridge:=true bridge_port:=9097 web_port:=5182 \
  control_profile:=passage_manual manual_output_dir:="$fishbot_manual_run"
```

需要语音时，在同样的命令环境另行显式启动`fishbot_voice_bridge.py`，使用domain129、mission9097与voice9099。工作台profile也须匹配这些端口和domain。进入网页、刷新或读回回执不会自动启动ROS或派发动作。
