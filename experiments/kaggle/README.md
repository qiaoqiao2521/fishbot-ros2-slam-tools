# F1 私有 Kaggle 运行入口

复用原 Jazzy、MuJoCo、Nav2、SO101 和 `tools/cooperation_factory.py`。
本入口只适配云端依赖与启动，不增加控制器、训练流程或新评分器。

2026-10-24 已运行私有 CPU 前检。该回合是 Ubuntu24.04/glibc2.39、
4核配额、约31GB可用内存、默认Python3.13，未安装ROS/MuJoCo。
本机UDP成功；ROS仓库HTTPS出现证书主机名不匹配，未禁用TLS验证。
这些是单次环境观测，不保证后续Kaggle分配相同资源。

- `f1_environment.py`：只读环境报告，`task_acceptance=false`，零Goal/任务。
- `pack_f1.py`：打包当前Jazzy安装、既有vendor runtime、Git版F1源码、
  SO101规划依赖闭包与模型。保留许可证，排除历史输出和认证配置。
  解引用vendor runtime目录链接，避免上传指向本机的空链接。
- `f1_candidate.py`：重建未验收候选。保留原加减速、局部碰撞配置和评分；
  载货上限`.06m/s/.10rad/s`，全局规划padding为候选`.025m`。
- `f1_compute.py`：零Goal有限实录状态消融；分别记录物理、IMU、实际scan与点云等价，
  原生步与Python包装剖析分列，始终`task_acceptance=false`。
- `f1_capacity.py`：独立ROS观察者，22墙秒静止，读回源时钟/scan/16×360点云/IMU，
  不发布运动；容量结果不代替完整任务。
- `f1_run.py`：在临时Kaggle环境安装Python3.12，显式绑定上传ROS CLI和
  venv内colcon的解释器。独立构建原1.3.13的Smac缓存和源时钟平滑补丁，
  运行原生时钟用例、原prepare和原factory的B→A。

## 使用

先在本机生成新的私有包目录；不要上传整个SO101实验目录。

```bash
python3 experiments/kaggle/pack_f1.py \
  --so101-project /absolute/so101 \
  --output /absolute/private/f1-dataset
cp experiments/kaggle/f1_candidate.py /absolute/private/f1-dataset/
```

用官方`kaggle datasets init/create`生成并上传私有数据集。
保留依赖原许可证；元数据使用`other`，不把第三方代码改授CC0。
在description写明第三方组件保持原许可证。
数据集必须包含四个`*.tar.gz.bin`包、`bundle.json`和`f1_candidate.py`。
打包器在原tar/gzip前增加19字节格式头，避免Kaggle自动展开运行库；
云端用标准tarfile解包，保留原执行权限和符号链接。此封装不加密、不锁定内容。
云端factory显式使用`--isolated-runtime`，不查询本机历史systemd演示服务；
记录空保护对象范围，不能声称原107/114在云端仍运行。本轮原任务与owned清理评分保持。
部署程序与输入可使用标准Kaggle kernel metadata：`kernel_type=script`、
`code_file=f1_run.py`、`is_private=true`、`enable_gpu=false`、
`enable_internet=true`，`dataset_sources`绑定自己的私有包。
调用官方`kaggle kernels push -p DIR -t 3600`，其中3600秒包含部署构建，
不会扩大原路线120秒、单单360秒和整轮1000秒的评分期限。

任务输出为`f1-deployment.json`、逐阶段日志以及
`f1-results-*/full-run/result.json`和原独立oracle报告。
源码、venv和编译树只放临时`/tmp`，不让Kaggle把依赖树保存成任务输出。
只按原factory的最终物理结果报告配送；提交、构建和网页状态均不替代验收。
本轮旧载货初态和独立overlay缓存已丢失，因此新包是重建候选，
不宣称与已删除输入完全相同，也不拼接历史成功。

账户元数据、认证、运行时库、模型包与原始日志留在私有目录；不进入Git。
本轮交接目录：`~/.local/share/fishbot/cloud-jobs/kaggle-20261024/`。
现有项目计划维护任务状态；不新增调度器或常驻Web服务。

来源：[官方Kaggle CLI](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md)、
[kernel metadata](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md)。

