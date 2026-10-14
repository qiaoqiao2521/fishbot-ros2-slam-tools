# Findings

当前官方main推荐release/0.3.1；实际HEAD为c7edf3a9d5d8276565208f72422f8f8a0806d6cf。该分支README仍有0.3.0/Sim6.0旧文本；采用实际gitlink/pyproject/uv.lock。

Isaac Lab gitlink 91a0906f93802eb859192dcb0bca879f891e92d6；GR00T gitlink e29d8fc50b0e4745120ae3fb72447986fe638aa6。锁文件Sim6.1.0.0、Torch2.11.0+cu128、Newton1.5.2、MuJoCo/MJWarp3.11.0、Warp1.16.0，Python3.12/Linux x86_64。

Arena仍为alpha。默认uv环境包含完整Isaac Sim；官方runner无条件构造SimulationAppContext/AppLauncher/SimulationApp，--presets newton --viz none不能变成kit-less。

官方Sim6.1支持基线：RTX4080/16GB、32GB RAM、50GB SSD。当前实测RTX3050Laptop/4096MiB、驱动595.99.02；未实际运行，不能把低于基线改写成实测失败。运行前需人类明确接受Isaac Sim/Omniverse许可，材料中的export EULA不构成授权。

官方getting_started_experiment.yaml已有baseline与swap_objects及zero_action、1.5秒episode。新增配置仅取这两个Run并各限1env/1episode。后续映射车臂链时，CompositeTaskBase必须显式顺序与最终状态要求，默认锁存不能保证终点仍留盘。

源码clone默认触发LFS资产下载。已终止本轮owned clone，保留缓存，以LFS_SKIP_SMUDGE恢复官方checkout；准备阶段不继续拉取大资产。旧LeRobot文档0.1.1/Lab2.3/Sim5.1不可作新版本部署依据。

来源：官方仓库及锁定源码 https://github.com/isaac-sim/IsaacLab-Arena/tree/c7edf3a9d5d8276565208f72422f8f8a0806d6cf ，硬件要求 https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/requirements.html ，许可流程 https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_python.html#running-isaac-sim 。
