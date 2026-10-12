# RGB 预训练物体巡检

此入口只操作隔离 MuJoCo domain 101。它复用原车载相机、Nav2、停稳确认、源时间和接收时间检查、图像与物理位姿对齐、取消及返航。

识别使用真实预训练 YOLO11n COCO 推理。检测器只接收 RGB 图像，输出类别、置信度和像素框。它不接收场景名称、物体真值、预期结果或颜色规则。COCO 的 80 类限制仍然存在，不是开放词表识别。

## 模型和资产

- 模型来自 [Ultralytics 官方 YOLO11](https://docs.ultralytics.com/models/yolo11/)，本机已缓存 `yolo11n.pt`，5,613,764 bytes。Ultralytics 运行库与权重使用 AGPL-3.0；见[官方许可证](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)。模型保留在 `~/.cache/fishbot/object-inspection/`，不提交权重。
- 杯子和笔记本电脑复用 [MetaWorld 3.0.0](https://github.com/Farama-Foundation/Metaworld) 已安装的 STL 和原有装配关系。[MIT 许可证](https://github.com/Farama-Foundation/Metaworld/blob/main/LICENSE)、来源路径和各文件 SHA 随缓存与 fixture 保留。缩放只用于常见物体尺寸。模型不会读取这些名称。
- [GroundingDINO](https://github.com/IDEA-Research/GroundingDINO) 是 Apache-2.0 的开放词表候选。本轮优先复用可运行的本机模型，没有下载其额外权重。

新适配只连接现有图像巡检和官方模型 API。没有训练模型，没有全局安装依赖，没有复刻导航或取消实现。真实物体检测不替代几何碰撞检测。

## 准备与运行

本机已有独立 ML 环境。默认 GPU 解释器为工作台 `vision/uw-yolo-code-assets/.venv-monitor/bin/python`。CPU 环境可通过 `FISHBOT_OBJECT_PYTHON` 和 `FISHBOT_OBJECT_DEVICE=cpu` 指定。运行库版本和模型 SHA 写入报告。

先将官方 MetaWorld 资产和许可证复制到新缓存目录：

```bash
python3 tools/fishbot_object_scene.py assets \
  --source /path/to/site-packages/metaworld/assets \
  --license /path/to/site-packages/metaworld-3.0.0.dist-info/licenses/LICENSE \
  --output "$HOME/.cache/fishbot/object-inspection/assets-v3"
```

将已核验的官方 `yolo11n.pt` 放入同一缓存根。运行只使用现有文件，不自动安装包或下载模型。缺失依赖直接报告错误。

```bash
bash tools/fishbot_object_inspection.sh /tmp/fishbot-object-new-run
```

使用新的外部目录，保留早先报告。入口先检查 domain 101 空闲，只清理自己启动的进程组，不碰 domain 93、实车或网络设置。

## 证据与边界

每个观察点采三张新鲜 RGB，并保存源时间、图像 SHA、时间对齐的位姿、速度和独立到点误差。`capture_freshness` 记录 ROS 源时钟和消息源时间、monotonic 采样时钟和接收时钟，以及分别计算的 `source_age_s` 和 `receipt_age_s`。报告可独立复算，不能跨两个时钟相减。返航后停稳也保留里程计与真值的双龄期。两帧检测到请求类别才记为 `present`；未检测或分歧保留 `unknown`，不能由此断言物体缺席。未知且设置了备用观察点时，实际导航换位，再采三帧。首次观察和备用观察分别保留。

图像采样沿用原巡检门限：观察点偏差最多 22 cm、朝向偏差最多 0.25 rad。它只判断照片是否来自请求的观察区域，不证明 15 cm 导航精度。图像与物理位姿时间差最多 0.12 s；采样时速度最多 0.015 m/s。

第二轮实际闭环通过时，最大照片采样位置偏差为 18.97 cm；它满足 22 cm 观察区域门限。不能将该结果写成“15 cm 导航精度通过”。

补证据后的一轮在空工位遇到独立真值朝向偏差 0.293 rad，虽然 Nav2 报告到点，巡检仍拒绝采样并记为失败。新 fixture 只复制基线 Nav2 参数，再采用项目已验证的 AMCL 配置：`sigma_hit=0.05`、`max_beams=180`、`z_hit=0.95`、`z_rand=0.05`、`update_min_a=0.02`、`update_min_d=0.02`。基线文件、RPP、Goal 容差和 22 cm / 0.25 rad 观察门限保留。复制来源、实际覆盖项和生成参数 SHA 写入 provenance。

后续一轮遇到 RPP 碰撞预测暂停，随后在低平移、大角度转向中被 `SimpleProgressChecker` 判定无进展，Goal 失败。此失败保留，不能单凭延长等待算通过。fixture 复用已验证的官方 `PoseProgressChecker` 配置：平移 0.04 m 或转角 0.1 rad 可更新进展，等待 20 s；来源为项目现有 `fishbot_passage_nav.yaml`。RPP 碰撞预测、Collision Monitor 和 Goal / 采样门限保持，实际新一轮仍须完成各点和返航。

合成 fixture 包含可见杯子、可见笔记本电脑、被挡住的杯子和空工位。fixture 预期仅用于报告后的独立评分，不传入检测器。遮挡首视角应为未知，换位后应恢复；空工位不得出现杯子误检。未知负例不会被改写为“已识别缺席”。

fixture 经过人工选择，不能当作识别精度基准。初试篮球被预测为 `orange`，足球被预测为 `umbrella`，20 cm 支台上的笔记本被预测为 `tv`。保持相机不变，将支台降到 10 cm 后，模型能看到键盘。九个高度和姿态组合均检测到 `laptop`，置信度 0.874–0.962。选定主视角为 0.952；杯子为 0.881，遮挡换视角为 0.469。失败候选、支台调整和选择范围写入 fixture provenance 与最终报告。这里证明指定合成物体可识别，不能外推现实物体的准确率。

首轮实际导航已完成识别、换位、负例和返航，但左侧备用位姿因到点容差遮住杯柄，恢复识别评分失败，报告保留 `unknown`。右前候选只有 18/27 个选定容差姿态检出杯子，未采用。后侧观察点 `[2.5, 1.85, -π/2]` 的 27 个选定扰动姿态均检出杯子，置信度 0.619–0.947。此结果用于选择视线，不等于现实检测准确率；实际导航结果单独验收。

`report.json` 保留导航、停车、位姿、原始模型输出、模型版本和 fixture 评分。模型输入 PNG 的 SHA 必须等于报告照片 SHA，避免识别结果与显示照片错配。启动前记录运行源码 SHA，结束后核对；fixture 的场景与路线 SHA 也独立核对。`index.html` 展示实际 RGB、模型框与真值路线。静态 `fishbot_object_scene.py render` 只验证视线和模型推理，不能证明真实导航或巡检闭环。

## 本轮实际验收

2026-10-12 的最终运行 `fishbot-object-runtime-20261012-f` 在 domain 101 通过。任务耗时 135.802 s；这个数值来自任务计时，不含入口的空域检查和模型预热。7 次导航各发一个 Goal，日志中的 7 次成功结果与四个主观察点、两个备用点、返航顺序一致。独立真值轨迹有 615 个采样点，累计平移 10.15 m。

| 实际车载 RGB 观察 | 新鲜帧数 | 真实模型结果 |
| --- | ---: | --- |
| 可见杯子 | 3 | `cup`，置信度 0.781 |
| 可见笔记本电脑 | 3 | `laptop`，置信度 0.903 |
| 遮挡杯子，首视角 | 3 | 未检出杯子，保留 `unknown` |
| 遮挡杯子，后侧备用视角 | 3 | `cup`，置信度 0.940 |
| 空工位，首视角与备用视角 | 6 | 未检出杯子，保留 `unknown` |

18 帧均保存原图和模型输入文件；两者的实际文件 SHA 与模型回执中的输入 SHA 全部相等。由记录时钟独立复算，图像源龄期为 8–34 ms，接收龄期为 0.093–1.033 ms。图像与真值最大时间差为 24 ms。最大采样位置偏差为 21.46 cm，朝向偏差为 0.162 rad；两者满足观察门限，位置结果不能算作 15 cm 导航验收。

返航独立真值误差为 9.04 cm / 0.113 rad。最后停稳确认取得 26 个新真值样本，持续 1 s；真值源龄期 / 接收龄期为 14 / 12.643 ms，里程计为 4 / 2.945 ms。低频保存的轨迹末段也确认车身没有继续运动。

这一轮仍记录 12 次 RPP 碰撞预测提示和一次控制器耐心超时。Nav2 现有恢复树在同一个 Goal 内恢复，随后完成空工位、备用观察和返航；没有额外重发导航 Goal，没有 `Failed to make progress`。报告保留这些提示，不能把任务完成写成“没有暂停”。未采集原始接触流，此结果不证明物理接触率。

独立读回核对了 13 个运行源码 SHA、场景、路线、机器人、资产许可证和生成导航参数 SHA；19 个报告文件链接均存在。20 个启动进程 PID 均已退出。独立结论保存在同一外部运行目录的 `independent-readback.json`，原始 RGB 与日志保留在该目录，不提交运行产物。

| 保留运行 | 真实结果与边界 |
| --- | --- |
| `a` | 导航及返航完成；左侧备用视角未检出杯子，评分失败 |
| `b` | 原识别闭环通过；尚未记录可独立复算的双龄期，不作为最终证据 |
| `c` | 定位启动未就绪，0 个 Goal、0 张照片，失败并清理 |
| `d` | 朝向偏差 0.293 rad，被原 0.25 rad 门限拒绝，失败 |
| `e` | 平移不足而持续转向，被旧平移进展检查器判定失败 |
| `f` | 六个实际观察视角、18 帧、7 个 Goal、返航及新鲜停稳通过 |

运行目录没有被覆盖。`f` 使用 fixture 独立 AMCL 配置和现有 `PoseProgressChecker`；各轮源码与参数变化由各自 provenance 记录。

离线回归复用 [物体巡检测试](../tools/tests/test_object_inspection.py)、[原巡检测试](../tools/tests/test_inspection.py)、[视觉绑定测试](../tools/tests/test_inspection_vision.py) 和 [进展配置测试](../tools/tests/test_passage_config.py)。本轮 48 个测试全部通过；这些测试检查失败边界与复用接口，实际闭环仍由上述运行证据验收。

此阶段不证明实车相机、现实环境检测精度、开放词表能力或生产持续运行。实际闭环结果须以对应新报告为准。
