# 巡逻与地图模块修复

## Goal
保留7a8fe13纯TypeScript模块思路，修复已复现边界，接回原页面/任务/规则owner，补真实ROS合同及隔离仿真。

## Constraints
不重写Nav2，不用前端位置判断替代原Action终态；不动实机/固件/网络/原121演示。后端暂不支持的模式明确拒绝，不静默降级。

## Phases
1. complete：复现275绿测之外的ROS载荷、几何、状态和引用缺陷。
2. complete：worker各完成两个库和其tests；root接回页面/reducer/后端薄适配。
3. complete：实际页面、原生消息构造、相关全量测试与独占122闭环通过。
4. in_progress：文档/知识判断和独立审查完成，Git交付进行中。

## Success
原反例正确处理；真实Goal/Filter消息可构造；禁区由原栅格器发布和Nav2确认；网页可见里程与规则碰撞提示，原owner仍决定任务状态；未知回执不重发；完整后端合同/测试/页面与实际ROS验证，失败证据保留。

## Next Step
完成提交推送与远端SHA读回，保留空闲122复核实例。
