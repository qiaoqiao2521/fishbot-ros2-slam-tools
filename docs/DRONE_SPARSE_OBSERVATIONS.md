# 现有方法选型与只读稀疏观测

本阶段选择EGO＋PX4作为现有执行基线，MINCO S4NU保留离线制动候选。稀疏测距只作旁路观测，尚不驱动飞控。
目标是复用现有实现得到接近的可观察能力，不要求同款网络、硬件或原版权重。

## N0选择

| 方法 | 本机已有实现与来源 | 本阶段选择与边界 |
| --- | --- | --- |
| PX4＋MAVSDK＋EGO-Swarm | 原任务执行链；官方ros2分支23a8d5a，EGO原GPLv3许可保留 | 保留为执行/历史数据基线。只读describe发现waypoint、ego均built，不等于新飞行通过；原动态失败不改判 |
| MINCO S4NU分轴制动 | 已有原生axis_stop及连续审计；GCOPTER e0444f6，MIT许可保留 | 保留离线候选，不声称已在线兜底或任意初态可行 |
| 完整GCOPTER走廊优化 | 已有离线probe；[官方实现](https://github.com/ZJU-FAST-Lab/GCOPTER)公开MINCO与走廊模块 | 不为本切片替换现有执行链；走廊/动力学硬审计与接管仍需原合同 |
| 稀疏GRU/Neural-Primitive等学习路线 | 本机没有已验收的稀疏策略适配与部署权重；本轮作者项目页不可读，不能判断其最新发布状态 | 非当前必需前置。以后可换成熟模型或做最小适配，不随机初始化网络控制，不默认训练 |
| NavRL动态检测候选 | 旧记录中的缓存路径当前不存在 | 标待核，不以历史摘要充当本机可运行资产 |

选型依据是现有接口与已验收范围，未开展新规划器性能排名。EGO仍消费其原有稠密输入；旁路四束不被描述为“四束已完成自主避障”。

## N1观测合同

- 从已录`/drone/ego/depth`取固定前右25°/8°、前左8°/25°四个像素；从`depth_down`取独立中心像素。射线间有盲区，侧后方未覆盖。
- 复用drone的`inspection_depth.sample_pixel`处理32FC1、行填充和大小端；复用`ego.frames`的光学旋转。所有像素位置固定，不用障碍真值选择像素。
- 将光轴深度转换为斜距，保留像素、原始float32字节、单位方向、单像素视角、hit/no_return/invalid和原源时间。无回波不等于通道无障碍。
- 原包没有CameraInfo。前视K取保存的运行yaml，图像尺寸/裁剪取显式配置的pinned OakD SDF；下视从该回合生成SDF解析。均标明非实机标定、非录制CameraInfo。
- 世界射线使用同一源stamp且同一时钟回合的已录光学PoseStamped。其生产者是理想Gazebo定位sidecar，不作为独立VIO成果。
- rosbag记录时间与图像仿真源时间分开保存。用记录中的前后/clock消息给图像及位姿共同可用时刻包络，使用上端作为回放显示时刻；不直接跨时钟相减。
- 三维射线用原生scale_invariant的2px标注线宽，适应桌面与手机；不表示实体粗细。
- 各流独立选择当时已可用观测。达到.25源秒即隐藏世界射线，表格保留年龄及“已过期”；此门槛仅用于显示，不是新增飞行判据。
- 原始导出保留全部源帧；MCAP页面按原诊断位姿帧显示最新已可用观测，不插值或伪造50Hz新测量。缺包不直接等同注入丢帧；多个时钟回合不强并成一个播放轴。

## 使用与复验

在项目根先source ROS2，再执行已有记录的离线抽取；不会初始化ROS节点、发布话题或启动仿真：

```sh
source /opt/ros/jazzy/setup.bash
python3 apps/fishbot-control-station/workbench-tools/drone-sparse-observations.py --run-dir "$DRONE_RUN" --output "$SPARSE_EXPORT"
```

`DRONE_RUN`为已有回合目录。`SPARSE_EXPORT`指向诊断缓存中同一原任务ID的`sparse-observations.json`。
默认缓存为`apps/fishbot-control-station/workbench-tools/output/drone-diagnostics/<id>/`，可用`DRONE_DIAGNOSTICS_DIR`选择隔离缓存。
`--drone-root`指定已有无人机项目，`--front-model-sdf`指定OakD SDF；不自动下载、安装或修改依赖。
抽取后打开原`/drone-diagnostics?taskId=<id>`，显示四束前视、一束下视及新鲜度。原文件变化后派生MCAP按mtime刷新。

局部验证：

```sh
python3 apps/fishbot-control-station/workbench-review-tests/test_drone_sparse.py
node --test apps/fishbot-control-station/workbench-review-tests/drone-sparse.test.cjs apps/fishbot-control-station/workbench-review-tests/drone-diagnostics.test.cjs apps/fishbot-control-station/workbench-review-tests/drone-services.test.cjs
```

独立原包读回：

```sh
python3 apps/fishbot-control-station/workbench-review-tests/audit-drone-sparse-recording.py --bag "$DRONE_RUN/depth-input" --exported "$SPARSE_EXPORT" --output "$SPARSE_AUDIT"
```

浏览器沿用原只读检查，加`DRONE_SPARSE_EXPECTED=1`验五束表格、新鲜3D射线、过期清除及后退；控制写请求仍被记录并拦截。
代码和必要文档入库，原包、导出、审计JSON、截图与本地运行状态继续保留在忽略目录。

## 本轮数据与交接

- 原任务ID：`748f910e-f0f8-4ecf-b2d5-22b7b15d57e6`；原记录在`/home/muqiao/dev/ros2/projects/drone/output/measured-state-reanchor-flight-748f910e`，没有创建新飞行。
- 前视681帧、下视648帧，合计1329帧、3372束；965束hit、2407束no_return。同源位姿配对1329，未对齐0、重复源stamp 0、时钟回合1。
- 独立原CDR审计3372像素/1329位姿通过；斜距最大误差1.78e-15m、世界端点7.11e-15m。初次浮点时钟比较产生16条审计假失败，改为整数纳秒核对后通过；原数据和阈值未改，初次报告保留。
- 前/下视最大源间隔1.124/.892s；可用年龄上界最大.544/.548s。56帧在可用时已过期（前26/下30），不生成新鲜射线；不能据此认定注入丢帧比例或精确通信延迟。
- 合成细柱负例证明射线之间的盲区：中心深度4.7m、四束无回波。它是单元夹具，不是新飞行或真实障碍检测成绩。
- 6项Python检查、14项Node检查、定向ESLint与生产构建通过。页面验收与提交状态见[进度](../plans/workbench-code-rebuild-20261018/progress.md)。
- 代码目录：`workbench-tools/drone-sparse-observations.py`抽取；`drone-sparse.cjs`按可用时刻取观测；`DroneDiagnostics/SparseObservation.tsx`显示年龄与测距；`audit-drone-sparse-recording.py`独立回读原包。
- N2已有[精确分段接口](DRONE_TRAJECTORY_PRIMITIVES.md)离线资格；本切片没有24维状态向量、教师训练、策略推理或飞控写入口。drone保持c866441冻结，动态闭环仍未通过。

当前页面：`http://127.0.0.1:5186/drone-diagnostics?taskId=748f910e-f0f8-4ecf-b2d5-22b7b15d57e6`；手机追加`&mobile=1`。接续owner为当前对话Codex。
