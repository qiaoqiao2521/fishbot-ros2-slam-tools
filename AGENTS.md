# FishBot project

先读 PROJECT.md，再按需读 FISHBOT_STATUS.md、tools/FISHBOT_STACK_RUNBOOK.md 和 docs/ARCHITECTURE.md。
本目录是唯一开发入口，旧ros2路径只是兼容链接；不编辑repo-revival或_public_release的历史快照。
本目录直接跟踪 `https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools.git` 的 `main`。先核对 `git rev-parse --show-toplevel`，不要再把成果只提交到外层工作台仓库。远端接续与本机保留项见 `docs/REPOSITORY.md`。
不能在本项目根统一colcon build；只选择对应workspace。嵌套Git和未提交内容仍保留，不得删除或重置。
离线检查用 `./fishbot.sh check`，它不证明实车可动。不得绕过新鲜odom安全门；延迟问题未解决，软件停止不是物理急停。
地图、固件备份、标定和网络配置默认本地保留，不自动推送。固件安全补丁未烧录，不能声称已生效。
当前迁移证据：../../plans/hardware-consolidation-20260915/。
