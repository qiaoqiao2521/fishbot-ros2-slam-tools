# 共享执行栈与配对验收

FishBot借鉴Recursia的交接状态和候选筛选机制，复用现有MuJoCo、Nav2和SO101。执行环读取新鲜物理反馈，再决定下一阶段；改进环在执行之外比较父版本与候选版本。当前没有在线LLM、自动代码修改或策略训练。

## 复用与边界

官方源码锁[56c902d](https://github.com/cocacola-lab/Recursia/tree/56c902d95958041d231811d168008a2811933f65)。公开实现提供FR3实机链；[sim说明](https://github.com/cocacola-lab/Recursia/blob/56c902d95958041d231811d168008a2811933f65/recursia/sim/README.md)明确仿真代码和依赖尚未加入。这里不是完整Recursia仿真部署，也没有复现论文成功率。

直接复用[官方verdict](https://github.com/cocacola-lab/Recursia/blob/56c902d95958041d231811d168008a2811933f65/recursia/real/cap/agent/rsi/recursia.py#L181)纯函数，保留[许可证](licenses/Recursia-LICENSE.txt)和[NOTICE](licenses/Recursia-NOTICE.txt)。未搬运FR3动作、SAM3或重建runner。官方review绑定其campaign与真实机器人；本项目缺口是现有仿真报告的匹配、冻结和完整性校验，因此只加薄适配。

传`failure_class=None`，只接受真实新增成功且没有原成功退化。论文和公开实机实现允许部分阶段前进的不同选择规则；本项目只把阶段前进作诊断，不能当任务成功。

## 四层在项目中的位置

| 层 | 既有实现及本轮改进 |
| --- | --- |
| 工具 | 原生NavigateToPose、DockRobot、MuJoCo物理反馈和IK/OMPL规划 |
| 技能 | 抓取、松爪放稳、回位、携货运输；保留实际接触和连续源时间证据 |
| 交接 | 旋转后的完整货物外廓；车hold/停稳、臂home/停稳和货物留盘/放稳共同成立 |
| 验证 | 原独立物理oracle；新增仿真报告配对门禁，不改变评分器或碰撞边界 |

正在执行的策略与评测器分开。候选不得修改评分器、机器人模型、场景生成器或测试输入来制造增益。实体被第一步移动后，下一步必须读取当前状态；旧阶段成功不能代替新交接条件。

## 门禁用法

`./fishbot.sh stack-gate`读取已有suite/campaign报告，不启动ROS、不重跑任务、不自动应用候选。当前支持固定suite或随机navigation面板；不直接消费车臂oracle或Arena的异构结果。

[navigation-selection.json](../experiments/stack-gate/navigation-selection.json)从现有`case_matrix(12)`生成，固定六案例的完整物理输入、预算、评分器和模型来源。它是选择面板示例。开发面板和未来冻结目标测试另设；不得用目标测试反馈反向修代码，再宣称零样本迁移。

在每个独立版本checkout执行。输出目录必须在源码仓库外，所有输出文件必须新建：

```bash
./fishbot.sh stack-gate snapshot --panel /absolute/panel.json \
  --source-root /absolute/parent-checkout --report /absolute/parent-run/report.json \
  --phase before --output /absolute/parent-before.json
```

随后复用已有runner，对同一面板运行：

```bash
./fishbot.sh sim-suite --seed 12 --output /absolute/parent-run
```

报告完成后保存源边界回执：

```bash
./fishbot.sh stack-gate snapshot --panel /absolute/panel.json \
  --source-root /absolute/parent-checkout --report /absolute/parent-run/report.json \
  --phase after --before /absolute/parent-before.json --output /absolute/parent-after.json
```

候选版本按同一面板完成candidate-before、candidate-run和candidate-after。最后比较：

```bash
./fishbot.sh stack-gate compare --panel /absolute/panel.json \
  --parent /absolute/parent-run/report.json --candidate /absolute/candidate-run/report.json \
  --parent-before /absolute/parent-before.json --parent-after /absolute/parent-after.json \
  --candidate-before /absolute/candidate-before.json --candidate-after /absolute/candidate-after.json \
  --output /absolute/new-comparison.json
```

退出0表示输入与证据满足比较门禁，1表示有效拒绝，2表示输入错误。拒绝保留具体案例、丢失的原成功与证据原因。聚合分数更高也不能掩盖单案例退化；缺案例、unknown、预算或输入不一致、修改oracle/物理输入、前后源漂移及旧时间报告均拒绝。

本地回执是观察，不是签名证明。它只核对预声明源码的前后边界，不证明整个已安装原生环境或连续不可变。旧报告可以做诊断，但不得补写过去不存在的运行前快照或预算，将其升级成正式晋级证据。

## 本轮证据

现有编译MuJoCo场景中，托盘内边界0.058m。货物中心x=0.047m、绕z转45度时，独立八顶点核算最外角0.059727922m且底部仍有实际支撑；父版本误放，候选拒绝。中心x=0.040m样本两者保留。该静态机制配对只有两个样本、0个物理步骤，不代表运输成功率提高。

完整运输、门禁回归、源冻结和交付状态回源[当前计划](../plans/fishbot-recursia-stack-20261014/progress.md)。原始观测、地图、图片与运行日志保存在私有缓存。
