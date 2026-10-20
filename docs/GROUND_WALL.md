# 整车从地面连续转上墙

本实验在同一个 MuJoCo 场景、同一自由车体上完成地面接近、墙角交接、完全离地、沿墙爬升和轮端制动。原来的地面抓地、竖墙保持五例仍是独立分项，不能代替这一连续回合。

## 运行

```bash
./fishbot.sh wall-transition \
  --output "$HOME/.cache/fishbot/ground-wall/run" --render
```

复用负压隔离 Python 环境。需要 `mujoco==3.3.7`、Pillow、PyYAML；实际视频编码使用本机 `ffmpeg`。已有环境可用 `FISHBOT_SUCTION_PYTHON` 选择；共享 wrapper 清除 ROS 的 `PYTHONPATH` 和 `LD_LIBRARY_PATH`，不改系统 ROS 或网络。原隔离环境缺 PyYAML 时，在该环境执行 `python -m pip install PyYAML`；本轮实际版本为6.0.3。

默认执行有吸附与关闭吸附两个回合；`--case transition` 或 `--case no_pump` 可单独执行。输入在 [ground_wall_reference.json](../tools/config/ground_wall_reference.json)。车架、轮几何、质量和惯量继续读取 [J100 来源配置](../tools/config/base_profiles/jackal_j100.yaml)，不复制一套隐藏尺寸。

## 机械与控制

完整车架碰撞和四轮原生 hinge 保留。自由车体没有 weld、世界位姿目标、外力举升或运行中重置。电机受声明的速度和力矩限制。

四轮各复用一个已有 `Chamber` 和 MuJoCo 原生 `adhesion` 执行器，按真实接触决定密封代理。官方执行器把某个轮体的吸力分配到其全部接触法向；轮子同时碰地和碰墙时，也会吸向地面。前轮已在墙面承接后，控制器短暂释放仍在地面的后轮腔，待后轮离地再恢复吸附。[MuJoCo 3.3.7 定义](https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html#actuator-adhesion)

接触交接由分轮反馈控制；转角允许原生轮胎滑移，不强行写入一条无滑几何轨迹。停车通过轮编码器角度反馈和原有受限电机实现，不固定车身在世界坐标的位置。

这是沿用 J100 尺寸和惯量的专用吸附轮改装参考模型。轮胎摩擦、有效面积、阀控、理想密封和编码器均为可编辑假设；没有证明普通 J100 轮胎能够密封。新增泵、阀和密封机构的实体质量与结构尚未标定。没有涵道 CFD、柔性密封 FEM、视觉上墙导航或真机验收。

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
  --output "$HOME/.cache/fishbot/hardware-lab/latest"
```

保留原三个分项的历史案例，将连续转墙单独追加到负压部分。失败或缺报告不会清除旧有效结果。

将实际有吸附回合的 `transition.mp4` 复制到 `~/.cache/fishbot/hardware-lab/latest/transition.mp4`，或用 `FISHBOT_TRANSITION_VIDEO` 指向该录像。工作台 `/results` 在显式读取报告后显示播放器；播放不会执行 ROS 动作。视频路由只读取一个服务端指定文件，不开放缓存目录。

录像按源时间帧率编码。物理结果、源时长、帧数、停车与模型限制仍以原报告为准；录像不是独立评分。

本轮实际结果和保留的失败见[当前进度](../plans/scene-hardware-lab-20261020/progress.md)。

## 本轮验证

18.431kg模型从水平地面出发，4.50源秒开始前墙/后地交接，8.52源秒达到四轮墙面承载且全部离地。之后继续爬升0.31742m，最后连续静止4.50秒；原生warning0、无外加举升力，成功回合无机壳支撑。原生轮扭矩峰10.513Nm，保持12Nm限制；最大接触穿透0.509mm，属于软接触数值量。

根独立复跑有吸附和无吸附两回合，并用0.1ms步长复验原0.2ms成功回合。半步长仍通过，额外爬升0.31731m，差约0.114mm；这不是硬件精度或性能改进的证明。无吸附回合未立起或完成保持，实际机壳碰撞峰643.679N保留，不称安全取消或任务成功。

实际录像640×480、15fps、271帧；源仿真18秒，视频18.0667秒包含末端一帧。未通过加速或拼接独立回合表现转接。
