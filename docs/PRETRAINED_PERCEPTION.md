# 预训练感知接入

目标：用相机观测替代任务中的理想观测，继续复用 Nav2、SO101 的 mink/OMPL 和原独立物理评分。复用官方预训练推理，不新建训练平台或大批量故障面板。2026-10-31 已完成实际官方推理、模型驱动抓放和同一世界完整 ROS 视觉 B→A；两单独立物理/业务评分及原记录重算均通过。该结果限以下固定工位仿真范围，状态见当前 SpecMesh。

## 当前能力

`cooperation_prepare.py` 增加 `--camera-rgbd`。将它追加到原准备命令，并使用新的输出目录。开关只增加传感器，不改变 `station_perception.mode`；ideal 仍明确是 ideal，不会被相机开启伪装为视觉控制。默认不增加深度渲染。

| 输入 | ROS 接口 | 约定 |
| --- | --- | --- |
| 彩色图像 | `/cooperation/camera/image_raw` | `sensor_msgs/Image`，rgb8，640×480 |
| 配准深度 | `/cooperation/camera/depth/image_raw` | `sensor_msgs/Image`，32FC1，米制 optical Z；NaN 表示无效/远裁剪背景 |
| 内参 | `/cooperation/camera/camera_info` | CameraInfo，与彩色/深度共用光学坐标及采样时间 |
| 安装外参 | `/tf_static` | base_footprint → cooperation_camera_optical_frame，从当前车型编译后的 MJCF 求相对刚体变换 |
| 来源 | `/cooperation/camera/frame_metadata` | 原 scene/episode/sequence、源时间和渲染耗时；不发布 qpos、货物或相机世界位姿 |

两幅图使用同一物理快照。RGB 保留原 2 倍超采样＋BOX；深度独立原生分辨率渲染，不平均前景和背景距离。复用原最新单槽和墙钟最高 20Hz，慢渲染丢弃待处理旧帧；不保证实际 20Hz。MuJoCo 本身已返回米制 Z，不再线性化或转换毫米。

