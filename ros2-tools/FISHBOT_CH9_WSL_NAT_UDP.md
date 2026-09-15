# FishBot 第 9 章（9.0.3）UDP 联通两种方案（WSL Relay / Docker Desktop 端口映射）

> 历史记录，非当前启动指引。2026-09-06 起本工作台使用 Ubuntu/Jazzy 原生链路；下文“当前/推荐/稳定”均指 2026 年 3 月当时的 WSL 环境。不要照此执行 Docker 重建或 fishbot.sh start；当前入口见 FISHBOT_STACK_RUNBOOK.md 与 fishbot_stack.sh help。保留本文用于历史故障追溯。

目标：FishBot（udp_client）通过 WiFi 向 micro-ROS agent（udp4/8888）通信。

## 2026-03-22 当前稳定方案（已实机跑通）

这份文档最开始主要处理的是 `UDP 8888` 联通问题；现在这套环境已经往前走了一步，**当前默认稳定方案**如下：

- 网络：WSL2 **镜像模式**
- FishBot 板子参数：
  - `wifi_ssid=MuqiaoBot`
  - `wifi_pswd=muqiao123`
  - `udpserver_ip=192.168.50.182`
  - `udpserver_port=8888`
- Agent：`fishbot_agent_plus:humble`
- 容器对外端口：
  - `8888/udp`：micro-ROS agent
  - `9090/tcp`：rosbridge websocket

核心原因：
- 只把 micro-ROS agent 跑起来还不够；如果上位机后端连的是 **另一个** rosbridge（例如 WSL 主机里单独起的 rosbridge），就会出现：
  - 前端按钮有请求
  - 后端 API 返回 200
  - 但真机不跟着动，或者状态始终不更新
- 正确做法是：**让 rosbridge 和 live agent 在同一个容器里**，这样上位机连到的就是 FishBot 当前真实所在的 ROS 图。

当前推荐启动方式：

```bash
FISHBOT_DOCKER_BIN=docker.exe /home/muqiao/桌面/dev/ros2/tools/fishbot.sh start
FISHBOT_DOCKER_BIN=docker.exe /home/muqiao/桌面/dev/ros2/tools/fishbot.sh status
```

当前脚本行为已经更新为：
- 默认镜像：`fishbot_agent_plus:humble`
- 自动校验容器是不是旧镜像 / 旧端口映射
- 如果不是当前要求的容器，会自动重建
- 容器启动后会自动在容器内拉起 `rosbridge_websocket`

当前验收标准：

```bash
curl -s http://127.0.0.1:8080/api/v1/connection
```

期望结果至少满足：
- `rosbridgeConnected=true`
- `robotOnline=true`
- `statusMessage=connected`

容器内验收：

```bash
docker.exe exec fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 topic list'
```

期望至少看到：
- `/cmd_vel`
- `/odom`
- `/imu`

如果你后面再遇到“前端按钮没反应”，先不要先怪前端，先查这三件事：
- 小车是否还在线、是否重新上电
- `fishbot_agent` 是否还是 `fishbot_agent_plus:humble`
- `/api/v1/connection` 是否还是 `connected`

WSL2 NAT 的限制：FishBot 这类局域网设备通常 **无法直连** WSL 的 `172.22.x.x` IP。

你可以选两种方案：

1) **Windows UDP Relay → WSL**（适用于你能在 WSL *原生* 起 micro-ROS agent 的情况）
2) **Docker Desktop 端口映射（推荐）**（完全不需要 Relay/WSL IP）

> 实测：如果你用的是 Docker Desktop（`docker version` 里 Server 显示 `Docker Desktop`），推荐直接用方案 2。

> 说明：这里说的“转发/代理”是 **UDP 转发**，跟 HTTP(S) 代理（Clash/mihomo）不是一回事。
> 你在 WSL 里“再开一个代理”只能影响 `apt/git/curl/docker pull` 这类出网请求，**不会解决 FishBot↔WSL 的局域网 UDP 可达性**。

## 为什么默认推荐“端口映射”（并说明 Relay→WSL 为什么经常走不通）

