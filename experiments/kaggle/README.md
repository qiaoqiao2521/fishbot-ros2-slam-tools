# F1 私有 Kaggle 运行入口

复用原 Jazzy、MuJoCo、Nav2、SO101 和 `tools/cooperation_factory.py`。
本入口只适配云端依赖与启动，不增加控制器、训练流程或新评分器。

2026-10-24 已运行私有 CPU 前检。该回合是 Ubuntu24.04/glibc2.39、
4核配额、约31GB可用内存、默认Python3.13，未安装ROS/MuJoCo。
本机UDP成功；ROS仓库HTTPS出现证书主机名不匹配，未禁用TLS验证。
这些是单次环境观测，不保证后续Kaggle分配相同资源。

- `f1_environment.py`：只读环境报告，`task_acceptance=false`，零Goal/任务。
- `pack_f1.py`：打包当前Jazzy安装、既有vendor runtime、Git版F1源码、
  SO101规划依赖闭包与模型。保留许可证，排除历史输出和认证配置。
  解引用vendor runtime目录链接，避免上传指向本机的空链接。
- `f1_candidate.py`：重建未验收候选。保留原加减速、局部碰撞配置和评分；
  载货上限`.06m/s/.10rad/s`，全局规划padding为候选`.025m`。
- `f1_run.py`：在临时Kaggle环境安装Python3.12，显式绑定上传ROS CLI和
  colcon的解释器。独立构建原1.3.13的Smac缓存和源时钟平滑补丁，
  运行原生时钟用例、原prepare和原factory的B→A。

## 使用

先在本机生成新的私有包目录；不要上传整个SO101实验目录。

```bash
python3 experiments/kaggle/pack_f1.py \
  --so101-project /absolute/so101 \
  --output /absolute/private/f1-dataset
cp experiments/kaggle/f1_candidate.py /absolute/private/f1-dataset/
```

用官方`kaggle datasets init/create`生成并上传私有数据集。
保留依赖原许可证；元数据使用`other`，不把第三方代码改授CC0。
在description写明第三方组件保持原许可证。
数据集必须包含四个`*.tar.gz.bin`包、`bundle.json`和`f1_candidate.py`。
打包器在原tar/gzip前增加19字节格式头，避免Kaggle自动展开运行库；
云端用标准tarfile解包，保留原执行权限和符号链接。此封装不加密、不锁定内容。
云端factory显式使用`--isolated-runtime`，不查询本机历史systemd演示服务；
记录空保护对象范围，不能声称原107/114在云端仍运行。本轮原任务与owned清理评分保持。
部署程序与输入可使用标准Kaggle kernel metadata：`kernel_type=script`、
`code_file=f1_run.py`、`is_private=true`、`enable_gpu=false`、
`enable_internet=true`，`dataset_sources`绑定自己的私有包。
调用官方`kaggle kernels push -p DIR -t 3600`，其中3600秒包含部署构建，
不会扩大原路线120秒、单单360秒和整轮1000秒的评分期限。

任务输出为`f1-deployment.json`、逐阶段日志以及
`f1-work-*/full-run/result.json`和原独立oracle报告。
只按原factory的最终物理结果报告配送；提交、构建和网页状态均不替代验收。
本轮旧载货初态和独立overlay缓存已丢失，因此新包是重建候选，
不宣称与已删除输入完全相同，也不拼接历史成功。

账户元数据、认证、运行时库、模型包与原始日志留在私有目录；不进入Git。
本轮交接目录：`~/.local/share/fishbot/cloud-jobs/kaggle-20261024/`。
现有项目计划维护任务状态；不新增调度器或常驻Web服务。

来源：[官方Kaggle CLI](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md)、
[kernel metadata](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md)。
