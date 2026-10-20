# 整车从地面连续转上墙：理想基准与硬件候选

理想基准在同一个 MuJoCo 场景、同一自由车体上完成地面接近、墙角交接、完全离地、沿墙爬升和轮端制动。新增硬件候选检验有限密封面积、间隙漏气及泵阀载荷后能否保持该结果。原来的五例仍是独立分项，不能代替这一连续回合。

## 运行

```bash
./fishbot.sh wall-transition \
  --output "$HOME/.cache/fishbot/ground-wall/run" --render
```

复用负压隔离 Python 环境。需要 `mujoco==3.3.7`、Pillow、PyYAML；实际视频编码使用本机 `ffmpeg`。已有环境可用 `FISHBOT_SUCTION_PYTHON` 选择；共享 wrapper 清除 ROS 的 `PYTHONPATH` 和 `LD_LIBRARY_PATH`，不改系统 ROS 或网络。原隔离环境缺 PyYAML 时，在该环境执行 `python -m pip install PyYAML`；本轮实际版本为6.0.3。

默认执行有吸附与关闭吸附两个回合；`--case transition` 或 `--case no_pump` 可单独执行。输入在 [ground_wall_reference.json](../tools/config/ground_wall_reference.json)。车架、轮几何、质量和惯量继续读取 [J100 来源配置](../tools/config/base_profiles/jackal_j100.yaml)，不复制一套隐藏尺寸。

## 密封与携带硬件

```bash
./fishbot.sh wall-transition --vacuum-model hardware \
  --output "$HOME/.cache/fishbot/ground-wall/hardware" --render
```

默认 `--vacuum-model ideal` 保留历史基准。两种模式输出不同案例 ID，不能用旧通过覆盖新失败。

原理想模型每轮面积为 `0.02m²`。它大于原轮胎宽度乘直径的 `0.00784m²`，且轮胎接触线没有形成封闭气腔。因此历史结果只证明理想力学机制，不能证明实际吸附轮可制造。

