# FishBot

## Why / User Intent
一台FishBot一个项目，以本机代码和实测证据为准，包含控制台、ROS、雷达驱动、固件和运维。
## Non-goals
不把全部模块塞进colcon src；不自动公开地图；不删除历史Git；不以静态测试代替实车验证。
## Success
唯一开发根、运行脚本相对本项目解析、依赖来源可查、实测成果可追溯。
## Constraints
Ubuntu24.04/Jazzy、系统Python3.12；保留所有dirty修改和嵌套仓库。约10秒控制延迟仍待诊断。
## Current State
实车新场景局部图已保存，完整覆盖待继续：2026-10-05 已修正两块板的服务器地址，雷达约7 Hz、odom/imu约20 Hz上线；雷达接收定时器泄漏、断线重连和扫描点数变化导致的SLAM丢帧已修复。已实测低速短段直行、转向和主动零速停车，最新地图约6.725平方米自由区域及续建数据已保存。2026-10-05检查点的实车RViz实时视图曾保持打开，此处不代表当前在线状态。用户最新要求保持当前方向前进1米，实际仅前进约4.9厘米后触发前方保护，续试无新增位移；该检查点为零速、无排队动作，但续试的连续新鲜停车反馈未通过，原始时间戳偶发超限。底盘复位后已恢复续建，轮式转角与点云实测转角不一致仍待核实；窄口通过、完整覆盖、实车导航、避障和巡逻均待验收，见plans/fishbot-real-autonomy-20261005/。
2026-10-05：网页三点巡逻、物理箱体移入、减速转向绕障、继续巡航和返航已通过MuJoCo实测；三个巡逻点加返航共四点，约90.94秒，最终位置误差11.64cm且已停稳。取消任务、过期请求、仿真暂停和启动就绪门禁也已验证。入口为tools/fishbot_mujoco.sh web，证据见plans/fishbot-web-patrol-20261004/。此前RPP单点导航、断流停车和旧时间戳命令拒绝基线保留。2026-09-15原样迁移和旧路径兼容保留；本机Git历史未压平。历史实车建图和保存通过，实车恢复定位/Nav2仍未验收。私有成果未新增上传。
## Current Priority
2026-10-07 用户要求接好既有远端。当前开发目录直接对应 `qiaoqiao2521/fishbot-ros2-slam-tools`，后续在本项目根提交与推送；外层工作台和嵌套模块历史保留。本地运维原件与接入记录保存在忽略的 `.local/`；见 docs/REPOSITORY.md。
2026-10-07 用户确认先在虚拟环境实现三点视觉巡检，现已完成：MuJoCo车载RGB→三点导航拍摄→绿灯/红灯/空位像素识别→图文报告→返航。最终整轮73.703秒，九帧带拍摄位姿证据，返航误差12.29cm且停稳；独立超时取消通过。入口tools/fishbot_inspection.sh，仅domain97；见docs/VISUAL_INSPECTION.md。识别限定合成工位，实车相机与巡检尚未验收。
2026-10-06 用户确认直接采用FishBot开源模型，不以现场测量作为前置步骤；连续本地控制、分级限速/停车、触发记录与回放已实现。新入口 tools/fishbot_passage.launch.py 在隔离MuJoCo domain 96完成整段过门、硬停车及取消测试，74项聚焦测试通过；见docs/PASSAGE_CONTROL.md。当前小车充电，本次未操作实车。原domain 93仿真与旧实车脚本保留。接续使用新入口验收实际过门和建图；实车源时间戳、转角反馈、板端断流停车和旧命令拒绝仍需实际反馈验证。
## Knowledge Map
README.md；docs/ARCHITECTURE.md；docs/DEPENDENCIES.md；FISHBOT_STATUS.md；plans/fishbot-jazzy-mapping/。
