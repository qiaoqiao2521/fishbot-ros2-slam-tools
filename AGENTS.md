# FishBot project

先读 PROJECT.md，再按需读 FISHBOT_STATUS.md、tools/FISHBOT_STACK_RUNBOOK.md 和 docs/ARCHITECTURE.md。
规划、导航反馈或重复故障涉及用户体验时，先读 docs/USER_FEEDBACK.md 的相关条目；核对已有实现，再确定本次缺口。原始历史用 TraceMesh 定点检索，不把记忆当作已验证证据。
本目录是唯一开发入口，旧ros2路径只是兼容链接；不编辑repo-revival或_public_release的历史快照。
本目录直接跟踪 `https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools.git` 的 `main`。先核对 `git rev-parse --show-toplevel`，不要再把成果只提交到外层工作台仓库。远端接续与本机保留项见 `docs/REPOSITORY.md`。
不能在本项目根统一colcon build；只选择对应workspace。嵌套Git和未提交内容仍保留，不得删除或重置。
离线布局检查用 `./fishbot.sh check`；用户反馈回归用 `./fishbot.sh check-feedback`。两者都不证明实车可动；缺失依赖和跳过项目必须披露。
实车已售，本次建图与导航阶段已由用户确认完成。当前任务限于项目代码、文档和虚拟环境；旧实车待验收项是历史边界，不是恢复实体操作的授权。
地图、固件备份、标定和网络配置默认本地保留，不自动推送。固件刷写与实车验收分别判断，当前边界见 FISHBOT_STATUS.md。
当前迁移证据：../../plans/hardware-consolidation-20260915/。