硬件候选在车底安装四个固定滑动裙边，使用原生碰撞唇边与背板；内半径35mm，有效吸力面积由 `πr²` 计算。64条原生射线沿实际16段唇边采样，只读取真实地面/墙面几何。薄缝漏流随间隙三次方增长，大开口再计惯性流阻；压力不会因接触布尔值直接恢复。配置见 [vacuum_seal.json](../tools/config/vacuum_seal.json)，实现见[密封模块](../tools/fishbot_vacuum_seal.py)。模型采用文献的薄缝规律，没有使用论文中的实验值冒充本车标定。[原始论文 §4.1.2](https://www.mdpi.com/1424-8220/21/4/1117)

一台 KNF N86 泵、八只 Festo 隔离/放气阀、管路、安装板、歧管与电控均携带非零质量、惯量及碰撞包络。四腔共用泵流量，不把厂家单泵流量乘四。腔容从裙边几何与各支管内体积推导，阀门包含开启/关闭延迟。[硬件配置](../tools/config/vacuum_hardware.json)逐项区分厂家数据与安装假设；泵曲线中间点是官方图粗略读数。[KNF 数据表](https://knf.com/fileadmin/Global_files/Downloads/Product_OEM_Process/Datasheets/KNF-Datasheet_N86_05_2023_web.pdf)、[Festo 阀目录](https://media.festo.com/media/204688_documentation.pdf)

几何按50Hz源周期更新，气路每个物理步积分。软唇接触是降阶柔顺代理，参考气腔容积不含流固耦合变化；固定管路不解析管损和弯曲。原生接触吸附只作用于裙边接触，不是自由空间负压力替代。功耗字段明确标记为泵名牌上界估算加阀额定功耗。这些仍是可编辑的候选假设，不是已完成的机械设计或真机验收。

## 机械与控制

完整车架碰撞和四轮原生 hinge 保留。自由车体没有 weld、世界位姿目标、外力举升或运行中重置。电机受声明的速度和力矩限制。

理想基准四轮各复用一个已有 `Chamber` 和 MuJoCo 原生 `adhesion` 执行器，按真实接触决定密封代理。官方执行器把某个轮体的吸力分配到其全部接触法向；轮子同时碰地和碰墙时，也会吸向地面。前轮已在墙面承接后，控制器短暂释放仍在地面的后轮腔，待后轮离地再恢复吸附。[MuJoCo 3.3.7 定义](https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html#actuator-adhesion)

接触交接由分轮反馈控制；转角允许原生轮胎滑移，不强行写入一条无滑几何轨迹。停车通过轮编码器角度反馈和原有受限电机实现，不固定车身在世界坐标的位置。

上述理想基准沿用 J100 尺寸和惯量，假设专用吸附轮。轮胎摩擦、有效面积、阀控、理想密封和编码器均为可编辑假设；没有证明普通 J100 轮胎能够密封。理想基准未计泵阀质量；硬件候选已计入源质量与假设安装包络，实际整机仍未标定。没有涵道 CFD、柔性密封 FEM、视觉上墙导航或真机验收。

## 独立验收

[评分器](../tools/fishbot_ground_wall_score.py)只读取原始轨迹，不给控制器反馈。顺序要求是：

1. 源时间起始窗口内，四轮在地面承载，车体水平，压力为零。
2. 存在前轮墙面、后轮地面的实际承载交接。
3. 四轮全部承载墙面、全部离开地面，车体接近竖直。
4. 从完全立起后的高度继续爬升至少 `0.20m`。
5. 进入停车阶段，并在墙上连续 `0.7s` 满足静止条件。

仅靠近墙面的 `margin/gap` 接触与真正产生法向力的承载接触分别记录。轨迹还检查源时间、采样间隙、位置/姿态连续性；缺失或无效证据保持 unknown，不靠重排或补时间戳制造通过。

同模型关闭吸附的对照，采用相同名义轮速与停车逻辑；物理反馈不同会使后续制动命令不同，不称全回合逐帧命令相同。按“不能完成持续爬升与保持”的预期评分。即便对照验收通过，`task_motion_success` 仍为 false。评分与源码/模型检查分别确认；轨迹连续不能单独证明没有 pose 写入或隐藏外力。

## 工作台

```bash
./fishbot.sh hardware-report \
  --real /absolute/real/report.json \
  --base /absolute/jackal/report.json \
  --suction /absolute/suction/report.json \
  --transition "$HOME/.cache/fishbot/ground-wall/run/report.json" \
  --hardware-transition "$HOME/.cache/fishbot/ground-wall/hardware/report.json" \
  --output "$HOME/.cache/fishbot/hardware-lab/latest"
```

保留原三个分项的历史案例，将连续转墙单独追加到负压部分。失败或缺报告不会清除旧有效结果。

将实际有吸附回合的 `transition.mp4` 复制到 `~/.cache/fishbot/hardware-lab/latest/transition.mp4`，或用 `FISHBOT_TRANSITION_VIDEO` 指向该录像。工作台 `/results` 在显式读取报告后显示播放器；播放不会执行 ROS 动作。候选录像单独复制到 `~/.cache/fishbot/hardware-lab/latest/transition-hardware.mp4`，或使用 `FISHBOT_HARDWARE_MODEL_VIDEO` 指定。两个视频路由各读取一个服务端指定文件，不开放缓存目录。

录像按源时间帧率编码。物理结果、源时长、帧数、停车与模型限制仍以原报告为准；录像不是独立评分。

本轮实际结果和保留的失败见[当前进度](../plans/scene-hardware-lab-20261020/progress.md)。

## 原理想基准验证

18.431kg模型从水平地面出发，4.50源秒开始前墙/后地交接，8.52源秒达到四轮墙面承载且全部离地。之后继续爬升0.31742m，最后连续静止4.50秒；原生warning0、无外加举升力，成功回合无机壳支撑。原生轮扭矩峰10.513Nm，保持12Nm限制；最大接触穿透0.509mm，属于软接触数值量。

根独立复跑有吸附和无吸附两回合，并用0.1ms步长复验原0.2ms成功回合。半步长仍通过，额外爬升0.31731m，差约0.114mm；这不是硬件精度或性能改进的证明。无吸附回合未立起或完成保持，实际机壳碰撞峰643.679N保留，不称安全取消或任务成功。

实际录像640×480、15fps、271帧；源仿真18秒，视频18.0667秒包含末端一帧。未通过加速或拼接独立回合表现转接。

## 硬件候选实际结果

| 项目 | 理想基准 | 有限裙边与携带硬件 |
|---|---|---|
| 整车质量 | 18.431kg | 19.82391kg |
| 总有效吸附面积 | 0.08m²，理想假设 | 0.015394m²，由内圈几何计算 |
| 最大压差 | 8kPa | 8kPa |
| 独立上墙任务 | 通过 | 未通过 |

硬件B轮与无泵对照均完整保留0–18源秒、901行。B轮没有前墙/后地的有效承载交接，也没有全车立起、额外爬升和墙面保持；原生warnings、外力、机壳及携带硬件支撑均为0。最大轮矩10.24845Nm，接触穿透0.509mm。无泵对照压力全0，按不能上墙的预期通过，车辆任务仍失败。

实际新增硬件1.27291kg，四个裙边另计0.12kg。重心在车体坐标的高度由63.636mm升到72.121mm。每杯名义气腔13.461mL；加入不同长度支管后为17.646/17.646/19.390/19.390mL。安装包络、内部惯量和这些参考容积仍包含明确假设。

首轮A保留。原生接触检查发现，MuJoCo同优先级参数混合把声明的裙边摩擦0.05变成0.8，柔顺时间常数0.02s变成0.0125s。B轮通过原生接触优先级让原声明值生效，然后重新运行；没有调大吸力或更改评分。新增测试读取真实 `data.contact`，不是只检查XML字符串。

四裙边在8kPa下总吸力上界约123.15N。即便把所有接触都按最高摩擦0.8乐观估计，切向上界98.52N仍低于车重194.47N。这是静态量级检查，不能代替转墙任务评分。整车回合没有完成转角交接，因此也不能把本次失败单独归因为墙角漏气；几何倾斜、局部开缝和90°角漏流由独立原生样件测试覆盖。

当前固定车底裙边没有独立改向或跨角接管机构。完成建模暴露了这处机械缺口，尚未交付可制造的整车爬壁方案。B轮原始报告与录像保存在私有 `~/.cache/fishbot/vacuum-model-20261020/hardware-b/`；A轮与旧理想结果均保留。
