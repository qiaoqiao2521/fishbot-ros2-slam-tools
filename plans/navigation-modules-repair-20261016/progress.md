# Progress

## Current
实现、限定验收与独立审查完成，Git交付进行中。保留原类思路和原ROS owner。

## Done
- 原反例均修复；map-zones37、patrol46项行为测试通过。覆盖共线/端点/单点/圆足迹、引用隔离、停留/期限/停表、两点循环、真实Goal、支持范围拒绝。
- 页面使用两个库生成原HTTP任务和规则DTO、几何提示与里程；重做实际可用。原后端发布消息通过标准序列化导出，新增3项真实消息构造/过期版本/发布失败测试。
- 最终349/349前端、类型、lint、domain122构建通过；106项mission通过。反馈1121/1121（control600/mission160/autonomy61/frontend300），零跳过与缺依赖；布局12项、diff与文档相对链接检查通过。
- 私有run-617828f1：1440网页建墙→撤销→等待轮询→重做→显式保存→Nav2全局/局部applied；下载真实info+mask并与独立ROS订阅完全一致；新库HTTP请求只派发1次，两点+返航同UUID终态4；末真值误差0.092496m/0.126759rad，按原0.15m/0.17rad门槛通过，连续停稳≥0.7源秒。
- 390px真实页面完成禁区草稿/撤销/重做，无写请求、无横向溢出或页面异常。实际截图已查看。
- 原试验10份执行/页面源起止一致。随后只改3个前端文件，将只读耗时改配对原runs、撤回不存在的mission时间字段。控制/规则/几何源码不变；追加同一完成UUID的真实网页GET读回38.6秒，零POST，final-source-readback单列。没有将前后两版冒充同一冻结试验。
- 独立复核发现13点观测崩溃和时间字段来源错误，均修复后再读回；最终额外75项复跑通过，无阻断。原生Goal的实际TS输出交真实Jazzy set_message_fields已成功，无动作发送。

## Remaining
仅Git交付。不支持的真实逐点等待、HTTP循环、任意多边形/no_clean/speed规则没有实现或验收；明确拒绝，不静默转换。演练completed不外推ROS/真机成功。

## Retained evidence and runtime
本机证据位于`~/.cache/fishbot/navigation-modules-20261016/run-617828f1/`，含声明/逐帧真值/原生状态/实际导出消息/浏览器/评分/最终源哈希，全部不入库。

122实例有意保留供复核，末任务已终态成功并独立停稳：`fishbot-nav-repair-122-617828f1.service`，invocation `3fcffd2bb32941c2b07174281475326f`，API9072；前端`fishbot-nav-repair-web-5181-617828f1.service`，invocation `ccc71ecc8c8545c0a2c37e451c4dec44`。入口`http://127.0.0.1:5181/simulation`。停止前核对原任务终态及停稳，再按这两个精确user unit停止；不匹配其他服务。原121 unit invocation `18c9bfab583f46fba894606579d88861`/PID366493在本轮前后核对保持；未操作实机、固件或网络。

## Issues
- 首轮类型检查发生在worker替换旧导出测试期间；参数属性与erasableSyntaxOnly冲突已修复，最终完整检查通过。
- 新增export测试首轮fixture缺少真实文档map_id，已修测试fixture后106通过；未放宽生产校验。
- 原只读验收失败样例保留，原视觉11失败和历史物理验收数字不改变。

## Knowledge closeout
already_covered：Wiki/ROS2 与 FishBot第12节已覆盖原UUID/未知不重发和回执分层，第19/20节覆盖真实消息、来源/时间和独立物理评分。本轮沿用；13点/导出与引用修复属于项目协议细节，保存在本计划与MAP_RULES，不重复Wiki。root负责收尾，worker未改共享知识。
