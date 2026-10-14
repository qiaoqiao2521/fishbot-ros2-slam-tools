# Arena 组合评测

目标是用同一策略比较不同物体组合的回合结果。使用官方 Arena 的场景、机器人、任务、策略与 ExperimentRunner；现有 MuJoCo/Nav2 继续负责 FishBot 的已验收执行。

## 当前交付边界

源码锁、两Run配置与部署预检已接入项目。尚未安装 Isaac Sim，尚未运行 Arena，也未验证 SO101 策略或模型迁移。本机 RTX3050 Laptop/4GB 低于官方支持基线。用户已选择Colab尝试。L4已实际分配，但原生Vulkan预检失败；尚未启动Arena。实际安装和运行仍需图形驱动完整的GPU目标及明确的Isaac Sim许可接受。

Arena 仍为alpha。锁定 `c7edf3a9d5d8276565208f72422f8f8a0806d6cf`，Isaac Lab子模块锁 `91a0906f93802eb859192dcb0bca879f891e92d6`。实际依赖见 [upstream.lock.json](upstream.lock.json)。分支 README 的部分版本文字滞后，以 gitlink 和 uv.lock 为准，不跟随 main 漂移。

## 能力与验收

[evaluation.yaml](evaluation.yaml) 复用官方getting_started实验，保留baseline和swap_objects两个Run。每Run一个环境、一个回合，固定zero_action、1.5秒物理预算与相同背景；只替换拾取物体和容器。

zero_action让部署验证不依赖神经网络权重。它不证明抓取能力；任务超时或失败是合法评测结果。真实评测验收须读取官方 `arena_experiment_result.json` 的两个Run、每回合成功字段、episode长度和物体组合，并保留逐episode原件与原生报告。安装退出0或20步预检不算这项验收。

后续策略接入使用官方PolicyBase，不另写runner。当前示例是官方DROID；SO101/FishBot embodiment 尚未适配。以后将车臂链映射到CompositeTaskBase时，显式启用顺序子任务，并验证终点货物仍留盘，避免默认锁存把中途成功当终点成功。

## 部署步骤

先在目标机器运行 `./fishbot.sh arena doctor`。该命令只读硬件、源码锁和依赖状态，不初始化CUDA/Kit。它是预检，不替代官方兼容检查与实际运行。

准备源码使用 `./fishbot.sh arena prepare`。源码、子模块、依赖与资产放在用户缓存，项目Git只保存薄入口、配置与锁。准备阶段跳过LFS资产，不安装运行环境，不接受许可。

安装和执行的具体原生命令可用 `./fishbot.sh arena plan` 查看。安装入口转交官方 `uv sync --locked`；预检转交官方policy_runner；评测转交官方experiment_runner。既有输出目录不得覆盖。

安装与运行前，阅读并明确接受 [Isaac Sim/Omniverse许可](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/common/NVIDIA_Omniverse_License_Agreement.html)。入口的 `--accept-eula` 只表示操作者已完成这一决定；自动化不能从这篇说明或粘贴材料推断许可已经被接受。

条件满足且操作者已确认许可后，在目标机器执行：

```bash
./fishbot.sh arena install --accept-eula
./fishbot.sh arena smoke --accept-eula
./fishbot.sh arena evaluate --accept-eula --output /absolute/new/arena-run
```

`--source` 可指定独立官方checkout；`--gpu` 指定nvidia-smi中的物理索引，执行时绑定实测GPU UUID。原生日志写stderr，入口回执写stdout。evaluate要求新目录，并记录源码与评测配置起止SHA，再读官方结果；失败原件不覆盖。此处命令是待执行入口，本轮没有执行这三条命令。

## 官方边界

[Isaac Sim6.1硬件要求](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/requirements.html)：x86_64 Linux、RTX4080/16GB、32GB RAM、50GB SSD。驱动与实际机器兼容仍需检查。低于该基线不等于已实测失败，也不能宣称受支持。

Arena官方runner无条件启动SimulationApp。`--presets newton --viz none`仍使用完整Isaac Sim；不能照搬独立Isaac Lab的kit-less安装宣传。当前部署走原版依赖，不改上游移除Kit。

官方执行、结果和组合语义：[Experiment教程](https://isaac-sim.github.io/IsaacLab-Arena/release/0.3.1/pages/quickstart/arena_experiment.html)、[锁定源码](https://github.com/isaac-sim/IsaacLab-Arena/tree/c7edf3a9d5d8276565208f72422f8f8a0806d6cf)。派生配置保留Apache-2.0声明；原许可证见 [LICENSE.upstream.md](LICENSE.upstream.md)。Isaac Sim许可独立，不包含在Arena的Apache许可证内。

## Colab 实测

2026-10-14使用既有Colab CLI的安全适配，独立申请L4会话。实际环境为L4/23034MiB、驱动580.82.07、Ubuntu24.04.4、GLIBC2.39、Python3.13.15；内存约53GiB，可用磁盘约193GiB。Python3.12应由官方uv锁环境独立安装，不改Colab主Python。

该实例没有发现NVIDIA Vulkan ICD、GLX或RT用户态库。已有`libvulkan.so.1`的原生`vkCreateInstance`返回`-9 / VK_ERROR_INCOMPATIBLE_DRIVER`。这证明该实例当时的Vulkan环境未就绪，不是Arena运行失败，也不证明所有Colab实例都不可用。没有安装Isaac、接受EULA、运行20步或两Run评测。已确认本轮VM解除分配，服务端活动会话为0。

[NVIDIA官方GCP部署](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_advanced_cloud_setup_gcp.html)列出T4和L4云方案；不能单凭桌面显存门槛排除T4，也不能把GCP完整VM支持当作Colab支持。[官方Vulkan排查](https://docs.omniverse.nvidia.com/dev-guide/latest/linux-troubleshooting.html)明确指出nvidia-smi不证明Vulkan可用。下一次尝试须先核对与托管内核驱动匹配的官方用户态图形组件及原生Vulkan，不能换驱动、重启宿主或使用软件Vulkan冒充NVIDIA设备。

Colab只用于有界评测。遵循[Colab FAQ](https://research.google.com/colaboratory/faq.html)的资源与使用限制，不搭建SSH、远程桌面、代理或常驻控制站，不购买新套餐。原始预检与回收证据存本机缓存，不进入Git。

## 有界Colab入口

[colab_preflight.py](colab_preflight.py)只做原生NVIDIA Vulkan/RT预检；成功仍输出runtime_verified=false。[colab_bootstrap.py](colab_bootstrap.py)是Colab临时/content部署适配，复用本项目锁版CLI；必须由操作者明确接受许可后传--accept-eula。它不分配VM、不持有认证，不搭Web服务；VM分配/释放继续使用既有Colab工具。

当实例缺图形组件时，只从官方同版.run提取64bit图形库和官方ICD，使用进程局部路径，不执行系统installer、不替换kernel、不覆盖provider CUDA/NVML。原生NVIDIA和RT预检通过后才继续官方prepare/install/smoke/evaluate。每阶段保留原生日志；总预算最多2640秒，为45分钟VM生命周期预留回收时间。结束下载artifacts.zip与报告并释放本轮VM，不能将脚本完成或Vulkan成功写成Arena物理运行通过。
