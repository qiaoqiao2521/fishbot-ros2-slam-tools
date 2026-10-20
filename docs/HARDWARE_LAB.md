# 真实地图、新底盘与负压实验

三个分项复用当前工作台，分别保存验收证据。它们不是一台已经在真实房间执行爬壁运输的整机。

## 实测工作图

```bash
/usr/bin/python3 tools/fishbot_real_scene.py \
  --source-map /absolute/private/map.yaml \
  --output "$HOME/.cache/fishbot/real-map/fixture"
./fishbot.sh scene-validation \
  --config "$HOME/.cache/fishbot/real-map/fixture/panel-config.json" \
  --output "$HOME/.cache/fishbot/real-map/run" --domain 132 --port 9102
```

输入为ROS地图YAML/PGM。原始free、occupied、unknown像素保留；仅实测occupied格生成墙，墙高0.55m是明确假设。未知空间没有物理重建，不标成实测房间。AMCL读取原图；NavFn的`allow_unknown=false`限制规划，不添加虚拟激光墙。

生成器选择完整旋转外廓可容纳的已知区域路线。派发前预检路径，执行后独立按每帧真值检查完整外接圆是否仍在known-free区域，另保留接触、停车和原生UUID评分。地图、provenance与路线图默认只在私有缓存。

本轮源图来自已接受的2026-10-08工作整图，实测自由区域约7.41m²。结果只证明该二维布局中的虚拟导航；没有重新访问真实房间或操作已售实体车。

## Clearpath Jackal J100

```bash
./fishbot.sh scene-validation \
  --config tools/config/jackal_scene_validation.example.json \
  --output "$HOME/.cache/fishbot/jackal/run" --domain 133 --port 9103
```

官方来源、许可证与网格在[模型目录](../workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/mjcf/jackal_j100/README.md)。使用Clearpath Jazzy `78e3677`的底盘/四轮尺寸、质量和完整惯量；MuJoCo轮胎摩擦、接触priority、速度执行器增益和力矩限值是可编辑仿真假设，未做厂家标定。

适配输出MJCF、四关节URDF、左右各两轮的diff_drive_controller及Nav2参数。保守矩形半尺寸约0.244×0.223m，规划外接圆约0.3304m；保持原0.17m渐变带，膨胀半径约0.5004m。任务桥使用同一半径检查航点、返航、倒车扫掠及规则参数，默认FishBot仍为0.13m。

J100默认复用官方`imu_sensor_broadcaster`与`robot_localization` EKF。轮式输入只取车体vx/vy；IMU只取原生roll/pitch和gyroZ，不取绝对yaw、加速度或真值。原始轮式里程计在`/wheel/odom`，融合输出为`/odom`，只有EKF发布odom到base_footprint的姿态。采用理想仿真IMU与声明的协方差，不能外推真实IMU精度。`localization.enabled=false`可显式恢复轮式对照。

低速原地转向使用已安装的`PoseProgressChecker`，按位移或转角更新进展；保留原0.15m/10s条件，只增加0.2rad角度判据。没有放大无进展期限。

四轮低速擦滑会使RPP按实际角速度限制起步指令时长期低输出。仅J100将`rpp_rotation_max_angular_accel_rad_s2`设为10；这是RPP每周期的命令变化上限，不代表实际车体达到10rad/s²。原生冻结plant对照中，0.1/0.5rad/s请求各2秒实际仅转0.0191/0.1547rad。轮控仍保留2rad/s²限幅、1.5rad/s速度上限和12Nm执行器力矩限制；完整往返按原条件独立验收。

原生探针证明四轮真实接地和运动，也测得明显转向滑移。它不证明闭环导航通过；实际Nav2结果、失败与接续均见[本轮进度](../plans/scene-hardware-lab-20261020/progress.md)。三维雷达安装高度改变，本例不沿用FishBot低矮近场测试物的评分；探针明确为`interface_only`，保留原默认五项低物体验证入口。

## 负压与短距离爬壁

首次在隔离环境安装官方Python MuJoCo。不要使用ROS C++ vendor的库路径覆盖该环境。

```bash
python3 -m venv "$HOME/.cache/fishbot/suction-python"
"$HOME/.cache/fishbot/suction-python/bin/python" -m pip install 'mujoco==3.3.7' Pillow
./fishbot.sh suction --output "$HOME/.cache/fishbot/suction/run" --render
```

已有独立环境时设置`FISHBOT_SUCTION_PYTHON=/absolute/env/bin/python`。默认入口使用上述缓存。压强、有效面积、泄漏、泵曲线、摩擦和评分输入在[suction_reference.json](../tools/config/suction_reference.json)，可以直接编辑。

复用[MuJoCo原生adhesion执行器](https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html#actuator-adhesion)。用`Δp×A`作为接触法向吸附力，压强按容积/泵曲线/泄漏动态建立和释放。墙面四轮以原生hinge和velocity执行器产生沿墙摩擦驱动力。没有weld、位姿伺服、瞬移或运行中修改qpos。

五个案例分别验收：地面关泵滑移、开泵抗横推、墙面持压保持、先保持再失压脱落、四轮沿平面墙上行。失压时自然脱落是预期故障响应，不标成运输成功。0.2ms步长执行，0.1ms复核竖墙稳定性；保留原1ms失败，不能用提高采样频率掩盖物理不稳定。

这是4kg假设试件的降阶模型。墙面试件机壳只有视觉和惯量，四轮参与接触；失压案例不验证机壳撞击或整机防护。没有涵道CFD、柔性密封裙/FEM、表面粗糙度标定或跨墙角导航。泵电能是模型估计；驱动只记录机械正功，未包含电机损耗或堵转电流，二者不能相加冒充实测整机电耗。

## 工作台与报告

```bash
./fishbot.sh hardware-report \
  --real /absolute/real/report.json \
  --base /absolute/jackal/report.json \
  --suction /absolute/suction/report.json \
  --output "$HOME/.cache/fishbot/hardware-lab/latest"
```

此命令只聚合现有文件，不启动ROS或重发任务。网页“成果验收”增加三个分项和各案例指标，显式点击“读取实验报告”。端点只支持GET；缺报告、坏JSON或某分项失败不会抹去其他有效分项，也不会把历史缓存冒充当前结果。

网页默认读取`~/.cache/fishbot/hardware-lab/latest/report.json`。用`FISHBOT_HARDWARE_REPORT`可选择另一个服务端文件；浏览器不能指定服务器路径。地图与运行数据不提交Git。

## 连续地面转墙扩展

原五个负压分项保持原定义。用户追加的整车转接使用同一完整碰撞车体，在单个回合完成地面到墙面交接、爬升和保持，见[运行与验收](GROUND_WALL.md)。它是专用吸附轮改装模型，不代表普通J100或真实负压机构已完成设计。
