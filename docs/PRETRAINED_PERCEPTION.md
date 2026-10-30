# 预训练感知接入

目标：用相机观测替代任务中的理想观测，继续复用 Nav2、SO101 的 mink/OMPL 和原独立物理评分。先跑一个真实视觉抓放回合，不新建训练平台或大批量故障面板。

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

这是理想针孔 RGB-D 仿真传感器，尚无真实深度噪声、反光/透明缺测模型。当前沿用后向停靠相机及原 AprilTag 夹具；它不是工位俯视或腕部相机，不保证货物完整可见。标记仍可见不等于新模型已使用它。旧 RGB 停靠继续独立保留。

## 已有实现优先

- SO101 `experiments/colab-twin/position_ik.py` 已使用 mink；碰撞与路径复用原 OMPL。SO101 为五轴臂＋夹爪，不能承诺任意六维姿态可达。
- SO101 `experiments/graspgenx-demo/README.md` 记录官方 GraspGen-X 候选、预训练评分器和原 IK/OMPL 的固定方块完整抓放成功。该输入是完整物体几何上界；不是可见点云、泛物体或配送成功。优先扩展此现有链路。
- 2026-10-30 原 `~/.cache/so101-graspgenx/upstream/.venv` 与 `models` 路径均不存在。原脚本和来源保留；不能称当前推理已可运行。
- FoundationPose 是已知 CAD/首帧掩码的位姿路线。官方 `register(K,rgb,depth,ob_mask)` 与后续跟踪可复用，优先评估官方 Isaac ROS 组件，不另造模型服务。它不是抓取规划器。
- openpi 提供预训练策略和官方远程推理。官方推理显存要求 >8GB，本机 RTX3050 为4GB；本体、相机键、归一化和动作头还需与 checkpoint 匹配。LeRobot 支持 SO101 硬件，不等于所有 VLA 权重支持本任务零样本。

当前 SO101 固定在工位，J100 独立移动。保留 Nav2 到站＋机械臂局部规划的协同，不能把两者假定为固定连接的一棵运动链。可复用任务逻辑，也仍需核对夹爪开口、可达范围和车型交接高度。

## 下一行为切片

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
