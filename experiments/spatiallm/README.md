# SpatialLM离线场景导入

读取官方布局文本，查看结构，人工校正后导出可加载的MuJoCo场景。本模块不接ROS，不派发机器人动作，不修改现有地图、导航规则或运行实例。

## 已有入口与最小适配

复用SpatialLM固定源码的Layout/entity、官方布局序列化及Rerun可视化。复用本项目FishBot基础MJCF，保留关节、轮控、传感器与原碰撞参数。

现有生成器接收栅格地图或固定工位，官方可视化没有参数校正/MJCF导出。本模块只补严格输入检查、校正记录、墙体开孔与离线导出，不改模型或重建通用场景平台。

## 安装与来源准备

条件：位于FishBot仓库根，使用独立Python3.11环境。依赖不装入系统Python或机器人运行环境。

```bash
uv venv --python 3.11 "$HOME/.cache/fishbot-spatiallm/runtime"
uv pip install --python "$HOME/.cache/fishbot-spatiallm/runtime/bin/python" -r experiments/spatiallm/requirements.txt
"$HOME/.cache/fishbot-spatiallm/runtime/bin/python" experiments/spatiallm/prepare.py
```

`prepare.py`将固定官方源码和样例保存在Git之外。已有缓存版本/哈希不符时拒绝覆盖。原始点云与GT、模型权重、运行输出均不进入本仓库。

## 打开编辑器

条件：上述准备完成，选用空闲本地端口。若端口已占用，另选端口，不停止原服务。

```bash
experiments/spatiallm/run.sh \
  --source-dir "$HOME/.cache/fishbot-spatiallm/prepared/source/SpatialLM" \
  --sample-layout "$HOME/.cache/fishbot-spatiallm/prepared/sample/layout/scene0000_00.txt" \
  --sample-point-cloud "$HOME/.cache/fishbot-spatiallm/prepared/sample/pcd/scene0000_00.ply" \
  --output-dir "$HOME/.cache/fishbot-spatiallm/exports" \
  --fishbot-project "$PWD" --port 8867 --render
```

进入 `http://127.0.0.1:8867`。程序只绑定回环地址。`--render`请求真实MuJoCo预览；不加此参数时仍验证模型，但界面明确显示未请求图像。

1. 点击“加载官方GT样例”，或导入自己的布局文本。
2. 核对来源、坐标、尺寸与墙引用。
3. 显式设置墙厚，保存其他参数校正。
4. 如需FishBot，填写空闲初始位置。
5. 点击“生成并验证MuJoCo场景”。
6. 下载通过验证的文件。

官方样例是GT标注，不是本次模型推理。它的6面墙原始厚度均为0；软件保留原值，并要求导出前明确校正。米制位置、完整包围盒尺寸与绕z弧度不可混用。

## 输出与证据

- `scene.xml`：碰撞墙、真实门孔、保守窗板、固定家具包围盒，可选原FishBot。
- `layout.txt`：通过官方序列化并检查往返身份的布局，可继续用于官方工具。
- `layout.json`：原始来源、当前实体和逐次before/after校正。
- `manifest.json`：输入/源码/输出哈希、实体计数、近似策略与验证报告。
- `validation.json`：实际编译、有限状态步进、墙体负例和门洞采样。
- `scene.png`：实际MuJoCo渲染，仅在成功生成时提供。

导出按服务器文档ID/版本处理。过期版本拒绝；验证失败的目录不开放下载。文件被改写后，原验证下载链接也拒绝返回它。

家具框是保守占用体，门不含门板/铰链，窗保留全厚碰撞板。平面由墙底高度推导。门孔采样通过不证明整车可通行，编译通过不证明起点无碰撞或导航安全。

## 官方点云查看

可选条件：独立环境有`open3d==0.18.0`、`rerun-sdk==0.21.0`、`numpy==1.26.4`和兼容的`pyarrow==19.0.1`。

```bash
python experiments/spatiallm/visualize_official.py \
  --source-dir "$HOME/.cache/fishbot-spatiallm/prepared/source/SpatialLM" \
  --point-cloud "$HOME/.cache/fishbot-spatiallm/prepared/sample/pcd/scene0000_00.ply" \
  --layout "$HOME/.cache/fishbot-spatiallm/prepared/sample/layout/scene0000_00.txt" \
  --output "$HOME/.cache/fishbot-spatiallm/official-gt.rrd"
rerun "$HOME/.cache/fishbot-spatiallm/official-gt.rrd"
```

包装器执行固定哈希的原始`visualize.py`，只隔离模型急切导入，未重写点云可视化。原脚本图层名`pred`不改变GT输入的身份。Rerun记录与碰撞导出是两种证据。

包装器在生成manifest前调用Rerun官方`disconnect()`关闭保存文件，记录最终字节数及SHA256。已有RRD或同名manifest时拒绝覆盖；写入或关闭失败时保留原件，不生成成功manifest。

## 验证与接续

条件：准备好官方源码与样例。测试缺失依赖时失败，不静默跳过。

```bash
SPATIALLM_SOURCE_DIR="$HOME/.cache/fishbot-spatiallm/prepared/source/SpatialLM" \
SPATIALLM_SAMPLE_LAYOUT="$HOME/.cache/fishbot-spatiallm/prepared/sample/layout/scene0000_00.txt" \
SPATIALLM_SAMPLE_POINT_CLOUD="$HOME/.cache/fishbot-spatiallm/prepared/sample/pcd/scene0000_00.ply" \
MUJOCO_GL=egl "$HOME/.cache/fishbot-spatiallm/runtime/bin/python" -m pytest -q experiments/spatiallm/tests
node --test experiments/spatiallm/tests/test_editor_state.cjs
```

本模块计划：[task_plan.md](../../plans/spatiallm-scene-import-20261014/task_plan.md)。本轮软件/实际加载及一个官方预测样例已验收；样例差异、未渲染的预测衍生场景和原项目整合由计划分别记录。后续由FishBot主区owner串行整合，不从本分支同时推main。

来源与许可见[THIRD_PARTY.md](THIRD_PARTY.md)。
官方单例推理的结果、独立环境、固定权重和后续命令见[INFERENCE.md](INFERENCE.md)。
