# SO101 保存回合 → Lichtblick MCAP

只转换已存在的仿真记录。不导入控制器，不推进物理，不访问机械臂，不派发任务。
原 `trace.npz`、报告、独立验收和视频只读。输出、依赖环境、样本和运行日志均留在被忽略的 `output/`。

## 执行

条件：系统已有 Python 3.12、ffmpeg、ffprobe，已取得选定的 SO101 回合与原源码。

```bash
python3 -m venv output/venv
output/venv/bin/python -m pip install -r requirements.txt
output/venv/bin/python so101_to_mcap.py \
  --episode-dir /path/to/saved/full-cycle-directory \
  --source-root /path/to/so101 \
  --output output/new-run --include-rgb
output/venv/bin/python verify_so101_mcap.py output/new-run
output/venv/bin/python -m unittest -v test_conversion_boundaries
SO101_RECORDED_FIXTURE=output/new-run \
  output/venv/bin/python -m unittest -v test_readback_semantics
```

输出目录必须是 `output/` 下尚不存在的子目录。转换失败不覆盖原产物；未完成文件保留 `.partial`，不会发布成完整 MCAP。
不传 `--include-rgb` 时不读取视频。已提供视频但不能核准时序时，拒绝同步导出，不猜测时间映射。

## 数据与时间

| 主题 | Schema | 内容 |
| --- | --- | --- |
| `/so101/scene` | `foxglove.SceneUpdate` | 原世界坐标中的方块中心、姿态及保存场景的真实尺寸 |
| `/so101/camera/overview` | `foxglove.CompressedImage` | 原视频逐帧转 JPEG，不生成新视角；仅通过来源/时间核准后写入 |
| `/so101/joints` | `so101.JointSample` | `position` 六轴实测；`command` 六轴已应用目标，单位 rad |
| `/so101/contact` | `so101.ContactSample` | 双指力 N、原接触与安全标记 |
| `/so101/episode` | `so101.EpisodeReview` | 原回合最终结论、独立验收、当前阶段和真实阶段事件 |

MCAP `log_time`/`publish_time` 是原 `time_s` 换算的整数纳秒，**不是 Unix 时间**。通道元数据声明 `simulation_seconds_not_unix`。
每条记录对应已执行该控制周期后的观测；`command` 是此前周期已应用的目标，不是未来动作。
本条原回合控制时间从 0.02 s 开始，按 20 ms 保存；每完成两条观测才写一帧视频。
同步导出需要原 recorder SHA-256 与报告绑定一致、AST 符合已审查规则、视频全部帧数及 PTS 与原时间匹配。
因此视频第 `j` 帧对应 `trace[2*j+1]`：首帧物理时间 0.04 s、媒体 PTS 0，不做减 0.04 s 的伪对齐。

`/so101/episode` 每个控制周期都保存元信息与当前阶段，支持原生 seek 后恢复；`success` 是原回合最终结论，不能解释成当前时刻已经完成。
`stage_events[].sim_time_s` 直接使用原物理秒，不减第一条时间。输出 `episode.sample.json` 是面板联调样本，含真实结果，不提交仓库。

## 读回与边界

转换前后核对原输入哈希。独立读回通过官方随机 reader 校验分块 CRC，并用 `StreamReader` 顺序核对完整数据节 CRC；CRC缺失时拒绝冒充已校验。
读回重新计算原报告到 trace、recorder、full-cycle 源码及独立报告到原报告的四条绑定，核对七项原报告指标、JSON Schema、全部数值与标记、方块旋转往返误差、图像覆盖和区间索引。
负例通过官方 Writer 构造合法新 MCAP 并更新外围哈希，再篡改指标或绑定；另单独改坏 DataEnd CRC，确认拒绝来自语义或数据节校验，而非仅总文件哈希不符。
`readback.json` 通过只代表格式、来源和数据转换通过；实际 Lichtblick 页面、3D视图、Image/Plot 和阶段跳转仍由浏览器验收。
JPEG 转码有额外有损压缩，不宣称原 H264 字节相同。全臂三维 FK、原安全守卫、新仿真和批次泛化不在转换范围内。

## 第三方来源

- MCAP 容器由官方 `mcap==1.3.0` 编写与读取，不实现自有容器。来源：<https://github.com/foxglove/mcap/tree/main/python/mcap>，MIT。
- `schemas/SceneUpdate.json` 与 `schemas/CompressedImage.json` 使用官方 `@foxglove/schemas@1.13.0` 内的 `generateJsonSchema` 和 `foxgloveMessageSchemas` 生成，未修改字段。来源：<https://www.npmjs.com/package/@foxglove/schemas/v/1.13.0>，MIT；许可保留在 `schemas/LICENSE-FOXGLOVE`。
- Schema 包 tarball SHA-256 和生成工具记录于 `schemas/SOURCE.json`。这两个 schema 是底座已有依赖版本，不把 npm JSON 入口缺失问题变成自研 schema。
- `EpisodeReview.json` 为本项目的有限数据契约，不包含原报告绝对路径、密钥、模型权重或运行日志。
