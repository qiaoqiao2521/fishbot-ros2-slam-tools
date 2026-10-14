# Architecture decisions

这里只保存当前系统的重要取舍。阶段结果与待做事项回源 [PROJECT](../PROJECT.md) 和对应任务计划。

## 共用物理世界，复用现有控制与规划

固定 SO101 与 FishBot 使用同一 MuJoCo 世界和同一自由货物。移动控制复用 Jazzy Nav2，机械臂复用现有 IK/OMPL。规划克隆只作查询；执行由实际执行器、重力和接触推进。

这能直接检查抓放、交接和载物运输的因果连续性。分开世界传递货物位姿或新增一个仿真平台，不能替代本项目的完整任务验收。Arena 独立承担官方策略组合评测，其运行通过不代表 SO101 或运输能力完成。

仅在已有栈出现已核实的能力缺口时重访后端选择。来源：[架构](ARCHITECTURE.md)、[协同](COOPERATION.md)、[Arena](../experiments/arena/README.md)。

## 观测、动作回执与物理评分分别判断

ideal/perturbed信标由仿真真值派生，显式标注为理想传感器；页面总览相机不参与定位。vision使用后向RGB、AprilTag/IPPE与固定标定，检测失败不会退回理想观测。现有交接条件和机械臂碰撞查询仍使用物理反馈，必须披露该依赖。

原生动作成功、实际交接成立和完整运输成功分别确认。评分保留完整外廓、真实接触与连续源时间；候选比较在运动环之外完成，不向每条命令增加晋级锁。

真实视觉接入或新评分任务出现时，先核对来源、坐标、时间与不确定度，再扩展薄适配。来源：[协同合同](COOPERATION.md)、[共享执行栈](STACK_IMPROVEMENT.md)、[视觉停靠计划](../plans/visual-docking-robustness-20261014/task_plan.md)。


## 地图定位与视觉精停靠分工

AMCL和原生NavigateToPose负责到达工位准备点；RGB提供原生DockRobot的近距目标。远处PnP的协方差较大，不反复写入initialpose重置AMCL。完整六维图像协方差保留，硬平地约束不用于伪装测量精度。

采用此分工是因为开发回合证明，静态标定通过不等于动态姿态或AMCL一致性通过。只有在独立数据证明RGB具备更广域定位能力时重访融合；不以放宽时间/物理门槛取得成功。来源：[协同](COOPERATION.md)、[视觉发现](../plans/visual-docking-robustness-20261014/findings.md)。
