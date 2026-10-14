# 官方单例推理与接续

## 当前状态

2026-10-15官方单例已实际运行，状态为`official_single_prediction_and_cpu_conversion_complete`。执行时模块冻结于`0d11a5bdc4a96e3b5a0586b4491b31098440bd48`；此前的`not_run_pending_gpu_window`属于准备阶段状态。原件与17份执行源码哈希保留，不用本次文档修订替代历史版本。

原官方CLI在26.903秒后退出0，BF16/seed0和4096 token默认上限保持。严格解析及原始生成与序列化ID对账通过：预测6墙/1门/1窗/8bbox，共16实体；GT为18实体，存在门、家具数量及类别差异。这是一个真实运行样例，不是重建精度或数据集评测。

六墙显式校正为0.12米后，预测布局与原FishBot完成CPU编译及100物理步：27geom、9nq、363sensor，12固体探针及1门的两个截面通过。此衍生结果未渲染，起点`collision_checked=false`，没有导航或整车净空结论。

所属进程每秒采样峰值2014MiB，属于采样下界；退出及GPU lease释放已独立读回。后续新运行的GPU窗口仍由FishBot owner协调。此入口不申请云GPU，不训练，不改模型源码。

原件入口为Git外的`~/.cache/fishbot-spatiallm/inference-single-v1/`：

| 原件 | SHA256 |
| --- | --- |
| `receipt.json` | `a2901ac1ebb965c3f4aacd496d0e1f30990993383b8d01c75c902a0e465d0d94` |
| `handoff-manifest.json`，绑定14产物/17执行源 | `4f8face87fef0f9cc863ff754408cd27ac4e7391b5b267b19a49324d857ab2a3` |
| 原始预测`scene0000_00.txt` | `3157749a1893ae7d20440873f32d05d2b01c30e78e9df636e15fde547cd6e34f` |
| `prediction-corrected-cpu-v1/export-receipt.json` | `802665d5a4e67d68cfa5df2dc6efceae670e4ad0e447d45416fa32205b202150` |

## 固定输入

| 对象 | 版本或SHA256 |
| --- | --- |
| SpatialLM源码 | `8913c44d84a450c53e9340b13317f8cf7144a738` |
| Testset | `60bab76febb0c9635f58e156f32e906afc91a499` |
| scene0000_00点云 | `12d8cf9c239791260166837d090334915f7056537a2e35c97959d9842a6c5f92` |
| SpatialLM1.1-Qwen-0.5B | `b3ae9ad7a8689bc130a242c7f922a8cc290c1b59` |
| model.safetensors | `ed2e1ca161d9ca51342bdee27e801ff7aac4f6ef4b2585f530b7ba657ed8a827` |

权重文件2,414,130,784字节。使用实际SpatialLM发布权重，Qwen底座许可不覆盖此发布物。许可分层见[THIRD_PARTY.md](THIRD_PARTY.md)。

## 本轮已核实环境

独立Python路径：`~/.cache/fishbot-spatiallm/inference-venv/bin/python`。未修改系统Python或FishBot原运行环境。

| 组件 | 实际版本 |
| --- | --- |
| Python | 3.11.15 |
| Torch | 2.4.1+cu124 |
| transformers / tokenizers | 4.46.1 / 0.20.3 |
| huggingface-hub | 0.25.2 |
| flash-attn | 2.7.4.post1 |
| torch-scatter | 2.1.2+pt24cu124 |
| spconv-cu120 / cumm-cu120 | 2.3.6 / 0.4.11 |
| numpy / scipy | 1.26.4 / 1.15.3 |
| open3d | 0.18.0 |
| rerun-sdk / pyarrow | 0.21.0 / 19.0.1 |

FlashAttention使用[官方预编译wheel](https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1%2Bcu12torch2.4cxx11abiFALSE-cp311-cp311-linux_x86_64.whl)。torch-scatter使用[官方PyG wheel](https://data.pyg.org/whl/torch-2.4.0%2Bcu124/torch_scatter-2.1.2%2Bpt24cu124-cp311-cp311-linux_x86_64.whl)。二者与本轮Python、Torch和ABI匹配；不要随意替换为最新版本。

RTX3050 Laptop实际capability为8.6，BF16可用。模型参数加载估算约1.425GB，不包括激活、点云编码和KV缓存；实际单例及采样峰值见上文。不同点云和输出长度仍需另行测量。

## 运行一例

条件：owner确认新的空闲窗口；缓存仍满足固定版本和哈希；选用不存在的新输出目录。以下命令保留本轮实际参数，但使用新目录，防止覆盖已验收的`inference-single-v1`。

```bash
mkdir "$HOME/.cache/fishbot-spatiallm/inference-single-v2"
cd "$HOME/.cache/fishbot-spatiallm/prepared/source/SpatialLM"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  timeout --signal=INT --kill-after=15s 600s \
  "$HOME/.cache/fishbot-spatiallm/inference-venv/bin/python" inference.py \
  --point_cloud "$HOME/.cache/fishbot-spatiallm/prepared/sample/pcd/scene0000_00.ply" \
  --output "$HOME/.cache/fishbot-spatiallm/inference-single-v2/scene0000_00.txt" \
  --model_path "$HOME/.cache/fishbot-spatiallm/model/SpatialLM1.1-Qwen-0.5B" \
  --inference_dtype bfloat16 --seed 0 \
  > "$HOME/.cache/fishbot-spatiallm/inference-single-v2/run.log" 2>&1
```

命令最多运行600秒，超时保留日志。从源码目录执行，因为官方CLI默认读取相对路径的代码模板。模型使用BF16，点云backbone按官方代码使用FP32；保留官方清理、模板、采样和4096 token默认上限。不要把人工GT校正文件替换为预测。

完成后记录退出状态、执行源码/输入/权重/输出哈希、GPU峰值、日志和严格解析结果。超时、CUDA失败、输出缺失或无法解析均保留为失败，不能以导入成功代替。

通过严格解析后，将实际输出在编辑器中声明为模型输出，核对几何，再显式校正与导出。即使此单例通过，也不代表数据集评测或导航任务通过。

## 交接

工作区：`/home/muqiao/worktrees/fishbot-spatiallm-scene-import-20261014`。
软件入口和验收命令见[README.md](README.md)。实际状态见[progress.md](../../plans/spatiallm-scene-import-20261014/progress.md)。

本轮单例由总协调根的内置helper执行；后续推理窗口协调和主区整合owner为FishBot原对话`01a101eb-92b4-78b3-a725-361dc7342c05`。项目总协调对话为`01a13a98-c3ea-7760-aeb8-e5a7396a5574`。