浮点深度无效值遵循 [ROS REP118](https://www.ros.org/reps/rep-0118.html)；若某模型要求无效值为0，在该模型输入边界转换，不能改变标准ROS流。

这是理想针孔 RGB-D 仿真传感器，尚无真实深度噪声、反光/透明缺测模型。车载流沿用后向停靠相机及原 AprilTag 夹具；它不保证货物完整可见。工位抓取另用下述固定斜视 RGB-D 相机。标记可见不等于抓取模型已使用它，停靠与抓取输入分别记录。

## 已有实现优先

- SO101 `experiments/colab-twin/position_ik.py` 已使用 mink；碰撞与路径复用原 OMPL。SO101 为五轴臂＋夹爪，不能承诺任意六维姿态可达。
- SO101 `experiments/graspgenx-demo/README.md` 记录官方 GraspGen-X 候选、预训练评分器和原 IK/OMPL 的固定方块完整抓放成功。该输入是完整物体几何上界；不是可见点云、泛物体或配送成功。优先扩展此现有链路。
- 2026-10-30 环境曾缺失；2026-10-31 已恢复原缓存入口并实际推理。官方代码 `b9429097728cb1c430dd78b92edf17ba318aad03`、模型 `7c834043c11a11417e31d6d5ea9355801e40a2c1`；权重不入 Git。
- FoundationPose 是已知 CAD/首帧掩码的位姿路线。官方 `register(K,rgb,depth,ob_mask)` 与后续跟踪可复用，优先评估官方 Isaac ROS 组件，不另造模型服务。它不是抓取规划器。
- openpi 提供预训练策略和官方远程推理。官方推理显存要求 >8GB，本机 RTX3050 为4GB；本体、相机键、归一化和动作头还需与 checkpoint 匹配。LeRobot 支持 SO101 硬件，不等于所有 VLA 权重支持本任务零样本。

当前 SO101 固定在工位，J100 独立移动。保留 Nav2 到站＋机械臂局部规划的协同，不能把两者假定为固定连接的一棵运动链。可复用任务逻辑，也仍需核对夹爪开口、可达范围和车型交接高度。

## 工位视觉抓取模式（2026-10-31）

在原命名实体 `--continuous-delivery` 准备命令追加：

```bash
--pretrained-grasp-config tools/config/perception/pretrained-grasp.example.json
```

从仓库根执行；配置中的相对路径按当前工作目录解析。模板复用现有 GraspGen-X 环境与权重路径。Python 路径必须保留 venv 的符号链接，不能解析为基础 Python；否则会丢失 venv 包环境。默认输出为该场景目录下 `grasp-observations`，每次查询只保留一份输入 RGB、米制深度、掩码、可见点云、标定、候选和报告，不录高频 RGB-D 视频。

准备器为装货及卸货机械臂配置固定斜视相机。选区使用**已声明的绿色货物先验和固定库存槽位**；不是开放词汇识别。目标身份来自订单与槽位配置；同槽中的多个相同颜色目标尚无独立身份识别。感知输入只使用 RGB、深度、标定和夹爪描述，不使用 MuJoCo segmentation ID、目标真位姿或完整货物网格补点。物理快照仅由独立渲染生产器使用，模型子进程不接收它。

官方 GraspGen-X 使用 Z 向上点云，因此先用固定工位外参转换输入，再把全部候选变回相机系。最终经相机标定送入原 mink/OMPL；所有 diffusion／OBB 候选与分支、预训练判别分均保留。分数不是物理成功概率，选中 OBB 分支也不能写成纯神经生成成功。

SO101 的公开机械 `PINCH_POINT=(.006,0,-.094)` 不在手掌原点轴上。项目的 `so101-graspgenx-tip-region.json` 将模型原点放在同一夹持中心轴：两个描述 offset_x 均减 `.006`，extents 和 fingertip_depth 不变；其 `T_body_model` 同时用于模型评分和 IK 边界逆变换。不能只平移旧候选后沿用原分数。该描述是声明的仿真接触区域，不是硬件标定或最大张口认证。

候选筛选同时核对声明的放货终点IK及完整开爪扫掠，仍保持官方候选排序、姿态和判别分。开爪复用原六关节配置扫掠，保留1mm碰撞余量及原`.005rad/.002rad`臂／夹爪采样；闭合和全开端点合格不能替代中间角检查。该接纳不代表整条载物路径或动态夹持成功。实际搬运从最新双指抓持快照读取夹爪方向，用既有mink保持该方向，再逐段执行原载物碰撞检查，并在实际抓持姿态下复核放货末端开爪；旧ideal模式继续使用原竖直／零腕角IK。预训练候选可能含大腕角，直接接入旧零腕角搬运器会发生姿态突变。松爪后先沿原下降段竖直清离，再经原OMPL回位，不能用几何回执替代托盘／货架支撑和最终交接评分。

视觉持货段 `lift/transport/lower` 沿同一规划路径推进。若接收或发送漏掉周期，不按已流逝源时间一次追赶；每次推进最多为原 `.3rad/s × min(源间隔, .02s)`。重复源帧不推进，实际参考到达末端后再计算原dwell；原段时限和整单预算不变。任务中的 `arm_reference_pacing` 记录受限次数、最大源间隔与实际参考步长。它是执行节奏诊断，不是物理成功评分。

视觉分支的无载接近先复用现有 `validate_joint_path` 验证实际起点到pregrasp的直达关节边，采样仍为`.005rad`、碰撞余量仍为1mm；通过时使用同一对端点与原时标，未通过才回退原RRTConnect。报告 `planner=validated_direct_joint_edge` 与 `direct_approach` 区分两种路径来源。此优化不改变持货路径、放货位置、速度上限或最终清理确认期限。

启用此模式时，ROS launch 复用官方 `GraspGenXZMQServer`，只监听回环地址，端口为本轮 API 端口加 1000。服务随同一 launch 启停；多次抓取共享权重，原每次接近查询总期限仍为 30 秒。推理失败、看不到目标或无可执行候选均明确失败，不回退理想目标。默认未启用时保持原模式。

推理报告的 `physical_grasp_verified=false` 保持原义：模型进程没有执行或评分物理动作。实际抓放是否通过看原Factory订单和独立Oracle，不能回填模型分数或把推理完成当作物理验收。当前工位路线以竖直下降收尾；非竖直／单点自定义退让仍未通过该视觉分支验收。报告中的旧 `kind=upright_cartesian_ik` 保持兼容，实际朝向策略以 `orientation_policy` 为准。

边界：RGB 标记只接管工位精停靠，Nav2 仍使用地图、激光和定位。视觉模型接管抓取目标；原碰撞规划、载货接触测量和后续放货规划仍复用既有物理反馈与已知场景几何。它不是端到端 VLA、无真值的全流程控制，也不证明真机或 sim-to-real 成功。

## 复用宽场景运行入口

复用 [J100宽场景准备命令](FACTORY_DELIVERY.md#j100-宽场景2026-10-28)，在同一 `prepare` 命令追加以下参数，再执行原 `f1_candidate.py` 配置步骤：

```bash
--perception-config tools/config/perception/apriltag-station.example.json \
--pretrained-grasp-config tools/config/perception/pretrained-grasp.example.json
```

这两项分别启用真实RGB标记停靠和工位RGB-D模型抓取，不能只开相机后仍使用ideal停靠。公开AprilTag配置与本轮实际运行设置相同。保留原GraspGen-X环境和模型缓存；缺失时按SO101既有 `experiments/graspgenx-demo/README.md` 恢复，不另建第二套训练环境。

从新输出目录派发原连续订单；`FISHBOT_NAV2_QUERY_OVERLAY` 指向已构建的原生补丁安装目录，恢复方法见原配送文档。使用独占domain和空闲API端口；模型服务会占用API端口加1000。

```bash
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PWD/tools:/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
export MUJOCO_GL=egl
"$FISHBOT_COOP_PYTHON" -B tools/cooperation_factory.py run \
  --manifest "$scene_out/scene-manifest.json" \
  --output "$HOME/.cache/fishbot/vision-delivery-next" \
  --domain 176 --port 9146 --publication-mode asynchronous \
  --continuous-deliveries tools/config/factory_delivery/continuous-ba-orders.json \
  --order order-b --order order-a --scope transport
```

不要重复使用已有运行目录。Factory保留原任务身份、两个独立货物、同一世界和原评分；失败不会自动重发。需要用户systemd保护快照时，沿用当前登录会话的 `XDG_RUNTIME_DIR` 与 `DBUS_SESSION_BUS_ADDRESS`，不修改网络或旧实例。

## 本轮验收（2026-10-31）

K/run `a7264eae-5138-4ee7-9e14-1a727d550d57`，独占domain176/API9146。J100＋3D雷达、三个固定SO101工位、两件独立自由货物在同一world/episode完成B→A；2start、0reset、0cancel。整轮958.277墙秒，原配置为每单装运360秒＋卸货180秒、路线120秒、整轮1360秒，均未改动。旧ideal成绩和A–J失败保留。

| 订单 | 路线墙秒 | 最终XY误差 | 最终yaw误差 | 命名原物理／业务评分 | 离线重算 |
| --- | ---: | ---: | ---: | --- | --- |
| B／cargo_1 | 49.902 | 31.065mm | .001365rad | 通过／通过 | 一致 |
| A／cargo_2 | 20.968 | 21.215mm | .014968rad | 通过／通过 | 一致 |

四次实际RGB-D输入分别为312/226/291/227个可见点，官方每次完整产生48个diffusion＋360个OBB候选。最终选择51/85/87/61，均为OBB分支并经预训练判别器评分，不能写成神经生成分支成功。实际GPU推理约.50–1.10秒，RTX3050 Laptop峰值分配约584.3MiB，训练步数0；整个查询还包含模型/场景初始化、候选机械接纳与规划，不能用推理时长代替查询总耗时。

独立评分覆盖实际双指抓取/抬升、托盘释放/完整足迹支撑、清离/home、同一货物运输、目标停车、卸货抓取/货架释放和清理后的新帧确认。两单命名投影均通过原K。兼容字段 `original_k_oracle_passed` 仍固定观察主货物cargo_1，因此A的旧主货物诊断为false；A实际搬运cargo_2，验收读取独立命名投影与业务评分，保留旧诊断、不将它改成true。

停车plant guard分别介入.80/.74源秒；B/A物理序号缺227/28，最大源间隙.34/.06秒，未插值补帧。观测质量、原生动作和物理评分保持分层；本轮通过不代表零缺口、纯视觉停车精度、长期稳定、任意物体或真实sim-to-real成功。全部owned进程/端口清理完成，选定源码及输入起止一致。原记录入口和恢复方式见[本轮进度](../plans/continuous-twin-regression-20261024/progress.md)。

## 行为切片与验收顺序

1. 恢复已有 GraspGen-X 官方环境/权重，先核对存储位置和容量。复用原 setup，不并建 FoundationPose、VLA 多套环境。
2. 为抓取配置能看到取货台的固定 RGB-D 视角；验证标定和目标可见性。当前后向相机只完成共用输入能力。
3. 用图像分割或显式人工选区生成可见目标点云，再调用原官方候选生成/评分。禁止用 MuJoCo 分割 ID、物体真位姿或完整目标网格补成“视觉输入”。首帧人工掩码需在结果中标明。
4. 将相机系候选经标定/定位变换交给原 SO101 可达性与 OMPL 筛选；执行同一自由货物抓取、抬升、释放、回位。观测、候选、原生动作、物理结果分别记录。
5. 单次真实视觉抓放通过后，再以视觉观测进入原 B→A owner；保留旧理想基线和停车保护介入记录。

不把模型评分解释成成功概率，不保证零样本成功或10–20条微调样本足够。模型缺失时明确 unavailable，不能用理想姿态回退并报告视觉成功。

## 定向验证

```bash
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PWD/tools:/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
MUJOCO_GL=egl ~/.cache/so101-colab/planning-venv/bin/python -B tools/tests/native_cooperation_rgbd.py -v
/usr/bin/python3 -B -m unittest tools.tests.test_cooperation_camera tools.tests.test_cooperation_prepare -q
```

原生检查验证 Z 深度、背景、实际 ROS 消息序列化、同快照 RGB-D、默认 RGB-only、车型相对标定及 J100 prepare/render。它不证明 DDS 消费、模型推理或配送成功。临时场景由 TemporaryDirectory 回收，不存逐帧 RGB-D 日志。

## 官方依据

- [GraspGen-X](https://github.com/NVlabs/GraspGenX)：复用既有官方推理与夹爪描述。代码和权重各自遵循上游许可。
- [FoundationPose](https://github.com/NVlabs/FoundationPose)、[官方示例](https://github.com/NVlabs/FoundationPose/blob/main/run_demo.py)、[Isaac ROS 位姿组件](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_pose_estimation)。
- [mink](https://github.com/kevinzakka/mink)、[openpi](https://github.com/Physical-Intelligence/openpi)、[LeRobot SO101](https://huggingface.co/docs/lerobot/so101)。