显式设置`FISHBOT_OMIT_UNUSED_NATIVE_RANGEFINDERS=1`时，prepare只省略合作驱动
未消费的legacy laser/laser_ray声明，默认保持。实际10Hz二维/三维射线、IMU、
500Hz物理、完整碰撞与原时限不变；该模式在完整任务前执行held ROS容量检查。
输入数据集比源码旧时，允许在私有Kaggle脚本中用`FISHBOT_SOURCE_OVERLAYS`
显式附带更新文件原文。输出`source-overlay.json`与原文记录基础commit/文件，
不宣称数据集本身已更新。compute模式用`FISHBOT_KAGGLE_SCOPE=compute`，
单文件Kaggle脚本可嵌入`COMPUTE_WORKER_SOURCE`与`COMPUTE_FIXTURES`；
完整模式可嵌入`CAPACITY_WORKER_SOURCE`。这些都复用原控制与评分入口。

2026-10-24 原v6/v7完整任务均未交付，不把部署或静止测试算配送通过。
`f1_terminal_stop.py`用同版原生平滑器和实录初态比较旧输入与新的终态零目标，
分别保存时戳拒绝、50Hz/500Hz接触和停稳；零导航Goal，不称完整任务回放。
`terminal_stop_heartbeat=true`只允许原Goal status4后的当前owner等待停稳阶段，
每个新物理帧向原`/cmd_vel_nav`发新的全零目标。保留旧非零指令的源时龄/episode检查、
原减速度和失败立即hold；不统一刷新移动命令的时间戳。

`f1_capacity.py MANIFEST OUT full [DOMAIN PORT]`启动原完整栈、只GET就绪，
采样22墙秒并记录owned进程CPU与清理；默认域144/9114，可显式隔离。
该短测没有原完整运输observer和活动规划负载，不能承诺真实任务实时率。
`FISHBOT_FULL_STACK_CAPACITY=1`让新完整实验先执行这个更完整的容量检查。
`FISHBOT_REUSE_NATIVE_INSTALL=1`尝试使用显式输入的唯一`native-install.tar.gz`；
仍需同1.3.13/未改原生补丁和真实原生校验，缺失时WARNING后正常重建。
本轮失败kernel作为输入被服务端拒绝，未宣称云端复用已经成功。

完整ROS静止检查仍不包含活动规划和原业务observer；必要时同时启动原oracle，
使用空marker明确零业务，独立确认采集完整，不能把其业务false当作配送失败或通过。
非交互ROS launch的停止请求只送launcher，由其原生转发；仍用原owned PID/starttime
核对全体子进程退出。原组信号导致的销毁中断保留为失败记录，不忽略finalization错误。

`FISHBOT_STAGING_REVERSING=1`显式复用prepare的倒车进场组合，默认关闭。
当前重建J100候选的B进场为`(1.35,-2,0)`，最终B仍为`(.7,-2,0)`。
本机载货短路线已在原120秒内完成105.794秒；这是路线分项，不是云端完整配送成绩。
云端v6/v7失败、`.95m`进场失败及其余开发候选均保留；完整B→A另由原factory评分。

原始出生点完整e未复现上述路线分项，1.35进场在120秒取消，A未执行。
`FISHBOT_TRANSPORT_CONTROLLER=graceful`显式复用Nav2 1.3.13的
RotationShim＋Graceful及下述原生补丁；默认仍为RPP，不另写控制器。
`graceful-j100.yaml`只替换FollowPath，StagingPath/checker/物理保持；
原载货平滑器的`.06/.10`和`.025/.05`加速度门槛保持。
Graceful自身最大线/角速`.06/.055`、降速范围`.12m`。
新prepare复制YAML并记录来源，移除不适用的RPP速度ACK，保留共享progress。
也可用`f1_candidate.py MANIFEST --transport-controller-yaml PATH`显式传入原生配置。
旧`.06`载货短测118.615秒通过，但原始出生点完整f触发底部接触保持失败，A未执行。
`.065`、`.08/.10m`、预测参数对齐和完整位姿模式的失败分别保留，未晋级默认。
当前`.055`＋可选原生yaw-stop短测119.637秒通过，余量仅.363秒；
尚不能据此宣称完整两单、稳定性或云端配送完成。实际状态见原SpecMesh。

## 显式配送任务输入

可选`FISHBOT_F1_FACTORY_CONFIG`指定任务JSON，相对路径从FishBot根解析。
未设置时保留既有进场`(1.35,-2,0)`；设置后完整保留输入，不再覆盖进场姿态。
仍由原prepare校验场景，由原factory、Nav2与独立oracle执行和评分。