结论：
- 在 **Docker Desktop 引擎** 场景下，默认推荐 **方案 2：Docker Desktop 端口映射**。
- **方案 1：Relay→WSL** 只有在你能在 WSL **原生**起 `micro-ROS agent`（真正监听在 `WSL_IP:8888`）时才靠谱。

原因（这次踩坑的核心点）：
- WSL2 默认 NAT：FishBot 这类局域网设备通常无法直连 WSL 的 `172.xx`。
- 方案 1 的链路需要满足：`Windows:8888 -> (Relay) -> WSL_IP:8888` 这一跳里，**WSL_IP:8888 必须真的有 agent 在监听**。
- 你现在用的是 **Docker Desktop 引擎**：如果 micro-ROS agent 是用容器跑的，那么即使你在 WSL 里执行 `docker run --network host ...`，这个 “host” 往往也是 **Docker Desktop 的 Linux VM**，不是 WSL 自己的 `172.xx` 网络栈。
  - 现象就是：Relay 能看到 `[cli->wsl] 16B ...`（包确实转发到了 WSL 的 `WSL_IP:8888`），但 `/cmd_vel`、`/odom` 依旧不出来（因为 agent 其实没在 `WSL_IP:8888` 上监听/建 session）。
  - 这不代表“Relay 必然不行”：如果你把 micro-ROS agent **原生安装/运行在 WSL**（或使用能真正绑定到 WSL 网络栈的方式），让它确实监听在 `WSL_IP:8888`，那么 Relay 这条链路是可以工作的。
- 方案 2 的链路是：`FishBot -> Windows(WLAN_IP):8888 -> Docker Desktop 端口映射 -> 容器内 agent`
  - 这条链路**不依赖 WSL IP**，稳定性最好，也最省心。

## 0) 先把“刷机/写入参数”搞定（优先级最高）

> 只要串口写入失败，后面 UDP/ROS2 都不用看了。先保证能稳定对主控板写入固件/参数。

### 0.1 Windows：确认串口号（CH340 / COMx）

- 设备管理器 → 端口 (COM 和 LPT) → 找到 `USB-SERIAL CH340 (COMx)`，记下 `COMx`

### 0.2 Windows：防止串口被占用（最常见致命问题）

**必须关闭**任何可能占用串口的程序（包括但不限于）：
- VS Code（含 PlatformIO、串口监视器/插件）
- 任何串口助手（PuTTY/TeraTerm/串口调试工具）
- 已经打开的 `fishbot_tool`


如果 `fishbot_tool` 日志里出现类似 “`sudo chmod 666 COM5` / `dialout`” 的提示：
- 这是 **Linux/WSL 的权限提示**，在 Windows 上无效
- Windows 上真正的问题通常是 **端口被占用** 或 **没有管理员权限**

### 0.3 Windows：用管理员权限运行 fishbot_tool 再刷机

- 右键 `fishbot_tool` → **以管理员身份运行**
- 选择设备类型（如“FishBot 二驱主控板”）→ 选择 `COMx` → 先点“读取/连接”
- 能稳定读到参数后再点“写入/烧录/更新固件”

> 若仍提示“打开串口异常”，先拔插 USB 再试；还是不行就重启 Windows（串口被占用时这是最快的兜底）。

### 0.4（推荐）把 CH340 串口转发进 WSL：彻底绕开 Windows 串口“权限/占用”坑

适用场景：
- Windows 上 `fishbot_tool`/PlatformIO 经常提示串口打开失败、权限不足、端口被占用
- 你想把“刷机/写参数”统一放在 WSL 里做（更可控）

核心思路：用 `usbipd-win` 把 `USB-SERIAL CH340 (COMx)` **attach 到 WSL**，让 WSL 里出现 `/dev/ttyUSB0`。



## 方案 2：Docker Desktop 端口映射（推荐；不需要 Relay/WSL IP）

核心思路：让 Docker Desktop 在 **Windows** 上直接监听 `0.0.0.0:8888/udp`，把数据映射进容器里的 `micro-ros-agent`。
这样 FishBot 只需要打到 Windows `WLAN` 的 IP，不需要你维护 WSL IP，也不需要 UDP Relay。

### 2.1 先停掉 UDP Relay（如果之前开过）

> Relay 会占用 Windows 的 `:8888/udp`；不关的话，Docker 映射会冲突/不稳定。

