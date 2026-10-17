# Progress

## Current
实现、独立审查与限定验收完成；root正在提交推送。

## Done
- 起始HEAD eea5d51，工作区干净。只读核对目录、打开fd和有限抽样；无删除或服务重启。
- 90GB历史文件已由用户清理，本轮不计作释放空间成果。
- 诊断默认关闭；显式启用默认墙钟2Hz、8MiB×4部分。19项真实文件/字节轮转/IO异常边界通过；原stamp/sequence保留，源发布不降频。构造拒绝旧路径，运行失败仅停写诊断，错误持续可见。
- 独立证据15项通过：逐条收到记录不抽样，按实际manifest内容保留首份完整身份与后续引用；固定1000条夹具8,559,480→370,766B，仅该夹具减少95.668%，动态字段逐项相等。默认900秒/1GiB，超限/JSON/写/flush/close失败不完整。新采集完整性门禁先于JSON尾部解析，正式false报告关闭四项最终验收声明，原物理门槛保持。
- 96项日志/证据/oracle/launch/acceptance定向测试通过；22项状态/控制合同与实际116域QoS测试通过；反馈1223/1223（control637/mission160/autonomy61/frontend365），零跳过/缺依赖。compileall与diff检查通过。
- 最终实际ROS面板run-1a6cefd0：独占124关闭日志，收到299帧且无physics文件；125按2Hz记录14条、轮转6次、保留2片98,286B≤131,072B测试上限，实际ROS收到302帧，完整source.manifest保留；126单条超过1KiB时停写、收到295帧、车始终hold，节点按7秒期限正常结束。三组均无动作发送。
- 同一125面板独立observer收到105条physics/共742条记录，104次manifest去重，1,514,081B，capture_complete与collection gate通过；没有派发任务，因此原物理任务评分仍失败。126的1KiB观察预算写3条954B后正确停止，正式false score且physical_evaluation_performed=false；不将日志测试冒充运输成功。
- 最终6份执行/采集源起止与当前完全一致。初版run-90c29a27在计时说明字段补充前已通过并保留，最终面板另存，不混用源码。reader为BEST_EFFORT，不宣称收到的源序列无缺口；capture_complete只覆盖本收集器收到的offer。
- 原121 invocation18c9bfab583f46fba894606579d88861/PID366493、122 invocation3fcffd2bb32941c2b07174281475326f/PID525213保持。124/125/126及116定向进程全部owned退出，未停止原服务、改网络或操作实体。

## Remaining
Git交付与远端读回。实施无剩余项；RGB/相机素材不在本轮32MiB诊断限额内，独立证据不得换成滚动诊断。

## Issues
- 首轮QoS旧断言要求record_flush单独正计数，标准库emit已内含flush，断言失败。补充实际计时语义并检查合并阶段后22项通过；没有放宽源进度、QoS或新鲜度门槛。
- 初次新增gate测试误调用被CLI重绑的base.score，改用固定original_score别名后通过。独立审查发现最终验收布尔与passed不一致、坏尾行缺正式报告，两项均已修复并回归。
- 旧ROS_LOCALHOST_ONLY弃用提示保留，本轮不改变运行网络。历史90GB文件已不存在，增长估算只基于三份其他历史文件各首2行，不能反推原文件精确时长或全程平均。

## Next
新演示使用默认配置。需要诊断才显式record_state:=true；需要完整评分，使用独立observer的新目录和有限预算。使用说明见docs/COOPERATION.md，不自动重跑历史任务。

## Knowledge closeout
updated：root在Wiki/ROS2 与 FishBot第17节追加滚动诊断/完整证据、字节/时长预算、静态身份去重、半写与最终声明约定；Wiki/开发知识入口增加对应触发词。两段按原句读回，保留两页原有dirty，不将独立知识库其他工作混入本项目提交。

## Evidence
本机`~/.cache/fishbot/cooperation-log-budget-20261017/`保存实际脚本、两轮源/状态/timing/日志与观察器失败报告、反馈JSON。最终目录run-1a6cefd0，前一版run-90c29a27单列。仅约数MB新测试产物，不入Git。旧大日志没有在本轮重新生成或删除。