```bash
export FISHBOT_F1_FACTORY_CONFIG=tools/config/factory_delivery/line-side-j100-tangent-040.json
export FISHBOT_TRANSPORT_CONTROLLER=graceful
```

该有限候选把B进场改为`(1.35,-1.868238476919363,.4)`，与倒入原B的
圆弧切向相接；原A/B、占用体、默认出生点、物理与预算保持。
H装货后重建初态短测两原Goal成功，117.1158秒、末28.258mm/.005142rad，
仅证明路线分项，余量2.884秒。完整H仍失败，当前须从原默认起点重跑I两单。
Kaggle需新源码包或显式source overlay；该输入选择不代表已在云端完成任务。

## StoppedGoalChecker 与末端制动

`tools/patches/nav2-1.3.13-rotation-yaw-stop.patch`面向官方
[1.3.13 源码](https://github.com/ros-navigation/navigation2/tree/1.3.13)，
实际tag commit为`f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501`，保持Apache-2.0许可证。
它增加默认关闭的`stop_in_goal_yaw_tolerance`。只在原checker返回的pose容差内
请求零角速，保留原旋转碰撞检查；原StoppedGoalChecker仍须等待真实停稳。
J100候选仅对FollowPath显式启用，StagingPath与旧默认不变。

`FISHBOT_TRANSPORT_CONTROLLER=graceful`在同一1.3.13源码上应用该补丁，
同时应用下述距离补丁，构建追加`nav2_rotation_shim_controller`和
`nav2_graceful_controller`。复用旧native缓存时保留原Smac/平滑器，
再独立构建这两个包，不把参数声明当作补丁已生效的证明。
本机已执行原生反例、补丁后11项上游/新增测试及实际加载路径读回。
云端还需用最新源码包或显式source overlay；旧数据集不会自动获得新文件。

手工构建可在独立Nav2 1.3.13树执行：

```bash
git apply /absolute/fishbot/tools/patches/nav2-1.3.13-rotation-yaw-stop.patch
git apply /absolute/fishbot/tools/patches/nav2-1.3.13-rotation-position-namespace.patch
git apply /absolute/fishbot/tools/patches/nav2-1.3.13-graceful-path-distance.patch
colcon build --packages-select nav2_rotation_shim_controller nav2_graceful_controller \
  --allow-overriding nav2_rotation_shim_controller nav2_graceful_controller \
  --cmake-args -DBUILD_TESTING=ON
```

复用已有planner/smoother overlay并核对实际加载路径；不覆盖系统安装。
新增原生测试在`test_shim_controller`的`optInYawBandStopRetainsStoppedChecker`，
同时验证默认旧行为、容差外旋转与“请求停止仍不等于native成功”。

## Graceful 裁剪路径的终点距离

`nav2-1.3.13-graceful-path-distance.patch`保留同版Apache-2.0实现，
只为原终点距离补上机器人到裁剪路径首点的距离。原实现中，单点路径的
内部长度为零；两点残段也可能短于容差，即使车辆仍离目标较远。
原生反例固定1.5cm容差、首点距车3cm，旧实现提前旋转且线速度为零。
补丁后继续平移，原GoalChecker仍拒绝提前成功；容差内旋转保持。
20项控制器和5项坐标测试通过，原型测试在
`test_graceful_controller`的`prunedPathStillHasRobotToFirstPoseDistance`。
这只证明原生边界修复，真实载货路线和完整配送仍须独立验收。

## Shim 位置检查器的命名与当前判定

`nav2-1.3.13-rotation-position-namespace.patch`只把插件名赋值提前到
位置检查器初始化之前，保留同版许可证。旧版初始化时插件名为空，
实际参数是`.position_checker.stateful`，声明FollowPath下的同名参数不生效。
先应用yaw-stop补丁，再应用该补丁；两者仍构建同一个Shim包。

显式J100候选设置`FollowPath.position_checker.stateful=false`，与原外层
StoppedGoalChecker一致：减速后漂出15mm范围时，重新交给原控制器修正XY。
StagingPath默认true保持；不能用空前缀参数同时改动两个阶段。
原生反例先失败，补丁后12项Shim测试通过，包括10mm进入、19mm退出。
运行时须逐项读回FollowPath、StagingPath与原外层的值，空响应不是成功。