- 在 Relay 的 PowerShell 窗口按 `Ctrl+C` 停止

### 2.2 Windows：确认 WLAN IP（FishBot 要填这个）

```powershell
Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "WLAN" | Select-Object IPAddress
```

把这个 IPv4（例如 `192.168.14.172`）写进 FishBot：
- `udpserver_ip = 192.168.14.172`
- `udpserver_port = 8888`

### 2.3 Windows：放行 UDP 8888 入站（一次性）

管理员 PowerShell：

```powershell
New-NetFirewallRule -DisplayName "FishBot UDP 8888 (Docker)" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 8888 -Profile Private
```

### 2.4 WSL：启动 micro-ROS agent 容器（关键命令）

> 你不一定需要每次都 `rm` / `--rm`：  
> - **临时跑一把**（前台看日志、Ctrl+C 退出）：用 `--rm -it`  
> - **长期稳定用**（Docker Desktop 管理容器/开机自启/只装一次键盘包）：不要 `--rm`，建议 `-d --restart unless-stopped`

#### 推荐：用一键脚本（避免“终端残留/命令换行/名字冲突”）

仓库已提供脚本：`tools/fishbot.sh`（在 `/home/muqiao/桌面/dev/ros2` 下执行）：

```bash
./tools/fishbot.sh start   # 启动/创建 fishbot_agent（长期运行）
./tools/fishbot.sh logs    # 看日志
./tools/fishbot.sh topics  # 查看话题（验收用）
```

如果你遇到 `docker: command not found`（WSL 里找不到 docker CLI），说明 **Docker Desktop WSL Integration 没挂上**（常见现象：`/mnt/wsl/docker-desktop` 目录不存在）。
这种情况下：
- 最稳的做法：回 Windows 打开 Docker Desktop → `Settings` → `Resources` → `WSL Integration` → 勾选 `Ubuntu-22.04` → Apply & Restart
- 然后在 Windows（管理员 PowerShell）执行一次：`wsl --shutdown`，再重新打开 WSL 终端

如果你当前就在 `tools/` 目录里，也可以直接：

```bash
./fishbot.sh start
```

> 你在终端里手敲命令时，最容易踩的坑就是：  
> 1) 容器还在跑/名字已占用 → `Conflict ... name is already in use`  
> 2) 复制粘贴导致 `--ros-args` 被换行拆开 → `--ros-args: command not found`  
> 脚本就是为了把这些“手滑错误”直接消灭掉。

#### 方式 A：临时运行（调试方便）

```bash
docker rm -f fishbot_agent 2>/dev/null || true
docker run --rm -it -p 0.0.0.0:8888:8888/udp --name fishbot_agent \
  microros/micro-ros-agent:humble udp4 --port 8888 -v6
```

#### 方式 B：长期运行（推荐）

```bash
docker run -d --name fishbot_agent --restart unless-stopped \
  -p 0.0.0.0:8888:8888/udp \
  microros/micro-ros-agent:humble udp4 --port 8888 -v6
docker logs -f fishbot_agent
```

以后再启动/停止（不丢配置、不丢你装过的包）：

```bash
docker stop fishbot_agent
docker start fishbot_agent
```

如果你遇到 `Conflict ... name is already in use` 或者怀疑容器状态乱了，再用一次“强制清理”：

```bash
docker rm -f fishbot_agent
```

可选验证（Windows）：确认 `0.0.0.0:8888` 已被 Docker 占用（对局域网可达）：

```powershell
Get-NetUDPEndpoint -LocalPort 8888 | Select-Object LocalAddress,LocalPort,OwningProcess
Get-Process -Id (Get-NetUDPEndpoint -LocalPort 8888).OwningProcess
```

### 2.5 FishBot：重启一次（非常关键）

很多时候 micro-ROS 客户端需要在 agent 已启动后重启，才能完成握手并创建 session。

### 2.6 验收：容器里能看到 ROS2 话题

新开一个 WSL 终端：

```bash
docker exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 topic list'
```

> 注意：这里是 `bash -lc`（小写 L），不要写成 `bash -Ic` / `bash -I`；并且 `source` 后面要有空格：`source /opt/...`

