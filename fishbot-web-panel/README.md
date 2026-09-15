# fishbot-web-panel

吸收自 [ros2-mobile-panel-day1](https://github.com/muqiao215/ros2-mobile-panel-day1)（Day 6，`v0.1.0-soft-validated`）的轻量 Web 遥控与诊断面板，作为 FishBot 总仓的嵌入服务。一个 uvicorn 进程同时托管 PWA 前端（`frontend-dist/`）与 FastAPI 网关（`backend/`），无 nginx 也能独立运行。

## 能力（继承上游，未扩功能面）

- 系统状态、`/odom` 位姿曲线、`/scan` 雷达帧、`/map` 只读快照 + 有限窗口轨迹
- 安全遥控：方向命令必须带 `deadman_token` + `ttl_ms`（默认 300ms），松手即停、页面隐藏即停、断连归零、过期/重放命令服务端直接拒绝
- 限速：线速度 ≤ 0.2 m/s，角速度 ≤ 0.8 rad/s（`CONTROL_MAX_*` 可调）
- 网页控制不替代物理急停

## 运行

```bash
./run_web_panel.sh                      # 默认 0.0.0.0:8010，手机连同一局域网访问 http://<host>:8010
APP_PORT=8080 ./run_web_panel.sh        # 换端口
SERIAL_ENABLED=true ./run_web_panel.sh  # 树莓派等有底盘串口的宿主机开启串口心跳页
```

首次运行自动创建 `--system-site-packages` 的 `.venv`（web 依赖装进 venv，rclpy/numpy 继承系统；需先 source ROS）。

话题名与 FishBot 栈原生一致（`/odom` `/scan` `/map` `/cmd_vel`），如需改名：`ROS_ODOM_TOPIC` 等环境变量。Node name 默认 `ros2_mobile_panel_bridge` / `ros2_mobile_panel_command_gateway`，可用 `ROS_NODE_NAME` / `CONTROL_NODE_NAME` 覆盖。

## 接入 fishbot_stack

`tools/fishbot_stack.sh` 已内置 `web_panel` 窗口（`start-web` 单独启动；`start` / `start-slam` / `start-nav` 等流程经 `start_base_windows` 默认拉起）。端口 `WEB_PANEL_PORT`（默认 8010；8080 留给 control-station 后端）。

## 部署（树莓派常驻）

- systemd：`deploy/systemd/fishbot-web-panel.service`
- 对外 80 端口 + WebSocket 反代：`deploy/nginx/fishbot-web-panel.conf`（root 指向本目录 `frontend-dist/`）

## 测试

```bash
.venv/bin/python -m pytest backend/tests -q   # 上游 20 个契约/网关/桥接测试
```

## 与上游的关系

代码为上游 Day 6 快照的原样吸收（仅新增 `fishbot_app.py` 静态挂载包装与本启动器），上游修复 bug 后按目录重新同步即可。
