# N3/N4：离线参考前缀与MINCO刹停对照

本片把已有N2窗口接到现有MINCO S4NU分轴制动，在原生MCAP中展示对照候选和拒绝原因。
这是记录驱动的离线推演。没有新的飞行、控制提交、动态占据资格或任务成功率结论。
无人机源码保持c866441冻结；没有训练、重编译无人机或新增规划器。

## 现有方法如何组合

1. 读取[N2精确分段窗口](DRONE_TRAJECTORY_PRIMITIVES.md)，保留原任务、参考曲线和绝对sim相位。
2. 取0.8s前缀末端的完整PVA及左极限参考jerk，交给既有`axis_stop_request`。
3. 用原生`minco_probe`的`axis_stop`调用官方MINCO_S4NU，固定停止时长XYZ=3.5/1/.4s。
4. 复用原连续审计检查刹停尾与完整拼接曲线，分列动力学、切点PVAJ、尾内C3和资格未知项。

没有调用L-BFGS优化或调参筛选。停止位置沿用现有p0+.5*T*v0，不能因此假设该终点在自由空间。
参考jerk来自已知曲线，未称实测飞机jerk。原cubic前缀内部仍有J跳变；全曲线只声明C2，切点及尾内单列C3。

原速度1.8m/s、加速度1m/s²、Z2.2m硬界不变。原审计器在本片的`corridor`仅检查Z上界；XY走廊、动态占据和终端区域均未验证。
报告明确`math_gate_scope`、`occupancy=unverified`和`execution_admission=not_performed`。
参考继续前进与制动停稳的目标不同，不能把两者的数学通过率当算法任务成功率排名。

## 当前固定参数结果

| 原曲线 | 生成 | 完整曲线V峰m/s | A峰m/s² | Z峰m | 原数学判据 |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | 是 | .572879 | .691061 | 1.759597 | 通过；占据未知 |
| 2 | 是 | .526417 | .835167 | 1.769847 | 通过；占据未知 |
| 3 | 是 | 1.228397 | 1.674366 | 1.806082 | 加速度拒绝 |
| 4 | 是 | 1.585710 | 1.661290 | 1.986593 | 加速度拒绝 |
| 5 | 是 | 1.574017 | .923821 | 2.128953 | 通过；占据未知 |
| 6 | 是 | 1.680871 | .981600 | 2.133051 | 通过；占据未知 |
| 7 | 是 | 1.578854 | 1.081960 | 2.138174 | 加速度拒绝 |
| 8 | 未评分 | — | — | — | 原task/goal身份缺失，不派生 |

7条均生成，4条数学通过，3条因A超界拒绝；切点PVAJ均在1e-8数值容差内。
最大切点误差约2.30e-16，尾内J连接误差约4.77e-13。没有用J=0替代参考值，没有放宽A界。
生成/进程往返/审计耗时按离线墙钟另存，不映射成原飞行sim截止预算或实时性能成绩。

## 原生页面

常用入口仍为`/drone-diagnostics?taskId=748f910e-f0f8-4ecf-b2d5-22b7b15d57e6`，手机加`&mobile=1`。
新增`/drone/candidates`原生MCAP通道和“离线前缀＋MINCO刹停”说明。
紫线为数学通过候选，红线为拒绝候选；原历史备份未记录，仍不补青色已执行轨迹。
曲线#7在首发故障33.452s显示加速度拒绝；32.920s的#6显示数学通过/占据未验证；33.552s的无身份#8不派生。

候选只跟随当时最新收到的原名义曲线，新曲线替换后移除旧候选。seek、后退和刷新不发送控制。
可选文件缺失、ID不符、顶层null或空条目降级处理；损坏条目不阻断原任务回放。
预览每段17点仅用于绘图，动力学采用原连续极值与区间覆盖，不用显示采样判安全。

## 使用与复验

```sh
python3 apps/fishbot-control-station/workbench-tools/drone-stop-candidates.py --primitives "$PRIMITIVES_JSON" --output "$CANDIDATES_JSON"
python3 apps/fishbot-control-station/workbench-review-tests/test_drone_stop_candidates.py
node --test apps/fishbot-control-station/workbench-review-tests/drone-candidates.test.cjs
```

`PRIMITIVES_JSON`为N2输出；`CANDIDATES_JSON`写入原诊断缓存同ID的`stop-candidates.json`。
默认原生可执行文件为`~/.cache/ros2-drone/minco-probe/minco_probe`，支持`--native`和`--drone-root`显式指定；不自动安装或重构建。
`--stopping-times`可显式修改；上表仅本次预声明3.5/1/.4s对照，不宣称参数对任意初态可行。
原生不可用或某条生成失败时，保留该条原因并继续其他条目，不画伪造候选。

页面复验沿用项目脚本，增加`DRONE_CANDIDATES_EXPECTED=1`；同时设置`DRONE_SPARSE_EXPECTED=1`保留原稀疏观测回归。
JSON、原生输出、构建产物和QA截图留忽略目录；代码与文档按既有仓库边界交付。

本片完成组件对照与N4历史旁路展示，不代表N3任务级方法比较、M2完整滚动提交或M3动态执行完成。
后续先补官方Gatekeeper源码/机载许可及本地CommittedTail差异，再确定完整地图有效性和提交合同的最小适配。
当前仍缺动态安全集、终端区域、实际跟踪包络与PX4采用回执；动态闭环仍未通过。
实际页面验收与交付见[进度](../plans/workbench-code-rebuild-20261018/progress.md)。