期望至少看到：`/cmd_vel`、`/odom`（以及 `/imu`）。

如果你只看到 `/rosout`、`/parameter_events`：
- 说明 **FishBot 还没和 agent 建立 session**（常见原因是你刚重启了 agent，客户端还没重连）
- 先对 FishBot 断电重启一次，等 5~10 秒再 `ros2 topic list`
- 同时确认 FishBot 里 `udpserver_ip` 仍然是当前 Windows `WLAN` IPv4，端口是 `8888`
- 如果仍然不行，优先检查 Windows 防火墙/网络配置：
  - 确认当前 WLAN 网络类别是 `Private`（`Get-NetConnectionProfile`），否则你按 `-Profile Private` 加的规则可能不生效
  - 临时做一次性验证：把防火墙规则放宽到 `-Profile Any` 或在“高级安全”里允许 UDP 8888 入站
- 排查“到底有没有 UDP 打到 agent”：把 agent 临时改成 `-v6`，如果完全看不到 `recv_message`，说明小车压根没打到 Windows:8888（IP/端口/防火墙/隔离）
  - 进一步“锤死是哪一跳”的办法（不靠猜）：临时停掉 `fishbot_agent`，在 Windows 上起一个 UDP 监听器看是否能收到来自小车的 16B 包
    - WSL 停容器：`docker rm -f fishbot_agent`
    - Windows PowerShell（监听 15 秒；如果小车在发，会看到 `xxB from 192.168.xx.xx:yyyy`）：
      ```powershell
      $udp = [System.Net.Sockets.UdpClient]::new(8888)
      $udp.Client.ReceiveTimeout = 15000
      $remote = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Any, 0)
      try {
        while ($true) {
          $bytes = $udp.Receive([ref]$remote)
          "{0}B from {1}:{2}" -f $bytes.Length, $remote.Address, $remote.Port
        }
      } catch {
        $_.Exception.Message
      } finally {
        $udp.Close()
      }
      ```
    - 如果 Windows 监听也收不到：优先检查小车 `udpserver_ip/port`、是否连对 SSID、是否开启了“客户端隔离”

### 2.7 控车：两种方式（都在容器里跑，最省事）

**方式 1：直接发 /cmd_vel（无需额外包）**

```bash
docker exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}, angular: {z: 0.0}}"'
```

停止（Ctrl+C 后发一次 0）：

```bash
docker exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 topic pub -1 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0}, angular: {z: 0.0}}"'
```

**方式 2：键盘控制（容器里默认没有，需要安装一次）**

```bash
docker exec -it fishbot_agent bash -lc 'apt-get update && apt-get install -y ros-humble-teleop-twist-keyboard'
docker exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel'
```

> 强提醒：上面的 `ros2 run ... --ros-args ...` 必须在**同一行**（或都在同一对引号里），  
> 否则换行后 `--ros-args` 会被当成“新命令”，就会报 `--ros-args: command not found`。

如果你已经构建了 `fishbot_tools:humble`（见下文），推荐直接用脚本跑键盘（最不容易出错）：

```bash
./tools/fishbot.sh build-tools   # 只需一次
./tools/fishbot.sh teleop
```

如果你在安装时遇到 `502 Bad Gateway`（`packages.ros.org` 抽风/被墙），先在容器里把 ROS2 源切到国内镜像再装（下面示例用 TUNA；你也可以换成 `https://mirrors.ustc.edu.cn/ros2/ubuntu`）：

```bash
docker exec -it fishbot_agent bash -lc 'for f in /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources /usr/share/ros-apt-source/*.sources; do \
  [ -f "$f" ] || continue; \
  sed -i "s|https\\?://packages.ros.org/ros2/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu|g" "$f" || true; \
done'
docker exec -it fishbot_agent bash -lc 'apt-get update && apt-get install -y ros-humble-teleop-twist-keyboard'
```

如果你连 Ubuntu 的 `archive.ubuntu.com` 都在 `502`（会表现成 “repo not signed / InRelease 502”），需要先把 Ubuntu 源也换掉：

