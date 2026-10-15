# Progress

## Current
实现、限定仿真验收与Git交付完成。实施提交b6b09ea已推送qiaoqiao2521/fishbot-ros2-slam-tools的main。保留全部早期失败和能力边界，不扩展为真机或生产可靠性结论。

## Done
- 核心30项、网关43项、ASR7项通过。全前端曾259通过；最新序号补丁后专项38通过。反馈最终1017通过（control597/mission147/autonomy61/frontend212），零跳过；UI最终小显示修复后将重跑受影响前端。
- 原3误判修复；取消与原UUID、过期/重放、同源、音频来源、未知回执恢复与页面刷新序号已接。已有MissionBridge补绑定ID和单调任务期限；没有语音Twist发布者。
- 官方Vosk中文small模型本机CPU可用，真实音频预检与识别失败均保留。录音由用户显式操作，本轮只使用私有合成输入，不开启真实用户麦克风。
- 实际121导航试验runtime-nav-250b9afc：拒绝不动、前进0.4m（2.73cm物理末误差）、实际Vosk转写左转90度、返航（11.45cm）通过原生UUID终态与独立真值停稳；后续一米目标正确几何拒绝，原整体报告false保留。
- runtime-supplement-374d1620使用预检可通的后退0.4m补验运动取消与原任务0.8s期限取消，两项通过；原ROS状态5、独立连续停稳0.7源秒、起止五源SHA一致。它是独立补测，不冒充同一版本整批6/6。
- runtime-transport-4ae185fb通过voice装货运输+原cooperation oracle：原三动作终态4，完整抓放/运输/停车独立评分true，232.676墙秒，原6文件起止一致；不改变旧56例或11失败。
- 最新全前端261/261、类型、lint、domain121构建通过；布局12项通过。voice install入口实际复验固定模型校验成功，不启动任务。
- browser-1792079893513通过1440/390文字/上传/TTL/失焦卸载轨道关闭与零execute；browser-recording-1792081320846另通过正常stop→真实WebM→Vosk，轨道ended、执行0。截图已实际检查，无横向溢出或页面异常。
- 最终runtime-backup-e2bfef4e四项全通过、20.692墙秒，九份执行/前端源起止一致。后退20cm实际投影-0.214654m，位置误差1.465cm、朝向保持，原BackUp UUID终态4。网页刷新后显式预览/确认只派发一次，序号从服务端续接，Nav2终态4，末误差1.039cm。
- 同一最新回合运动取消与原owner0.8秒期限取消，分别取得原BackUp UUID终态5；独立连续停稳均超过0.7源秒。正常结果使用原导航0.15m/0.17rad门槛，不冒充视觉停靠资格。
- 最新反馈1030/1030（control600/mission157/autonomy61/frontend212）、零跳过/缺依赖；全前端261、类型/lint/build、布局与diff检查通过。独立Agent复跑核心/ASR/网关83及mission103，未发现阻断项。
- 完整运输使用ideal工位观测，货物位移1.789525m，完整足迹违例/禁止接触0，连续交接成立；停车plant guard启用约6.48源秒、触发0，单独保留，不宣称纯视觉精度。

## Issues and retained evidence
- 首个runtime-nav-40abde8a监视器订阅了不存在的odom真值话题，15秒超时、零派发；改读实际FreeJointStateArray后另建目录，不重写失败。
- 首次反馈partial：运行脚本方式缺项目根sys.path导致两个新package测试未导入；补显式checkout路径后1017通过。旧feedback.json保留。
- 首次网页QA时5180入口未运行、零操作退出；根只在确认空闲后起本轮5180服务。第二次QA因过期提示重复导致定位器严格冲突，页面无运动；去除重复显示后新QA继续。前端同时将转角按度展示。
- 小模型五句神经合成预检仅3句意图匹配、2句错误拒绝；不调谐音映射，不宣称生产识别准确率。TTS模型许可Unknown，全部模型与素材不分发。
- 共享上游API之间没有全局原子锁；本轮使用voice单写的独立profile，不同时运行两个物理世界。回充adapter未配置，明确禁用；工位停靠不冒充充电成功。
- 后退原派发是后方航点，默认RPP不倒车，实际可能先旋转。原补测只证明取消/期限，不证明倒车语义；改用原生BackUp后另冻结验收，不回写旧记录。
- 10月16日00:07系统oomd结束了本轮旧5180与9094服务，日志保留；恢复前核对端口空闲，新服务单列。未修改系统OOM策略或清理其他应用；不把服务恢复当任务恢复。

## Remaining
本轮无剩余实施项。真实人声/噪声/口音准确率、实际充电adapter与跨两个独立上游的原子全局仲裁没有验收，不宣称完成。

## Next
用户可在空闲demo连接语音服务并预览任务。后续按真实使用反馈另立验收；工作台不自动派发。

## Runtime and evidence
私有证据根为`~/.cache/fishbot/edge-voice-20261015/`，包含本轮各声明/评分/源哈希/浏览器报告；录音与模型不入库。原nav/supplement/transport及最新backup实验实例均已停止，末任务终态与连续停稳先确认；最新实验unit读回inactive/MainPID0/空ControlGroup。

为用户查看单独保留空闲demo：`fishbot-voice-demo-121-20261016.service`（invocation 18c9bfab583f46fba894606579d88861，domain121/API9071）、`fishbot-voice-demo-gateway-9094-20261016.service`（2a29f7b7e94148f7a72196707dfb7a7e，API9094）、`fishbot-voice-web-5180-20261016.service`（7b111f56c85244f9b2030a4596bf2f1f，5180）。三者均为本轮拥有的user service；demo状态已读回ready/idle、没有任务。入口`http://127.0.0.1:5180/workbench#workbench-voice`。停止时先核对任务终态和停稳，再`systemctl --user stop`这三个精确unit；不匹配其他FishBot服务。

原107/114未被本轮命令操作；本轮开始没有捕获其有效PID基线，因此不宣称独立证实原进程全程存活。固件release.sh保持原样，没有执行。

## Knowledge closeout
already_covered：既有Wiki/ROS2 与 FishBot第12节已覆盖原UUID、未知不重发与分层终态，第19/20节覆盖来源/双时钟/物理评分。本轮沿用这些规则；语音合同与当前测试结果保存在项目，不重复知识页或创建新规则库。root已读回对应段落，workers不改共享页。
