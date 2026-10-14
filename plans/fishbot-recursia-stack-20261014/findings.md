# Findings

官方Recursia main锁56c902d95958041d231811d168008a2811933f65。公开real runner为FR3链；sim/README明确仿真源码/依赖未加入。论文四层共享栈为工具、技能、交接、验证；源任务修改后冻结，目标反馈不得调试。

现有cargo_retained只检查中心和支撑；settled_cargo已有旋转外廓检查，应提取复用。装货交接和携货期间的机械臂home/quiet、车辆hold/stopped需要一致复验。当前已有独立连续终态留盘评分，不降低门槛。

官方静态verdict为纯函数，但依赖输入键齐全及truthy success；薄适配须先严格验证配对面板、bool成功、资源条件与源冻结，传failure_class=None，仅将实际新增成功作为接受依据。阶段前进只作诊断。