```bash
docker exec -it fishbot_agent bash -lc 'set -e; \
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do \
    [ -f "$f" ] || continue; \
    sed -i -E "s|https?://(archive|security).ubuntu.com/ubuntu|https://mirrors.ustc.edu.cn/ubuntu|g" "$f"; \
  done; \
  rm -rf /var/lib/apt/lists/*; \
  apt-get -o Acquire::Retries=5 update'
```

然后再装：

```bash
docker exec -it fishbot_agent bash -lc 'apt-get install -y ros-humble-teleop-twist-keyboard'
```

如果你遇到 `File has unexpected size ... Mirror sync in progress`（镜像同步中），可以先禁用 `deb-src`（我们不需要源码索引）再更新：

```bash
docker exec fishbot_agent bash -lc 'sed -i "s/^Types: deb deb-src/Types: deb/" /usr/share/ros-apt-source/ros2.sources'
docker exec -it fishbot_agent bash -lc 'apt-get update && apt-get install -y ros-humble-teleop-twist-keyboard'
```

> 如果你用了 `--rm`，容器退出后包就没了；想持久化就去掉 `--rm`（或自己做一个带 teleop 的镜像）。

#### 推荐：做一个“工具镜像”（一次构建，后续不再 apt）

你也可以把键盘控制做成一个单独镜像（避免反复在 `fishbot_agent` 里 `apt-get install`，也避免你一旦 `rm` 容器就丢包）：

1) 构建（在 `/home/muqiao/桌面/dev/ros2` 下执行）：

```bash
docker build -f tools/Dockerfile.fishbot_tools -t fishbot_tools:humble .
```

2) 运行键盘（共享 `fishbot_agent` 的网络命名空间，ROS2 发现最稳）：

```bash
docker run --rm -it --network=container:fishbot_agent fishbot_tools:humble \
  bash -lc 'source /opt/ros/humble/setup.bash; ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel'
```

#### 键盘操作的意义（以及为什么按 `i` 会让它动）

`teleop_twist_keyboard` 的本质：把你的按键转换成 `/cmd_vel` 上的 `geometry_msgs/Twist` 消息：
- `linear.x`：前进/后退速度
- `angular.z`：原地左转/右转角速度

所以你按 `i`（前进）时，其实是在持续发布 “`linear.x > 0`” 的速度指令，小车就会动。

最常用按键（以程序打印说明为准）：
- `i` 前进，`,` 后退
- `j` 左转，`l` 右转
- `k` 停止（或者“任意其它键：stop”）
- `q/z` 调最大速度（+10% / -10%）
- `w/x` 调线速度，`e/c` 调角速度
- `Ctrl+C` 退出

建议第一次测试先按 `z` 降一两次速度，再 `i/j/l` 微动验证。

### 2.7.1 键盘 + RViz（推荐：直接在 agent 容器里装一次工具包）

> 说明：你可能会遇到 `docker pull osrf/ros:humble-desktop` 失败（例如 `failed to fetch anonymous token ... EOF`）。
> 这种情况下，最稳的做法是：**给 `fishbot_agent` 容器加上 WSLg 显示挂载**，然后在容器里安装 `rviz2` + `teleop_twist_keyboard`。

#### 0) 不想重启 agent？用 “工具容器” 共享网络（推荐）

优点：**不需要重启**正在工作的 `fishbot_agent`（不会影响 FishBot 已建立的 session），并且键盘/RViz 跑在同一网络命名空间里，ROS2 发现最稳。

新开一个 WSL 终端，启动一个带 WSLg 挂载的工具容器（与 `fishbot_agent` 共享网络命名空间）：

```bash
# 如果你机器上没有 /dev/dri（很多 WSL 环境就是没有），把 --device /dev/dri 去掉即可；
# RViz 需要时可加：-e LIBGL_ALWAYS_SOFTWARE=1 走软件渲染
docker run --rm -it --name fishbot_tools --network=container:fishbot_agent \
  -e DISPLAY=$DISPLAY -e WAYLAND_DISPLAY=$WAYLAND_DISPLAY -e XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR \
  -v /mnt/wslg:/mnt/wslg -v /tmp/.X11-unix:/tmp/.X11-unix \
  microros/micro-ros-agent:humble bash
```

在 `fishbot_tools` 里执行：

