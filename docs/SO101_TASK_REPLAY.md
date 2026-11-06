# SO101 每次任务的结果与回放

打开工作台 `/so101-station`。运行结束后，在“当前仿真任务”查看原物理报告、抓取证据和视频，点击“回看本次三维轨迹”。也可在“历史任务”选择此前的回合。

回放使用该任务自己的 `episode.mcap`，复用无人机的任务产物接口、原生播放器与时间轴。拖动时间轴、播放、倒退或刷新只读取记录，不重新派发抓放。失败与取消的回合保留原结果，不显示为成功。

## 启动

在 SO101 源码根准备独立的仿真环境：

```bash
uv venv --python 3.12 .venv-station
uv pip install --python .venv-station/bin/python \
  -r experiments/colab-twin/requirements-station-runtime.txt
```

在本仓 `apps/fishbot-control-station` 构建并启动：

```bash
./workbench-dev.sh web:build:prod
SO101_ROOT=/path/to/so101 \
SO101_PYTHON=/path/to/so101/.venv-station/bin/python \
WORKBENCH_PORT=5186 node workbench-preview.cjs
```

服务已有任务时不要重复启动。保留同一个 `SO101_TASKS_DIR`（默认 `workbench-tools/output/station-tasks`），才能回看原任务；不要移动或覆盖正在运行的目录。

## 记录内容

每次任务在自己的 UUID 目录保存：

- `request.json`、`status.json`：本次输入与原终态。
- `episode/report.json`、视频和 `trajectory.json`：原执行器生成的报告、物理证据与逐拍记录。
- `episode.mcap`：索引化的模型、关节、物体位姿、接触力、阶段与原报告。
- `episode.recording.json`：任务 ID、样本数和可用几何说明。

`/so101/task` 保留原任务 ID、请求、完整报告与 `skill_evidence`。生成器只对保存的状态执行正运动学，不推进物理、不重评分。模型几何不可用时明确降级；旧轨迹缺少物体旋转时只显示位置标记，不补造姿态。转换失败不改原任务结果，仍可看原报告和视频。

MCAP 在任务结束后生成；打开该任务时可补生成缺失产物。历史列表不会批量转换全部旧回合。转换结束前，回看链接可能尚未出现，点击“查询原任务”即可重新读取。

## 验证入口

```bash
node --test workbench-review-tests/so101-recording.cjs \
  workbench-review-tests/so101-task-artifacts.cjs
```

真实任务回读使用 `workbench-review-tests/verify-so101-task-recording.py --task-dir TASK_DIR`；浏览器回看验证使用 `workbench-review-tests/so101-task-replay-browser.cjs`。前者验证保存数据的一致性，后者验证网页体验；两者均不能替代原抓放物理评分。

本功能限于保存的仿真任务。它不证明实体机械臂、完整 50Hz 或冻结的 20＋20 扰动验收通过。

## 本次验收

2026-11-06：新正常任务 `b996faa5-fedb-4712-a67e-aca132d743e3` 原物理抓放通过（76.58s仿真）；新取消任务 `4e11341d-9269-4325-ac27-12bcf52eff12` 保持取消（4.94s）。两任务各自的MCAP、报告、视频和抓取证据逐项读回一致，桌面／窄屏的播放、倒退、阶段定位、刷新与跨标签页均通过，没有重新派发任务。

原生回合面板仍分别显示原报告与独立验收／来源认证；本次未补造独立验收文件。视频和三维记录属于同一任务，但没有宣称逐帧同步。详细证据索引见本仓工作台计划的2026-11-06 A2节；完整物理指标见SO101仓的 `plans/workcell-productization-20261024/a2-task-replay-results.md`。
