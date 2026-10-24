# 重构进度

## 2026-10-24 — SO101 Carry接续入口收口

Current：复核并接续原八个Carry在途文件，未改Drone离线工具或Mint。根读当前diff，原runtime五项测试新跑通过；既有56项Jest、生产构建和13项无运动浏览器QA所涉前端源码未变（a433d1e至59e5578无workbench源码改动），复用原证据，不与后台Blender抢渲染。

Done：原5186服务已退出、无监听，原持久化SO10113／Drone25任务均终态；按原环境与入口新启node服务，没有kill旧PID。实际SO101 runtime ready=true/resume_carry=true，Drone ready=true/resume_carry=false；原全部任务ID保留，主页与main／Carry chunk按原构建实际服务。向原SO101终态任务接续返回409、Drone不支持返回405，均无新marker或任务。原件在apps/fishbot-control-station/workbench-review-tests/output/carry-handoff/live-api-readback.json。

Evidence：SO101独立仓已固定d93d60f完成原物理resume pass、waiting取消与原timeout两fail保留；源码后续仅P0定位诊断改动，未改Carry／物理函数。这里的实际API检查只验就绪与拒绝，没有触发新抓放或证明浏览器按钮到物理的完整接续回合；不把fixture UI与云端输入标记拼成一次真实网页验收。

Remaining：根接实际原任务的HTTP继续／取消与物理全过程，保留原90sim120wall／244／1mm及全部回退；六技能halt、同世界恢复、20＋20仍未完成。Drone三旧文件及native-session两新文件保持其原owner在途，不混入Carry提交。Knowledge=already_covered，沿用Wiki§20的交接／动作／晋级分列。

## Current

2026-10-18：P0已交付，P1运行合同完成并通过隔离服务/浏览器验收。P2共享工作面开始拆分；P3–P6待实施。原ROS进程保留；5180/5181是共享源码的Vite开发服务，前端随源修改HMR。

## Done

- 已读项目AGENTS、PROJECT、ARCHITECTURE、DECISIONS、USER_FEEDBACK、WORKBENCH及SpecMesh v1.1。
- 已核对当前Git起点与干净工作区；保护嵌套项目与旧运行实例。
- 已将cy源码核验、34项限定解析测试、商业代码缺陷和本地真实页面观察写入findings。
- 已写目标、跨层范围、用户行为合同、迁移/回退、性能和真实ROS验收入口。
- 根Codex串行持有计划；内部Agent只读审查底层边界和开源组件选择。
- 已更新PROJECT、README、ARCHITECTURE和DECISIONS。独立P0评审无阻断；建议的服务端唯一owner、事件gap对账及UI计时边界已纳入计划。
- 已核官方Dockview许可/可见性生命周期、Three/URDF加载器与Foxglove嵌入边界；选型仅为实施决定，未宣称安装兼容通过。
- 已更新研究根PROJECT与现有三文件索引；没有建立第二份实施计划。
- 最终文档检查：本仓7文件80个本地链接（41个唯一目标）有效；研究根4文件23个本地链接（12个唯一目标）有效；两仓diff检查通过。独立评审无阻断项。
- 已核对qiaoqiao2521账号、既有目标仓库身份和fetch/push地址；交付前fetch确认本地与远端main一致。本轮只提交规划与索引，不以文档检查代替应用测试。

## Remaining

- P2：常驻业务owner、Dockview桌面四槽、手机画布与底部面板。
- P3–P6：按task_plan继续接回编辑/任务/渲染/底层和真实运动验收。P1只读服务验收不代表这些阶段完成。

## Issues

- 商业静态样本包含不可达校验与悬挂加载错误路径，需参考行为后由自有实现验收。
- 现有接口对“成功”的层级不一致，迁移前必须显式映射；不能统一成一个布尔值。
- 原56视觉面板11失败保留，未用此次规划改判。

## Knowledge writeback

`already_covered`：采用知识库FishBot第17–20节及CapMesh复用/平行重写经验。当前新增内容属于本项目重构范围和商业采纳矩阵，保存在本计划；没有新增通用知识页。

## Next

根Codex实施P2。先把页面业务owner与四槽视图分离，保持owner不随面板生命周期重建。已有动作方法、互斥与未知回执先复用；移动端不缩小桌面三栏。

## P1 实现与验收

- 四服务RuntimeDescriptor、可选进程身份检查、只读能力表、连接代次隔离已接入。新客户端跨重启写入被409明确拒绝；旧客户端保持兼容。没有新增跨owner运动锁。
- Java五资源独立校验/来源、SSE实例与序号、代次切换重读、畸形事件恢复已实现。Java流256条有界缓冲，最后订阅退出后仍允许新订阅，异常日志限频。
- 三任务页增加提交/原生/清理停稳/独立评分分层证据。协同事件按instance/episode/task对账，缺号显示缺口。原任务能力缺失明确呈现，不补造原生成功。
- 回归：反馈control637、mission160、autonomy61、frontend365项通过（离线）；布局12路径通过。后端定向Python256项与Java41项通过，独立CMake安装布局与系统Python导入通过。最终前端515项通过，生产构建和lint通过；仍有538kB级入口包体积提示，P2/P4按模块拆分，不调高阈值掩盖。
- 真实服务：隔离domain127 mission节点9097，Java offline8087，Vite5182。身份/响应header一致，旧实例POST409发生在业务前，mission任务状态不变。Java SSE序号和重新订阅实际浏览器通过。
- 浏览器：1440×900、390×844合同样本，分域/未知身份/事件缺口与补齐/零写入通过；实接Java五资源全部接纳，初次打开无写请求。截图只证明这些流程，不是视觉最终验收。
- 私有证据：`~/.cache/fishbot/workbench-rebuild-20261018/`，`actual-runtime-result.json`、`browser-result.json`、`browser-actual-result.json`。不提交日志、样本截图和运行JAR。
- 修正：初次测试只覆盖单次SSE订阅，实际重开暴露autoCancel；另修身份首次发现导致快照stale、畸形高序号推进水位、明确409拒绝误转unknown。首次CMake误选Python3.11缺catkin_pkg，显式系统Python后通过，未改全局环境。
- 没有运行MuJoCo运动、抓放或新物理评分；没有修改控制算法或旧56例结果。独占9097/8087/5182暂保留供P2只读集成，根负责最终清理；原9071/9072/9094进程未替换。