```bash
apt-get update
apt-get install -y ros-humble-teleop-twist-keyboard ros-humble-rviz2
source /opt/ros/humble/setup.bash

# 键盘控制
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel

# 或打开 RViz（另开一个 fishbot_tools 终端更舒服）
rviz2
```

#### 第一步：重启 `fishbot_agent`（加上 WSLg GUI 挂载）

先 `Ctrl+C` 停掉当前 agent，然后用下面命令重新启动：

```bash
# 同理：没有 /dev/dri 就去掉 --device /dev/dri；需要时可加 -e LIBGL_ALWAYS_SOFTWARE=1
docker rm -f fishbot_agent 2>/dev/null || true
docker run --rm -it -p 0.0.0.0:8888:8888/udp --name fishbot_agent \
  -e DISPLAY=$DISPLAY -e WAYLAND_DISPLAY=$WAYLAND_DISPLAY -e XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR \
  -v /mnt/wslg:/mnt/wslg -v /tmp/.X11-unix:/tmp/.X11-unix \
  microros/micro-ros-agent:humble udp4 --port 8888 -v6
```

> agent 重启后，FishBot 建议也重启一次，确保重新握手并创建 session。

#### 第二步：在容器里安装键盘包 + RViz 并启动

新开一个 WSL 终端：

```bash
docker exec -it fishbot_agent bash -lc 'apt-get update && apt-get install -y ros-humble-teleop-twist-keyboard ros-humble-rviz2'
```

键盘控制：

```bash
docker exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 run teleop_twist_keyboard teleop_twist_keyboard'
```

RViz：

```bash
docker exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; rviz2'
```

RViz 常用设置（你现在至少有 `/odom`/`/imu`）：
- Fixed Frame 先填 `odom`
- Add → Odometry → Topic 选 `/odom`

#### 2.7.2 可选：做一个“带工具”的本地镜像（避免每次 `apt-get install`）

如果你经常要用键盘/RViz，建议做一个本地镜像（以后启动 `fishbot_tools` 不再需要装包）：

1) 构建镜像（WSL 内）：

```bash
docker build -t fishbot_tools:humble -f tools/Dockerfile.fishbot_tools .
```

2) 启动工具容器（共享 `fishbot_agent` 网络）：

```bash
docker run --rm -it --name fishbot_tools --network=container:fishbot_agent \
  -e DISPLAY=$DISPLAY -e WAYLAND_DISPLAY=$WAYLAND_DISPLAY -e XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR \
  -v /mnt/wslg:/mnt/wslg -v /tmp/.X11-unix:/tmp/.X11-unix --device /dev/dri \
  fishbot_tools:humble bash
```

然后 `source /opt/ros/humble/setup.bash` 后直接 `rviz2` / `teleop_twist_keyboard`。

#### 2.7.3 可选：做一个“agent + teleop”镜像（单容器用法）

如果你更喜欢“一个容器全搞定”（agent 长期跑，键盘用 `docker exec` 在同一个容器里开一个进程），可以构建：

```bash
docker build -t fishbot_agent_plus:humble -f tools/Dockerfile.fishbot_agent_plus .
```

启动 agent 时把镜像名替换掉即可：

```bash
docker rm -f fishbot_agent 2>/dev/null || true
docker run -d --name fishbot_agent --restart unless-stopped \
  -p 0.0.0.0:8888:8888/udp \
  fishbot_agent_plus:humble udp4 --port 8888 -v6
```

键盘控制（容器内已有包，不需要再 `apt-get install`）：

```bash
docker exec -it fishbot_agent bash -lc 'source /opt/ros/humble/setup.bash; ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel'
```

如果你想继续用 `tools/fishbot.sh` 脚本管理 agent，只要把镜像名通过环境变量覆盖即可：

```bash
FISHBOT_AGENT_IMAGE=fishbot_agent_plus:humble ./tools/fishbot.sh start
```

### 2.8 常见问题

- 容器启动报 `bind error ... errno: 98`：说明 Windows 的 `:8888/udp` 已被占用（通常是 Relay 还在跑或旧容器没停）
  - `docker rm -f fishbot_agent`，并确保 Relay 已 `Ctrl+C`
