# Findings

- 开始时 HEAD `047ae63`，唯一未跟踪项为固件 `release.sh`，保留根接续审查。
- 现有地图操作是 `/radar`；巡逻在独立 `/simulation`，后者直接使用 Python mission bridge。
- bridge已有串行请求队列、FollowWaypoints确认与未知回执收束；复用其执行所有权。
- 逆向模型中两点/四点区分线/矩形，但几何与用途分别建模；PhonePosition不直接作为ROS米制坐标。
- KeepoutFilter原生无规则版本回执，发布或订阅数量不能单独证明应用；须通过配置与原生costmap读回核验。
- 本机Nav21.3.13 keepout订阅要求可靠、transient-local、depth1；相同filter-info不能周期重发。
- Keepout mask的未知格会跳过，外0/内100；标准障碍膨胀不会自动处理filters。
- 原生worldToMask不处理mask origin旋转，输出mask应轴对齐或明确拒绝旋转地图。
- 涂鸦文档1910=Matter标准服务的推断不采用；官方Matter使用FFF6。本阶段不新增BLE。

- 最终将KeepoutFilter之后的原生InflationLayer作为软代价梯度，mask仅几何和半格对角余量，原车体与RPP碰撞保留。首轮失败及同case复测见progress。
- Nav2清图正常重建过滤器订阅。暂缺查询不作为失效反证；fresh有效global格连续至少3秒证明未应用才取消现有任务，未知/过期/异常/采样孔洞中断计时。
- 文件refresh可能由route/run事务触发，必须将document版本与成功ROS发布版本分开绑定；所有者线程同步重发布，准备mission后再以revision CAS登记所有权。
- 模板保存不产生运动。未知模板保存只保护重复写入，不应额外禁明确派发有效草稿；规则和运动未知仍保护原操作。
- 独立验收client须先等待DDS服务发现再调用。取消接口终态不等于车已静止，完整连续新鲜truth窗口另行验证。
- Native参数radius0.13、padding约0.01；评分采用保守外接圆0.144142，原始`.13`假设不是完整padding评分。采样与分段线性扫掠界不证明未观测连续物理运动。
