# Arena 组合评测

目标是用同一策略比较不同物体组合的回合结果。使用官方 Arena 的场景、机器人、任务、策略与 ExperimentRunner；现有 MuJoCo/Nav2 继续负责 FishBot 的已验收执行。

## 当前交付边界

官方Arena运行与回收闭环已在Colab L4实际通过。20/20物理步正常关闭；baseline/swap_objects各1个23步回合，聚合JSON、JSONL、原生timings和对象任务指令一致。39个归档文件逐项校验；上传输入与源码/配置起止一致，VM实际解除分配、活动会话0。复用官方零动作策略，两组任务success均false，不能当抓取能力或训练效果。

本轮同一45分钟窗口中，首次上传超时已回收，修复后serial会话用剩余2159秒；最终生命周期804.445秒，未购买额度或更换kernel。本机4GB GPU未安装Isaac，SO101/FishBot embodiment仍未适配。历史20步后SIGSEGV和末轮取证缺失保留，后续成功没有覆盖它们。

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

`--source` 可指定独立官方checkout；`--gpu` 指定nvidia-smi中的物理索引，执行时绑定实测GPU UUID。原生日志写stderr，入口回执写stdout。evaluate要求新目录，并记录源码与评测配置起止SHA，再读官方结果；失败原件不覆盖。本轮已在Colab实际执行install与smoke；两Run验收必须以实际官方结果为准。

## 官方边界

[Isaac Sim6.1硬件要求](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/requirements.html)：x86_64 Linux、RTX4080/16GB、32GB RAM、50GB SSD。驱动与实际机器兼容仍需检查。低于该基线不等于已实测失败，也不能宣称受支持。

Arena官方runner无条件启动SimulationApp。`--presets newton --viz none`仍使用完整Isaac Sim；不能照搬独立Isaac Lab的kit-less安装宣传。当前部署走原版依赖，不改上游移除Kit。

