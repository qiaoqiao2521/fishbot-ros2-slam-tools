# 配送耗时报告

成果页 `/results#workbench-delivery-timing` 共用一个面板，选择原J100完整K、麦轮P2历史、本轮2D回归或3D雷达B→A记录。读取、切换、导入和下载只操作摘要，不执行ROS动作，也不重新评分。旧J100占用通道和麦轮开放通道不同，不能直接作为车型A/B性能对照。

## 只读导入

在项目根执行。`RUN` 指向原完整配送记录，`OUTPUT` 指向独立派生目录。二者不能互相包含。

```bash
python3 -B tools/cooperation_timing.py \
  --run "$RUN" \
  --output "$OUTPUT" \
  --public-output apps/fishbot-control-station/frontend/public/workbench/delivery-timing.json
```

输入沿用原 runner：`result.json`、`declaration.json`、`manifest-used.json`、`order-N/markers.json`、`order-N/observer/observer.jsonl`，以及可选的 `runtime/loop-timing.json`。首版面向完整 K 的相同记录合同，尚未自动发现其他历史格式。

麦轮沿用同一命令，把public-output改为`apps/fishbot-control-station/frontend/public/workbench/mecanum-delivery-timing.json`，不覆盖原J100文件。标题从实际车型与已执行订单生成，案例保留scene_id；未知字段不补成成功。

P3两组另存`mecanum-planar-queued-delivery-timing.json`和`mecanum-lidar3d-delivery-timing.json`。它们共用修复源码与queued接收配置；P2旧摘要保持。车型、sensor、任务UUID与原裁决来自实际记录，不由菜单名称推定。

导入器逐行处理 JSONL。坏记录被跳过并计数；缺项显示未知，案例导入标为 partial。原评分和失败不变。命令退出不等于导入完整，以 warnings 和每单 import_status 为准。

派生目录含 `timing.sqlite3`、`delivery-timing.json` 与 `order-N-trajectory-10hz.jsonl`。SQLite 的 `eval_runs`、`eval_stage_spans`、`eval_trajectories` 保存可重建索引；轨迹表存流引用，相同案例重导入采用 upsert。原记录、数据库、派生流及日志留在 Git 外。

公开摘要采用字段白名单，不导出原 manifest、本机绝对路径、原错误正文或高频轨迹。网页“刷新”重读静态导出，不代表重新采集；重新导入才更新摘要。人工编辑 JSON 后可直接导入，无内容锁；下载保留当前载入的摘要。

## 时间与证据

- 配送沿用原 120 墙秒：必要离站完成后起算，包含最终 Nav2、停稳和 hold 确认。装货和离站不并入此轴。
- 完整任务沿用原 360 墙秒。HTTP task.stage 是观测区间，切换发生在前后采样之间；末阶段右删失，不推定后续状态。
- native_route 只证明原 UUID 动作回执与终态。路径、速度转发或终态都不冒充控制器计算/消费确认。
- 路线耗时采用原 monotonic receipt；动作条以接收墙钟定位，微小计时差分别保留。源时间不改写成接收时间。
- K 发布周期为 20ms；physics_hz 是内部积分频率。10Hz 摘要选实际样本，缺口处断开，不插值补帧，不用于评分。
- 父区间和子区间不相加。未细分间隔不标为规划 CPU；会话 loop timing 不归因于某个 Goal。

B 路线 119.793848 秒，余 0.206152 秒。进场动作 89.251333 秒，最终配送 26.860442 秒，其余约 3.682 秒。这是时间分布，尚未定位唯一根因。A 路线 34.883377 秒，余 85.116623 秒。B/A 原缺失序号为 1/50，保护介入为 0.80/0.78 源秒。

## 验证

```bash
python3 -B -m unittest tools.tests.test_cooperation_timing
cd apps/fishbot-control-station/frontend
npm test -- --run src/lib/delivery-timing.test.ts src/components/workbench/delivery-timing-panel.test.tsx src/components/workbench/workbench-page.test.tsx
npm run build
```

页面检查复用已有 Playwright。为 NODE_PATH 指定其包位置，使用独立本机 Vite，输出放在 Git 外。

```bash
node tools/fishbot_delivery_timing_ui_contract.cjs \
  --base http://127.0.0.1:5191 \
  --output "$UI_EVIDENCE"
```

检查 B/A、预算轴、来源、桌面/390px、坏文件保留、编辑下载、404 保留和零写请求。主文档和摘要来自实际 HTTP 服务；无关服务 GET 明确返回离线，不伪造 ROS 成功。

本片只验证旧仿真记录的分析与界面。物理快照、连续卸货、故障注入、配对 A/B、真机与 sim-to-real 尚未由此验收。
