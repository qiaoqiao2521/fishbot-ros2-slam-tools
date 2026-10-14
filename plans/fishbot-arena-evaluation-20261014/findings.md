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

第三轮uvfix：官方cube_goal_pose完成20/20物理steps（约2.4s），CUDA场景、Franka articulation、动作与观测实际初始化。env.close和空episode报告已生成，但SimulationApp关闭时SIGSEGV11；smoke不通过，两Run尚未执行。不能以20步覆盖进程失败。VM已解除分配，活动0；只保留正式日志。

官方Isaac Sim v6.1.0（7c206f75bdadd9e05fc457f19863ca4c3f0cb693）检测JPY_PARENT_PID时设置ISAAC_JUPYTER_PYTHON_PACKAGE，再根据任一ISAAC_JUPYTER_*存在认定notebook，强制fast_shutdown=False。本次日志出现相同警告。薄入口现只清除独立子进程的这三个标记，不改父kernel、官方代码或退出逻辑；不使用测试专用跳过close、FORCE_EXIT或手写os._exit。18项入口测试通过，覆盖实际派发env与父环境保持。该触发链是已核实事实，不能单凭源码认定全部SIGSEGV根因已修复；最后terminal会话须实际正常退出后才算通过，仍共享首轮许可后45分钟总窗口。

关闭模式来源已由Root实际读取三份官方v6.1.0源码并重算SHA：package init c6f9f064b9dd5a9fca8b52cb5c94484d0f334ff82ded06e525e6edc0196a3469、simulation_app init b32081c9c5e4bcd37bc7e041aabad1b08e451ac6d64e43a4e77873cce59fd6ee、simulation_app body c2a2173be57abac20ef97f81b80d58319c94c9a4017c98709f8d13489ad0b746。独立审查18/18通过。原始官方文件缓存不入Git；公开定位：https://github.com/isaac-sim/IsaacSim/blob/v6.1.0/source/python_packages/isaacsim/__init__.py 和 https://github.com/isaac-sim/IsaacSim/blob/v6.1.0/source/extensions/isaacsim.simulation_app/isaacsim/simulation_app/simulation_app.py 。

terminal最终Vulkan/RT通过，install因剩余阶段395.675s上限中断，未进入smoke/evaluate；完整zip未在本机回收前下载，final live report已保留。stop真实解除分配，活动0。已验证子进程误继承模式与离线修复，但缺真实关闭复验；仍不能认定SIGSEGV已实际修复。原窗口耗尽后未再分配GPU。

完善闭环审查：旧result_readback接受最小两段JSON、重复episode或错误run/seed/index而不核对原生JSONL；runner-receipt在最终验收前落盘，缺最终通过/失败结果。官方episode JSONL已有job_name/env_id/episode_in_env/seed/success/episode_length/language_instruction/timestamp/progress。当前任务默认15Hz，1.5秒源时间上限23步；官方不输出termination_reason，False/23只可称与超时一致。HTML在零episode时也可生成，不能单独证明评测完成。

末轮取证失败发生在远端已经终态而本地exec仍pending，直到local cleanup预留截止，错误路径跳过zip下载。新有界入口须按远端终态进入恢复，检查zip发布后的index，成功/失败/超时都先恢复再停止唯一ownedscope并独立读回账户状态。只证明本轮 owned 释放与账户活动数，不杀其它会话。

新窗口首次实际分配L4成功，源码zip上传PUT在25.847s ReadTimeout，尚未启动remote exec。原控制器随后只取得artifact路径404，88.948s后实际stop成功、独立活动0。该失败发生在传输，不是Arena物理/关闭失败。补丁将先确认contents就绪，PUT超时后GET同一文件核对完整zip SHA；已存则继续，明确404才重传相同bytes；无exec时取证不适用，保存本机诊断即可。后续serial重试只用此新窗口余额，不重开2700秒。

本轮成功复验：SDK默认独立进程关闭路径下20步正常退出0，无原SIGSEGV和notebook警告；两Run各23步、false、progress约1/3且仅objects_settled事件。原生JSONL/汇总/timings/配置对照通过；39成员manifest通过，input五源起止一致；804.445s后回收，独立活动0。初次传输失败与前一窗口关闭失败保留，没有通过新观察改写历史。完整源/结果证据回源progress与本机cache。