官方执行、结果和组合语义：[Experiment教程](https://isaac-sim.github.io/IsaacLab-Arena/release/0.3.1/pages/quickstart/arena_experiment.html)、[锁定源码](https://github.com/isaac-sim/IsaacLab-Arena/tree/c7edf3a9d5d8276565208f72422f8f8a0806d6cf)。派生配置保留Apache-2.0声明；原许可证见 [LICENSE.upstream.md](LICENSE.upstream.md)。Isaac Sim许可独立，不包含在Arena的Apache许可证内。

## Colab 实测

2026-10-14使用既有Colab CLI的安全适配，独立申请L4会话。实际环境为L4/23034MiB、驱动580.82.07、Ubuntu24.04.4、GLIBC2.39、Python3.13.15；内存约53GiB，可用磁盘约193GiB。Python3.12应由官方uv锁环境独立安装，不改Colab主Python。

该实例没有发现NVIDIA Vulkan ICD、GLX或RT用户态库。已有`libvulkan.so.1`的原生`vkCreateInstance`返回`-9 / VK_ERROR_INCOMPATIBLE_DRIVER`。这证明该实例当时的Vulkan环境未就绪，不是Arena运行失败，也不证明所有Colab实例都不可用。首次预检没有安装Isaac、接受EULA、运行20步或两Run评测。已确认该VM解除分配，服务端活动会话为0。后续获用户明确许可的实测见下段。

[NVIDIA官方GCP部署](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_advanced_cloud_setup_gcp.html)列出T4和L4云方案；不能单凭桌面显存门槛排除T4，也不能把GCP完整VM支持当作Colab支持。[官方Vulkan排查](https://docs.omniverse.nvidia.com/dev-guide/latest/linux-troubleshooting.html)明确指出nvidia-smi不证明Vulkan可用。实际运行仍须先核对与托管内核驱动匹配的官方用户态图形组件及原生Vulkan，不能换驱动、重启宿主或使用软件Vulkan冒充NVIDIA设备。

Colab只用于有界评测。遵循[Colab FAQ](https://research.google.com/colaboratory/faq.html)的资源与使用限制，不搭建SSH、远程桌面、代理或常驻控制站，不购买新套餐。原始预检与回收证据存本机缓存，不进入Git。

## 有界Colab入口

[colab_preflight.py](colab_preflight.py)只做原生NVIDIA Vulkan/RT预检；成功仍输出runtime_verified=false。[colab_bootstrap.py](colab_bootstrap.py)是Colab临时/content部署适配，复用本项目锁版CLI；必须由操作者明确接受许可后传--accept-eula。它不分配VM、不持有认证，不搭Web服务；VM分配/释放继续使用既有Colab工具。

当实例缺图形组件时，只从官方同版.run提取64bit图形库和官方ICD，使用进程局部路径，不执行系统installer、不替换kernel、不覆盖provider CUDA/NVML。原生NVIDIA和RT预检通过后才继续官方prepare/install/smoke/evaluate。每阶段保留原生日志；总预算最多2640秒，为45分钟VM生命周期预留回收时间。结束下载artifacts.zip与报告并释放本轮VM，不能将脚本完成或Vulkan成功写成Arena物理运行通过。

## 前一窗口的许可后记录（历史）

同版580.82.07官方.run校验通过，仅提取32个私有图形库并保留provider CUDA/NVML；原生NVIDIA Vulkan与RT扩展通过。官方uv安装351包。初次入口误读uv的version_info，修复后官方cube_goal_pose实际完成20/20steps，env.close和报告生成，但SimulationApp关闭SIGSEGV11；该次smoke保持失败，VM已释放。

Isaac Sim6.1会根据继承的JPY_PARENT_PID/ISAAC_JUPYTER_*把独立进程误判为notebook，强制关闭默认fast_shutdown。本项目薄入口仅清除独立子进程的这三个标记，保持父kernel、隐私偏好和官方close流程。18项离线入口检查通过；最后重试在安装阶段限时中断，尚未验证真实退出或两个Run；不使用自加强制退出或跳过关闭来制造成功。详细运行状态回源[progress](../../plans/fishbot-arena-evaluation-20261014/progress.md)。

原45分钟窗口已收尾。所有许可后会话未购买额度；stop与活动0已实际读回。最后重试保留原生超时report，但完整zip未在回收前取得；此前20步后SIGSEGV的原日志完整保留。运行验收仍pending，不能称完整部署成功。接续使用现有入口与锁，需新的明确时间预算；本锁版已接受许可不再重复询问。

## 项目内闭环入口

[colab_run.py](colab_run.py)复用工作台已有ColabCLI0.6安全适配，负责本次单L4的有限调用。默认在相邻SO101项目查找安全适配；可用--safe-cli与--colab-python指定已安装工具。不读取认证文件，不复制浏览器登录态，不创建新认证或调度服务。

操作者已接受本锁版许可后，使用全新输出目录：

```bash
python3 experiments/arena/colab_run.py \
  --output /absolute/new/private/arena-results \
  --budget-seconds 2700 --accept-eula
```

入口先独立确认活动会话0，再申请一次L4。分配与执行不自动重发；contents就绪只做有限只读检查。源码PUT超时后读回完整zip并核对字节数与SHA；相同则继续，明确404才允许有限重传同一bytes，未知或不符不执行SDK。新一轮默认2700秒；同窗口的串行恢复必须显式传剩余预算，不能每次重开计时。

每阶段结束或中断都会保存不可变代际zip。最后原子发布recovery-index.json，标明zip及每个文件的大小/哈希。本机按索引取对应代际，最多三次有限重读；失败原件保留。仅有live报告、旧checkpoint或网页HTML都不能判闭环完成。预留360秒用于取证、释放和独立账户核对；成功、失败、超时都停止唯一owned会话。

原生验收读取真实退出状态、20步日志和context关闭；排除notebook标记与测试force-exit。两个Run各需一个完整原生JSONL，与聚合JSON、对象对应的任务指令和timings一致；源/配置/输出时间绑定。原生success=false或null分别保留，上游没有termination_reason时仍为null。当前1.5秒在默认15Hz下上限23步，不能把旧75步夹具冒充本配置实测。

生命周期的successful只在原生闭环、完整取证、上传输入起止一致、实际unassign和独立活动0均成立时为true。diagnostic_closure_verified只表示诊断与资源已收尾；评测未启动时远端产物为not_applicable。policy_success始终是原生结果，不能由successful=true推断策略能抓取。外部staging资产未由源码Git锁冻结；对象指令核对也不替代独立几何验收。

## 本轮实际结果

新有界入口已完成原生smoke和evaluate，退出均0；未出现SIGSEGV、notebook错误关闭或测试force-exit。基线为Rubik方块→碗，替换组为芥末瓶→木碗；同seed42、同1.5秒预算，两者各23步，任务success=false。原生progress约1/3，只完成objects_settled条件，未完成抓取/放置；它不能当完整成功或候选增益。上游未记录终止原因，保留null；False/23步与超时一致。

原生HTML、完整JSONL/timings、最终校验回执与日志存本机私有cache，不入Git。详细证据、来源、失败与资源回收见[progress](../../plans/fishbot-arena-evaluation-20261014/progress.md)。后续真实策略、更多留出任务和SO101/FishBot适配需各自验收，本轮不自动训练或分配新GPU。
