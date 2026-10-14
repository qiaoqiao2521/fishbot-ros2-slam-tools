# 官方单例推理接续

## 当前状态

2026-10-14已准备固定源码、官方样例、模型权重和独立兼容环境。官方推理尚未运行，状态为`not_run_pending_gpu_window`。转换、编辑、实际MuJoCo加载和GT点云查看已分别验收。

GPU窗口由FishBot原对话owner协调。不要停止其他模拟器、RGB批次或服务。此入口不申请云GPU，不训练，不改模型源码。

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

RTX3050 Laptop实际capability为8.6，BF16可用。模型参数加载估算约1.425GB，不包括激活、点云编码和KV缓存。4GB名义容量和参数估算均不证明单例推理能完成；峰值与结果需要实际运行。

## 运行一例

条件：owner确认空闲窗口；上述缓存仍满足固定版本和哈希；输出目录尚不存在。此命令是接续入口，尚无本轮运行结果。

```bash
mkdir "$HOME/.cache/fishbot-spatiallm/inference-single-v1"
cd "$HOME/.cache/fishbot-spatiallm/prepared/source/SpatialLM"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  timeout --signal=INT --kill-after=15s 600s \
  "$HOME/.cache/fishbot-spatiallm/inference-venv/bin/python" inference.py \
  --point_cloud "$HOME/.cache/fishbot-spatiallm/prepared/sample/pcd/scene0000_00.ply" \
  --output "$HOME/.cache/fishbot-spatiallm/inference-single-v1/scene0000_00.txt" \
  --model_path "$HOME/.cache/fishbot-spatiallm/model/SpatialLM1.1-Qwen-0.5B" \
  --inference_dtype bfloat16 --seed 0 \
  > "$HOME/.cache/fishbot-spatiallm/inference-single-v1/run.log" 2>&1
```

命令最多运行600秒，超时保留日志。从源码目录执行，因为官方CLI默认读取相对路径的代码模板。模型使用BF16，点云backbone按官方代码使用FP32；保留官方清理、模板、采样和4096 token默认上限。不要把人工GT校正文件替换为预测。

完成后记录退出状态、执行源码/输入/权重/输出哈希、GPU峰值、日志和严格解析结果。超时、CUDA失败、输出缺失或无法解析均保留为失败，不能以导入成功代替。

通过严格解析后，将实际输出在编辑器中声明为模型输出，核对几何，再显式校正与导出。即使此单例通过，也不代表数据集评测或导航任务通过。

## 交接

工作区：`/home/muqiao/worktrees/fishbot-spatiallm-scene-import-20261014`。
软件入口和验收命令见[README.md](README.md)。实际状态见[progress.md](../../plans/spatiallm-scene-import-20261014/progress.md)。

单例推理接续owner为本模块根Agent；窗口协调和主区整合owner为FishBot原对话`01a101eb-92b4-78b3-a725-361dc7342c05`。项目总协调对话为`01a13a98-c3ea-7760-aeb8-e5a7396a5574`。
