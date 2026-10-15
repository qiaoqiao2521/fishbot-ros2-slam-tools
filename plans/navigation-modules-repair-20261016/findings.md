# Findings

- 7a8fe13只新增独立库与14测试，页面无调用；原6文件变动已核对，工作区起初干净。
- 两导出交真实Jazzy set_message_fields均AttributeError；现有mission_bridge已正确生成PoseStamped与mask/FilterInfo。保留真实owner，复用现成构造。
- 共线/端点墙接触false；snapshot引用污染undo/redo；1秒期限10秒仍running；等待10秒立即完成；完成耗时2变0。
- 采用Wiki/ROS2 与 FishBot第12/19/20节：原任务身份/终态、源时间与物理评分分开。当前任务只代码和仿真，真实车辆已售。
- 非零逐点等待、无限循环和speed/no_clean不属于既有后端能力；本轮预览可表达，派发/导出必须明确支持范围，不自行另造执行协议。
- 12用户航点加返航形成13个观测点，不能用草稿12点限制构建只读指标；新增无草稿数量限制的polyline度量，派发上限不变。独立审查与SSR反例已覆盖。
- 原mission状态没有started_at/finished_at，时间原本在持久化runs。最终显示按任务ID/地图/相同owner状态匹配原记录，终态只用finished_at，不造新计时owner。实际网页读回38.6秒已验证。
- 重做需跨同版本规则GET保留；确认新版本或新编辑清空，saving/unknown禁止。旧reducer在草稿刚好等于已保存时会把历史清掉，已按相同版本/几何区分。
