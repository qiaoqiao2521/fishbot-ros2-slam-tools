# F1 Findings

## 已复用
- 原 workflow 已支持任意 N 个 batch 和每批 delivery_pose；只需让新场景的订单数据进入原初始化入口。
- 原 prepare 在编译碰撞体后生成激光切片和完整碰撞图。实体通道占用在编译前加入，可复用同一地图生成链。
- 原独立 oracle 区分执行终态、物理交接/运输与目标停车，不新增评分实现。

## 当前边界
P8 保留 39 项运行文本观测和所有 A–J 失败。J 的新 frame 已进入回调但缓存提交受控制锁阻塞；独立短缓存锁候选尚待定向测试与原生运行。H 未获得 callback 调度的间隙不能由该修复直接宣称解决。

ARIAC2025 仅作订单、工位与交付评价语义参照。官方来源已由场景worker打开核实：[ARIAC仓库](https://github.com/usnistgov/ARIAC)、[2025文档](https://pages.nist.gov/ARIAC_docs/en/stable/index.html)、[任务场景](https://pages.nist.gov/ARIAC_docs/en/main/pages/scenario.html)。当前一物体在两订单之间显式 reset；不宣称同回合多货物库存、真实产线 PLC 签收或跨引擎统一物理。

## 实体通道与缓存修复
- 占用箱 world 中心(-.45,-2.10,.25)m，完整尺寸(.18,.30,.50)m；同步写入 world、arm-contact 与 rig，arm-local 坐标按原 station_offset 平移。原 prepare 自动生成两地图，无第二套栅格化。
- 四个静态 MuJoCo3.3.7 场景（FishBot/J100×open/occupied）由场景 worker 编译测试；两图占用中心 open254/occupied0、原状态维数与物理参数保持。完整足迹直线受阻但端点/出站不占，有几何连通路径。这不是 Nav2 可达或实际配送证明。
- 缓存修复209项相关回归通过，P8原生K在140/9110独占运行；F1将在其清理后串行启动，不让同机两物理运行争用。

## 评测审查修正
- 原 native_cleanup_known 不能单独授权关闭运行中的整车臂任务；F1薄层先核同任务/回合明确终态，再复用原native/quiet证明。不修改P8运行源。
- 物理裁决与预算分开：原score通过不代表360秒内完成。每单finite elapsed≤360和整轮≤1000另外进入整体验收，缺时长不计通过。1000是验收预算，不冒充包含阻塞评分/清理的硬退出时刻。

## 当前修正
上述 v1 箱体与运行状态是历史记录。v1 原几何预检失败且零运动；当前 v2 箱体中心(.35,-2.10,.25)、完整尺寸(.12,.30,.50)。独立实跑开放场景2/2、占用场景1/2物理通过；B原生成功但物理位置4.3478cm，保持false。不能把Workflow或Nav2终态当作物理通过。短缓存锁与清理诊断已验收实现，J100的低速小转向响应不足仍独立校准中。


旧prepared不是当前实现：occupied-v2的生成YAML仍checker stateful=true且RPP未显式false；新prepare已读回双false、原native .015/.035门槛。direct/via必须共用新prepared，不能把旧YAML和新代码组合冒充当前配置。同一已生成输入可跨两个资源窗口独立启动，前提运行源码、场景、订单和原评分不变；新run/UUID分开，时段负载差异不得当策略效果。


实际派生manifest需要贯通生产器：首direct零订单启动失败揭示cooperation_sim.source_identity固定从world旁读scene-manifest，launch却只给bridge传derived路径。模拟器实际仍有物理帧，但bridge按现有manifest身份合同拒收，因此无ready。薄修复显式--manifest→Physics→source_identity并由launch共传，两端同源；保留无新参数的默认。原result保留unknown/未评分及独立owned清理回执，不当运输失败样本或成功成绩。
