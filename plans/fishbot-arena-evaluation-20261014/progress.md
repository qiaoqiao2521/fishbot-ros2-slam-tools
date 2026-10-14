# Progress

## Current

准备阶段完成，真实Arena部署未完成。当前本机4GB显存低于官方16GB支持基线，尚无用户选择的运行GPU目标，Isaac Sim许可未接受。

## Done

- 已下载官方Arena源码并完成实际prepare。HEAD c7edf3a9d5d8276565208f72422f8f8a0806d6cf、Isaac Lab91a0906f93802eb859192dcb0bca879f891e92d6、GR00T e29d8fc50b0e4745120ae3fb72447986fe638aa6及递归子模块均核对；工作区干净，uv.lock/pyproject SHA匹配。
- 项目增加arena doctor/prepare/plan/install/smoke/evaluate薄入口。实际执行只有源码prepare、doctor与plan；没有uvsync、Isaac导入、运行器、策略权重或收费API。
- 复用官方两Run配置：baseline/swap_objects，共用zero_action/背景/1.5秒源时间，各1env/1episode。PyYAML结构核对与上游共享配置/物体替换一致；这不等于官方环境运行已验证。
- Root独立15/15边界与回执测试通过，fail/error/skip均0，0.917s。检查真实Git身份、缺/改子模块、未知/4GB GPU、未接受许可不派发、旧输出不覆盖、原生结果缺失和False/null保留、安装后元数据读回与隐私偏好保持。全部是离线入口验收，未冒充GPU运行。
- Bash语法、12路径布局、selected文档相对链接与diff检查通过。原生stdout日志改写stderr，CLI stdout为JSON回执，实际prepare/doctor/plan JSON均已读回。
- 实际doctor：源码verified=true，selected GPU为RTX3050Laptop/4096MiB、驱动595.99.02；runtime installed=false、runtime_verified=false、ready=false。已有uv0.11.15与GitLFS3.4.1；未修改它们、网络、GPU驱动或107/114服务。
- 实际smoke缺许可flag退出2，在执行前明确拒绝；未代用户接受EULA。GPU门禁由离线负例与真实doctor分别验证，没有使用accept-eula做真实测试。

## Issues

文章版本已滞后；分支README文字与实际gitlink/lock也有差异。以已锁源码为准。官方runner无条件启动完整Kit，Newton/viz none不能自动变成kit-less。

第一次源码clone触发LFS下载后终止并保留缓存，再以skip-smudge恢复干净checkout；原始stdout保留。本轮正式prepare跳过LFS资产并浅克隆精确子模块。准备输出曾混有Git stdout，现原生日志改写stderr，原件与重新读取的JSON分别保存。源码补丁两次按旧片段未匹配，重新读取冻结文件后才应用，未落入半个补丁。

## Remaining / Next

部署与运行仍pending，owner=root。最短入口：用户提供合适的Linux x86_64/RTX GPU主机或SSH别名；root先读回目标身份、显存、空间和驱动，再请用户具体确认Isaac Sim/Omniverse许可。之后执行install、20步smoke和两个Run的evaluate；必须核对原生episode、组合、终止原因与结果。zero_action失败是策略结果，不改为任务成功。

SO101/FishBot embodiment、真实视觉策略、训练、真机和生产稳定性均未纳入本轮成功声明。固件release.sh按既有阻碍保留，owner=root，接续入口见协同计划Retained work，不执行或提交。

## Evidence

本机缓存~/.cache/fishbot/arena/：prepare-20261014.json、doctor-20261014.json、plan-20261014.json、config-structure-20261014.json、entry-tests-20261014.log和missing-eula-rejection-20261014.json。来源/源码/LFS缓存及硬件UUID、运行日志不入Git。实际Arena结果文件尚不存在。

## Knowledge closeout

updated：root已补写并读回知识库既有Wiki/ROS2 与 FishBot.md第19节的部署/运行链/策略效果区分、实际启动调用链与许可边界；同步Wiki/开发知识入口.md的Arena/Newton免Kit触发词。当前项目状态回源本计划；未把素材或日志复制到知识库，未顺带发布知识库累计变更。

## Git delivery

准备阶段13个已审查文件提交149447f129beca79414a586bc44eacb10030ad52，已推送qiaoqiao2521/fishbot-ros2-slam-tools main，并经GitHub API读回同SHA。此接续记录单独提交；实际GPU部署保持pending，root等待GPU目标与许可确认。固件release.sh仍是唯一未提交保留项，不以Git交付冒充运行完成。
