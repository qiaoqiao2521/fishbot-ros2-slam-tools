# 两作业合作编排

## 入口与边界
运行 `tools/cooperation_workflow.py`。它只调用现有本地 `/coop-api`；不启动服务，不接管 ROS，不重启合作桥。`run` 有界轮询本流程，其他命令每次只做一个显式步骤。

软件语义为两个不同洗衣 batch、容量一的合成 machine-ready 工位、两次完整刚性货物运输。当前物理场景只有一个自由货物；两作业之间显式新 episode 会重新初始化该货物。此模块不提供同回合两件库存、真实衣物抓取、洗衣机控制或纺织品柔性仿真。

代码基线为 `aab0da45`。`start` 只发送 `task_id/episode_id/issued_at`；默认完整运输，兼容基线和新桥。原 `reset.available` 已包含 worker 清理、原生动作终态、车臂货物静止、car_hold 与 guard 退出，薄层复用它。实际物理验收由 FishBot owner 在隔离实例完成，沿用独立 oracle；本模块 CPU fixtures 不证明机器人搬运成功。

## 有界运行

条件：FishBot owner 已建立**新的、空闲、ready 合成 episode**，且确认该实例由本流程独占。保留当前运行实例与旧账本。选择对应 HTTP 端口；默认 `9086`，仅允许 localhost HTTP。运行时 JSON 保存在私有 cache，不能入 Git。

先准备两个固定 batch UUID，然后初始化一次。下列 UUID 只是新流程的示例。

```bash
python3 -B tools/cooperation_workflow.py \
  --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" \
  --bridge http://127.0.0.1:9086 init \
  --batch 74a9049e-b2f0-4c4a-bf56-14539465c66a \
  --batch 2e640edc-40d9-4a51-b5fc-08a841b7a3ab
```

启动有界流程。ready 事件从另一个 CLI 到达后，`run` 自动完成派发、原 ID 查询、第一作业成功后的重置及第二作业派发。每轮释放 ledger 锁，允许事件并发写入。自定义端口时，每条命令都带相同 `--bridge`。

```bash
python3 -B tools/cooperation_workflow.py \
  --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" \
  run --timeout 900 --poll 1
```

`timeout` 为 1–1800 秒；`poll` 为 0.1–10 秒。当前有界 HTTP 或持久化步骤可以有限超出退出时刻，但完成后不发新 POST。返回码：成功 `0`、fault/unknown 封锁 `2`、编排超时 `3`。超时只保存 runner 原因并退出编排器，保留原桥和原任务，不取消或重发动作。若预检后预算已耗尽，不创建派发意图；若同步意图后才耗尽，保留该 ID 为 unknown。`fault/unknown` 同样即时退出；显式恢复后可再次 `run`。

尚无任何派发意图的 ready job，预检断流或未就绪会以 `blocked_preflight` 返回 `2`。该 job 保留 `waiting_ready`，恢复反馈后可以再次 `run`；这属于有证据的未发送，不能类推到已经尝试 POST 的 unknown 动作。

准备 `ready-1.json`，内容如下。事件为合成输入；不要把示例解释为实际设备回执。

```json
{
  "event_id": "7eea093d-4e60-4505-9de8-198673f85655",
  "batch_id": "74a9049e-b2f0-4c4a-bf56-14539465c66a",
  "machine_id": "laundry-machine-1",
  "version": 1,
  "ready": true
}
```

载入 ready 事件。若 `run` 正在轮询，事件到达后自动推进。下面保留单步命令用于调试与恢复；运行 `run` 时不用同时手动 `dispatch/reset`。

```bash
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" event --file ready-1.json
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" dispatch
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" tick
```

`tick` 只查询原动作 ID；任务运行期间可再次调用。`status` 只读本地账本，完全不请求桥。第一作业已知成功且 quiet 时进入 `waiting_reset`。显式提交回合重置，然后调用 `tick`，直到原 reset ID ACK、新 episode、旧作业 history 与 ready 一致。

```bash
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" reset
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" tick
```

第二事件使用新 `event_id`、第二 batch UUID 和 `version=2`。事件到达前不会派发。载入第二事件后，再显式 `dispatch`；`tick` 确认第二任务成功且 quiet 后，状态为 `succeeded`。成功账本保留并冻结，不因后续其他 episode 操作改写。

## 取消与恢复

`cancel` 先查原任务，仅对已知 running/canceling 的原 UUID 提交一次取消。回执丢失后，重复 `cancel` 只查询，不能再 POST。

```bash
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" cancel
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" tick
```

原任务已知 failed/canceled、原生动作结束且 quiet 后，`recover` 显式重置该合成 episode。旧失败 attempt、取消回执和 task ID 保留。ACK 确认后还需要新版本 ready；再次 `dispatch` 会生成新 UUID，属于同一逻辑 job 的新 attempt，不重放旧动作。

```bash
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" recover
python3 -B tools/cooperation_workflow.py --ledger "$HOME/.cache/fishbot/workflow-example/workflow.json" tick
```

明确 start 拒绝也保留失败记录，显式恢复走同样门禁。reset 自身失败或拒绝保留原请求与原因，交 FishBot owner 审查；本模块不替 owner 再发一个重置。

## 不明结果与重启

每个 start/cancel/reset 都先同步落盘派发意图，再进行一次 POST。即使进程死在 POST 前，重启也不能证明未发送，只能保留未知。重启同一 CLI、同一 ledger、同一 bridge 端口，用 `tick` 原 ID 查询。不要删除账本、改变端口、重启原 bridge 或重新初始化来跳过门禁。

`GET /state` 不按 query task_id 过滤，所以薄层自己查 current/history 的精确 ID 与 episode。原桥只返回最近十条 history；找不到原 ID 即 `unknown`。同 ID 状态冲突、物理 source 不可用、episode 未经本流程 ACK 改变，也封锁推进。缺失记录不代表请求没有执行，`unknown` 不能 `dispatch/reset/recover/cancel`。

ready 事件绑定 event UUID、batch、machine 和连续 version。重复同 ID 同内容只读；同 ID 改内容、旧版本、跳版本、不同 batch、工位占用期间的新事件均拒绝。每次 reset 清除已消费 readiness，但保留事件历史与版本。

## CPU 验收

```bash
python3 -B -m unittest discover -s tools/tests -p test_cooperation_workflow.py -v
```

fixtures 使用基线 `request_identity/reset_request_identity`，覆盖提交前后断点、lost receipts、同 UUID 取消/重启、版本乱序、缺 history、unknown、source=None 与 reset ACK 门禁。测试不启动 ROS、MuJoCo、浏览器、服务或 GPU。计划入口：[cooperation-workflow-20261014](../plans/cooperation-workflow-20261014/task_plan.md)。