- 容器日志只重复 `client_key: 0x00000000, len: 16`：先确认 FishBot 端口真是 `8888`，然后重启主控板一次
- WSL 上 `ros2 topic list` 只有 `/rosout`：正常；建议把 `ros2` 命令都放到 `docker exec ...` 里执行（避免 DDS 跨网络折腾）

---

## 方案 1：Windows UDP Relay → WSL（需要 WSL 本机 agent）

> 重要提醒：如果你现在的 `docker` 是 **Docker Desktop 引擎**，那么在 WSL 里跑 `docker run --network host ...`，
> 监听的不是 WSL 的 `172.xx` 网卡，而是 Docker Desktop 的 Linux VM。
> 这种情况下，Relay 虽然能把包转进 WSL，但 agent 不一定真的在 `WSL_IP:8888` 上监听，所以很容易“看起来转发有数据但 ROS2 没起来”。
> 想省事：直接用 **方案 2（端口映射）**。

### A) Windows：获取 Windows/WSL IP

在 Windows PowerShell：

```powershell
# 先确认当前连的是哪个热点（SSID）以及接口名
netsh wlan show interfaces

# Windows Wi-Fi IPv4（FishBot 需要填这个）
# 注意：不同机器接口名可能不是 "Wi-Fi"（例如常见是 "WLAN" / "Wi-Fi 2"）
# 先列出接口名，再取对应 IPv4：
Get-NetAdapter | Select-Object Name, Status
Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, IPAddress

# 如果你已确认接口名（例如 "WLAN"），再精确查询：
# Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "WLAN" | Select-Object IPAddress

# WSL IPv4（Relay 需要填这个）
wsl.exe hostname -I
```

### B) WSL：启动 micro-ROS Agent（UDP 8888）

在 WSL：

```bash
cd /home/muqiao/桌面/dev/ros2
source ./.ros2_env

docker run --rm -it --net=host \
  microros/micro-ros-agent:$ROS_DISTRO udp4 --port 8888 -v6
```

如果你发现：
- Windows Relay 已经在刷 `[cli->wsl] ...`
- WSL 里 `tcpdump` 也能看到 UDP 8888 包
- 但 `ros2 topic list` 仍只有 `/rosout`（没有 `/cmd_vel`/`/odom`）

通常说明：你当前的 agent 并没有真正“在 WSL 的网络栈里”监听/建立 session（尤其是 Docker Desktop 场景）。
此时请直接改用 **方案 2（Docker Desktop 端口映射）**，省掉 WSL IP/Relay 这条链路。

如果你在 WSL 里提示 `docker: command not found`（常见原因：Docker Desktop 没开 WSL Integration），有两种替代方案：

**方案 1：启用 Docker Desktop WSL Integration（推荐，后续教程也更省事）**

- Windows 打开 Docker Desktop → Settings → Resources → WSL Integration → 勾选你的发行版（如 `Ubuntu-22.04`）→ Apply & Restart
- 回到 WSL 重新开一个终端，再重试上面的 `docker run ...`

### C) Windows：允许 UDP 8888 入站 + 启动 Relay

管理员 PowerShell（只需一次；如果你看到 “拒绝访问/权限不足”，说明当前窗口不是管理员）：

```powershell
# 一键以管理员打开 PowerShell（或手动右键“以管理员身份运行”）
Start-Process powershell -Verb RunAs
```

```powershell
New-NetFirewallRule -DisplayName "FishBot UDP 8888 Relay" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 8888 -Profile Private
```

如果你不想敲命令，也可以走 GUI：

- Windows Defender 防火墙（高级安全）→ 入站规则 → 新建规则 → 端口 → UDP → 特定本地端口 `8888` → 允许连接 → 勾选 Private → 命名保存

启动 Relay（脚本在 WSL 仓库内；Windows 通过 UNC 路径运行；**WSL IP 变了要同步改**）：

```powershell
# 把 WSL_IP 改成 B) 里 wsl.exe hostname -I 的值（取第一个 IPv4）
$WSL_IP = "172.19.145.120"

powershell -ExecutionPolicy Bypass -File "\\wsl.localhost\\Ubuntu-22.04\\home\\muqiao\\dev\\ros2\\tools\\udp-relay-8888.ps1" -WslIp $WSL_IP
```

