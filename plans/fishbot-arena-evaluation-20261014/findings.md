# Findings

当前官方main推荐release/0.3.1；实际HEAD为c7edf3a9d5d8276565208f72422f8f8a0806d6cf。该分支README仍有0.3.0/Sim6.0旧文本；采用实际gitlink/pyproject/uv.lock。

Isaac Lab gitlink 91a0906f93802eb859192dcb0bca879f891e92d6；GR00T gitlink e29d8fc50b0e4745120ae3fb72447986fe638aa6。锁文件Sim6.1.0.0、Torch2.11.0+cu128、Newton1.5.2、MuJoCo/MJWarp3.11.0、Warp1.16.0，Python3.12/Linux x86_64。

Arena仍为alpha。默认uv环境包含完整Isaac Sim；官方runner无条件构造SimulationAppContext/AppLauncher/SimulationApp，--presets newton --viz none不能变成kit-less。

官方Sim6.1支持基线：RTX4080/16GB、32GB RAM、50GB SSD。当前实测RTX3050Laptop/4096MiB、驱动595.99.02；未实际运行，不能把低于基线改写成实测失败。运行前需人类明确接受Isaac Sim/Omniverse许可，材料中的export EULA不构成授权。

官方getting_started_experiment.yaml已有baseline与swap_objects及zero_action、1.5秒episode。新增配置仅取这两个Run并各限1env/1episode。后续映射车臂链时，CompositeTaskBase必须显式顺序与最终状态要求，默认锁存不能保证终点仍留盘。

源码clone默认触发LFS资产下载。已终止本轮owned clone，保留缓存，以LFS_SKIP_SMUDGE恢复官方checkout；准备阶段不继续拉取大资产。旧LeRobot文档0.1.1/Lab2.3/Sim5.1不可作新版本部署依据。

来源：官方仓库及锁定源码 https://github.com/isaac-sim/IsaacLab-Arena/tree/c7edf3a9d5d8276565208f72422f8f8a0806d6cf ，硬件要求 https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/requirements.html ，许可流程 https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_python.html#running-isaac-sim 。

2026-10-14 Colab实际L4预检：GPU23034MiB、驱动580.82.07、RAM55530600kB、磁盘207577022464字节、Ubuntu24.04.4、Python3.13.15、GLIBC2.39。标准ICD目录为空，仅发现Vulkan loader；原生vkCreateInstance=-9(VK_ERROR_INCOMPATIBLE_DRIVER)。没有安装/运行Isaac。安全适配stop实际unassign_completed=true，随后check-connection active_assignments=0。既有浏览器插件只有IAB，Chrome共享proxy blocked；未重启proxy或触碰profile，使用既有Colab CLI授权连接。

官方GCP页同时推荐T4/L4，桌面16GB门槛不是所有云卡的排除标准。A100/H100缺RT仍不支持。Colab本轮失败发生在用户态Vulkan入口，尚未测Arena；匹配宿主驱动的官方用户态图形组件能否补齐仍待核实，不等于要求换平台。

第二轮Colab获用户明确接受NVIDIA软件与Isaac Sim许可。原580.82.07同版.run经过原生archive check，只提取64bit图形库到私有路径，未执行installer或覆盖provider CUDA/NVML。NVIDIA Vulkan设备与两RT扩展实际通过，官方source prepare也通过。uv实际安装351包（Sim6.1.0.0/Torch2.11.0+cu128/本锁版Lab），入口误读uv pyvenv.cfg：字段是version_info而不是普通venv的version。已在本机uv0.11.15真实环境复现并修读回，17项入口检查通过。首轮安装回执拒绝及所有原日志保留，未算20步成功；VM实际unassign且活动0。第三个独立会话继续同一原45分钟预算，未重复请求许可。

T4不以桌面16GiB门槛误拒绝：官方GCP T4为nominal16GB，常见nvidia-smi总量15360MiB；薄入口单独识别T4云配置，仍要求实际图形/运行验收。A100/H100按官方无RT明确拒绝；更大显存不替代图形能力。
