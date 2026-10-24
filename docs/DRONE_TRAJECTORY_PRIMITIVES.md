# N2：原名义轨迹的精确分段接口

把已录EGO三次B样条限制成短时间窗口，保留位置、速度、加速度和原始jerk。
这是离线接口资格，不是新规划器、教师真值、已执行命令或备份接管。
无人机源代码保持c866441冻结；没有运行ROS节点、PX4、Gazebo或飞行。

## 复用和表示

- 复用无人机`scripts/audit_retiming.py::curve`读取B样条；SciPy `PPoly.from_spline`逐轴转换，在原节点处分段。
- 从`max(start_sim_s, received_sim_s)`对应的原相位开始取窗口，不把曲线起点移到收到时刻。每段系数平移到该段起点。
- 三次多项式的高阶项补两个零，复用原`3×6 coefficients_descending`容器；系数作用于局部物理秒，由原`normalized_power`归一化一次。
- `pieces[].duration`及`coefficients_descending`兼容现有PVA读取；不填写`native_success`，因为本切片没有调用求解器。
- 初末状态为`initial/terminal_pvaj_xyz_columns`：行是XYZ，列是P/V/A/J。`source_curve.start_pva`原日志的行是P/V/A、列是XYZ，两者明确区分。
- 原cubic通常仅C2。逐段保留左右jerk，报告跳变；不固定J=0、不假称C3、不做单段五次拟合或时间拉伸。

转换误差由独立B样条导数在每段中点构造参考多项式，使用原Bernstein区间证书核对整段P/V/A/J。
数值容差沿用原边界审计的1e-8，不是新的物理门限。连续V/A/Z复用原`interval_certificate`，未改公式或阈值。

## 证据资格

报告分别保存三项结论：

1. `conversion.passed`：精确限制及PVA拼接在数值容差内。
2. `vaz_gate.passed`：该窗口通过保存的离线候选界，V≤1.8m/s、A≤1m/s²、Z≤2.2m。
3. `occupancy.status=unverified`、`execution_admission=not_performed`：没有消费按曲线时刻保存的完整GridMap，也没有PX4采用回执。

离线MINCO夹具的静态走廊/占据见证不能冒充每条EGO曲线当时的自由空间。稀疏射线也不能证明扫掠体积自由。
收到曲线不等于提交或执行；未来窗口还可能被新曲线替换、被新占据作废。报告保留原始曲线、源行、任务/目标ID、起始和接收时间。
原记录第8条没有task_id/goal_id，保持`unrecorded`；不继承前七条任务身份。归档任务ID仅定位原文件。

## 当前数据

原文件为748回合的`ego/trajectory-events.jsonl`。本次预先固定窗口0.8s，8窗/23段全部转换通过，8窗V/A/Z证书全为clear。
CLI的`--horizon`允许显式选择其他正时长；0.8s为本次调用值，未设通用上限，也未验证其他时长的历史结果。

| 曲线ID | 接收相位偏移s | 分段数 | V峰m/s | A峰m/s² | Z峰m |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 约0 | 4 | 0.409179 | 0.691061 | 1.751362 |
| 2 | 0 | 3 | 0.403946 | 0.768911 | 1.760568 |
| 3 | 0.028 | 3 | 1.144514 | 0.817598 | 1.798740 |
| 4 | 0.036 | 3 | 1.585702 | 0.723131 | 1.925027 |
| 5 | 0 | 3 | 1.574017 | 0.923821 | 2.128953 |
| 6 | 0.036 | 3 | 1.632415 | 0.821758 | 2.133051 |
| 7 | 0.024 | 3 | 1.541072 | 0.764559 | 2.138174 |
| 8（未归属） | 0.004 | 1 | 0 | 0 | 2.183529 |

整段转换误差极值诊断：P≤1.02e-15m、V≤1.76e-15m/s、A≤1.52e-14m/s²、J≤1.31e-13m/s³；按1e-8容差核对的原区间证书全部clear。
跨段PVA误差≤1.48e-15；最大原J跳变2.268873m/s³。第6条接收相位的位置比日志原起点偏移约.05533m，不能套用旧`start_pva`。
初版因常量轴多项式自动裁剪系数而漏掉第8条，逐轴补零后修复；初次7窗报告保留，不算8窗通过。

## 使用与接续

在工作台仓库根执行，复用已安装的NumPy/SciPy和冻结无人机审计模块：

```sh
python3 apps/fishbot-control-station/workbench-review-tests/test_drone_primitives.py
python3 apps/fishbot-control-station/workbench-tools/drone-trajectory-primitives.py --run-dir "$DRONE_RUN" --horizon 0.8 --output "$PRIMITIVES_JSON"
```

`DRONE_RUN`为原记录目录；`--drone-root`可显式指定原审计模块所在仓库。没有安装或构建操作。
保存的`minco-margin-audit.json`提供离线候选界；若缺失，保留转换，门限结论为unverified，不默认通过。
本轮JSON在忽略的`workbench-tools/output/drone-primitives/748f910e-f0f8-4ecf-b2d5-22b7b15d57e6/exact-windows.json`。
两个局部夹具覆盖段内相位、非零初态、加速度拒绝、跨节点PVA及jerk跳变、空任务身份和缺占据资格。

下一项若需候选旁路比较，应先给所选方法接上这个分段合同，并保留原判据、时钟与身份。
在线采用仍缺动态占据有效性、提交/执行回执和有效备份；本切片不解除冻结，不授权训练或飞行。
验收及仓库交付见[现有进度](../plans/workbench-code-rebuild-20261018/progress.md)。