如果你找不到 `Ubuntu-22.04` 这个名字（发行版名不一样），先查一下：

```powershell
wsl.exe -l -v
```

### D) FishBot：配置（udp_client）

用 `fishbot_tool` 配置主控板参数：

- `wifi_ssid`：你的 2.4G WiFi（例如手机热点 `fishbot`）
- `wifi_pswd`：WiFi 密码
- `udpserver_ip`：Windows **WLAN** 的 IPv4（例如 `192.168.14.172`）
- `udpserver_port`：`8888`

写入后让主控板重启/重新联网。

### E) 验收

1) Windows Relay 窗口应打印 `[cli->wsl] ...`（说明 FishBot 已打到 Windows:8888）
2) WSL micro-ROS agent 窗口应出现连接/session/数据日志（说明已转发到 agent）

### F) 常见问题（快速定位）

- **Windows Relay 没日志**：多半是 FishBot 没打到 `udpserver_ip`（填错 IP/热点隔离/Windows 防火墙没放行 UDP 8888）
- **Relay 有 `[cli->wsl]`，但 WSL agent 没反应**：检查 WSL 里 agent 是否真的在 `8888/udp` 监听；以及 Relay 里填的 `$WSL_IP` 是否还是当前 WSL IP
- **WSL 网络看起来异常（比如你看到过 eth0 DOWN）**：在 Windows 执行 `wsl --shutdown` 后重开 WSL，再重新 `wsl.exe hostname -I` 取新 IP
- **热点重连后“看起来同一个热点但网段变了”**：手机热点/路由器 DHCP 可能会把网段从 `192.168.0.x` 切到 `192.168.14.x` 之类；此时必须重新获取并更新：
  - Windows：`Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "WLAN"` 得到新 IP，把它写回 FishBot 的 `udpserver_ip`
  - FishBot：屏幕上的 IP 也会变化；Windows 先 `ping <FishBot_IP>` 验证能互通

### G) “IP 不一致/不通”从头排查（按这个顺序做）

目标：让这三个 IP 配对正确，才能通信：
- FishBot 自己的 IP（屏幕上看到的 `192.168.X.Y`）
- Windows `WLAN` 的 IP（FishBot 要填的 `udpserver_ip`）
- WSL 的 IP（Relay 要填的 `-WslIp`，通常是 `172.22.*` 或 `172.18.*`）

### G.1 Windows：确认 WLAN IP 与 SSID

```powershell
netsh wlan show interfaces
Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "WLAN" | Select-Object IPAddress
```

### G.2 Windows：确认能 ping 通 FishBot

> 注意：`ping` 后面不要带中文顿号 `、`，否则会被当成域名解析，结果完全不靠谱。

```powershell
ping <FishBot屏幕上的IP>
```

### G.3 FishBot：把 udpserver_ip 改成 Windows WLAN IP

- `udpserver_ip` = `Get-NetIPAddress ... "WLAN"` 查到的 IPv4（例如 `192.168.14.172`）
- `udpserver_port` = `8888`
- 写入后重启主控板（断电重上电最稳）

### G.4 WSL：确认当前 WSL IP（给 Relay 用）

```powershell
wsl.exe hostname -I
```

把输出的第一个 IPv4 填到 Relay：

```powershell
$WSL_IP = "<wsl.exe hostname -I 输出的第一个IPv4>"
powershell -ExecutionPolicy Bypass -File "\\wsl.localhost\\Ubuntu-22.04\\home\\muqiao\\dev\\ros2\\tools\\udp-relay-8888.ps1" -WslIp $WSL_IP
```

### G.5 验收现象（必须同时满足）

1) Windows Relay 窗口开始刷 `[cli->wsl] ...`（说明 FishBot → Windows:8888 成功）
2) WSL 里的 agent 窗口出现 session/连接日志（说明 Windows → WSL:8888 成功）

---

## USB 断了还能不能跑？

可以。只要你已经把 FishBot 主控板的 WiFi/UDP 参数写入并保存：
- 运行时 **不需要 USB**：小车靠电池供电，通过 WiFi 和 agent 通信。
- USB 主要用于：刷固件、写入/修改参数、串口调试/日志。
