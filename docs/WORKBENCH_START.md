# 打开具身智能工作台

从 FishBot 仓库根运行：

```bash
./fishbot.sh workbench doctor --project all
./fishbot.sh workbench start
```

启动后打开输出的 `/start`。入口分别通向 FishBot 成果、SO101 工位和 Drone 工位；启动网页不会派发仿真任务。缺少 SO101 或 Drone 的执行环境不阻止已有网页和其它项目展示。FishBot 成果前端尚未构建时，入口明确显示准备状态，SO101/Drone 仍可使用。

| 入口 | 内容 |
| --- | --- |
| `/start` | 三项目入口与当前运行环境状态 |
| `/results` | 初始选中最新仓库 D 完整交付，可切换其它原始结果 |
| `/fishbot` | 原 FishBot 控制主页 |
| `/workbench` | 原 FishBot 能力总览 |
| `/so101-station` | SO101 工位编辑、显式运行与原任务回看 |
| `/drone-station` | Drone 工位与选定执行后端 |
| `/` | 原生 Lichtblick，保留布局与回放链接 |

`doctor --project fishbot|so101|drone|all` 只检查选定项目的源码、前端构建、依赖版本和执行器 `--describe-json`；`--json` 输出机器可读报告。它不启动模拟世界、连接 ROS 图或操作硬件，也不安装依赖。返回 `0` 为本轮环境检查通过，`1` 表示有缺项，参数或配置无效返回 `2`。通过环境检查不表示新物理任务、浏览器全链或实机验收通过。

## 配置当前执行环境

仓库相邻时，自动查找 `so101`、`drone-px4-ego` 或 `drone`。SO101 Python 优先取其 `.venv-station/bin/python`，再取 `.venv/bin/python`；没有可用环境时保留期望路径并指出缺项。默认 Drone 后端为 `cerlab`，不会根据缺少依赖悄悄切换后端。

需要其它路径时，把示例复制到 FishBot 根目录再编辑：

```bash
cp config/workbench.example.json workbench.local.json
./fishbot.sh workbench doctor --project so101
```

`workbench.local.json` 已被 Git 忽略。JSON 路径相对于配置文件所在目录，因此示例按复制到仓库根后的相邻目录填写。环境变量覆盖 JSON，显式命令参数覆盖环境变量；指定 `WORKBENCH_CONFIG` 或 `--config` 后，文件缺失或无效会直接报错。

| JSON 字段 | 环境变量 | 用途 |
| --- | --- | --- |
| `so101Root` | `SO101_ROOT` | SO101 执行器源码 |
| `so101Python` | `SO101_PYTHON` | SO101 仿真 Python |
| `droneRoot` | `DRONE_ROOT` | PX4 后端源码 |
| `cerlabRoot` | `CERLAB_ROOT` | CERLAB 后端源码 |
| `droneBackend` | `DRONE_BACKEND` | `cerlab` 或 `px4`，默认 `cerlab` |
| `host` | `WORKBENCH_HOST` | 监听地址，默认 `127.0.0.1` |
| `port` | `WORKBENCH_PORT` | 监听端口，默认 `5186` |
| `publicUrl` | `WORKBENCH_PUBLIC_URL` | 用户访问的 HTTP(S) 根 origin |
| `frontendDist` | `WORKBENCH_FRONTEND_DIST` | FishBot 已构建成果前端 |
| `workbenchBuild` | `WORKBENCH_BUILD_DIR` | Lichtblick 已构建网页 |

显式源码和 Python 路径不存在时，检查会显示原配置，不回退到旧家目录。没有配置时，也不会连接先前机器上的服务。

## 首次准备

按 `doctor` 给出的缺项准备即可。两套网页各自沿用原构建命令：

```bash
npm --prefix apps/fishbot-control-station/frontend ci
npm --prefix apps/fishbot-control-station/frontend run build
cd apps/fishbot-control-station
./workbench-dev.sh install --immutable
./workbench-dev.sh web:build:prod
```

Lichtblick 源码指定 Node >=20，并由 `workbench-dev.sh` 使用锁定的 Yarn 工具链。`start` 需要已有的 Lichtblick 构建和共享服务依赖；不会自动下载、安装或构建。SO101 的独立 `.venv-station` 使用其 `experiments/colab-twin/requirements-station-runtime.txt`；CERLAB/PX4 使用各自仓库已有运行说明，不在工作台复制一套模拟器。

## 从云端或转发地址访问

默认只监听本机。明确需要通过另一地址访问时，同时配置监听地址和用户实际打开的根地址：

```bash
./fishbot.sh workbench start --host 0.0.0.0 --port 5186 \
  --public-url https://your-workbench.example
```

该地址应由已有网络转发提供。工作台不会创建域名、隧道或 TLS 终端；HTTP 与 WebSocket 转发都应指向同一服务。`publicUrl` 只接受 `http://host[:port]` 或 `https://host[:port]`，不接受子路径、凭据、查询参数或片段。非 loopback 监听必须显式声明该地址，页面资源和实时连接据此保持同源。

反向代理需保留用户请求的原始 `Host`，并正确转发 WebSocket `Upgrade`／`Connection` 握手；否则服务可能看到内部地址，或实时三维连接无法建立。公开地址以 `WORKBENCH_PUBLIC_URL` 为准，不将代理内部主机名当成用户入口。

FishBot 后端连接由服务端固定目标代理完成。浏览器只请求同源接口，不把手机或远程浏览器的 `127.0.0.1` 当成运行服务的机器；后端尚未启动时保留不可用状态，不自动启动 ROS 或模拟任务。

SO101 也可以从自身仓库运行 `./so101.sh workbench doctor|start`，它会定位本工作台并传入当前 SO101 源码路径，保留显式 `SO101_PYTHON`。
