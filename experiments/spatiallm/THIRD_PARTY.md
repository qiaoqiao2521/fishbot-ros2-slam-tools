# 来源与许可边界

核查日期：2026-10-14。只记录实际来源与声明，不推定无条件商用许可。

| 对象 | 固定来源 | 已核查声明 |
|---|---|---|
| SpatialLM源码 | [8913c44](https://github.com/manycore-research/SpatialLM/tree/8913c44d84a450c53e9340b13317f8cf7144a738) | 根LICENSE与pyproject声明Llama3.2；不称整个仓库Apache/MIT |
| Layout/entity | 上述源码`spatiallm/layout/`，entity注明SceneScript派生 | [SceneScript](https://github.com/facebookresearch/scenescript/blob/main/LICENSE)声明CC-BY-NC-4.0；本模块从外部固定源码引用，不复制改授权 |
| Qwen1.1发布权重 | [b3ae9ad](https://huggingface.co/manycore-research/SpatialLM1.1-Qwen-0.5B/tree/b3ae9ad7a8689bc130a242c7f922a8cc290c1b59) | 模型卡声明CC-BY-NC-4.0；Qwen底座Apache不覆盖此发布权重 |
| Sonata | [官方项目](https://github.com/facebookresearch/sonata#license) | 代码Apache，权重CC-BY-NC-4.0，二者分开 |
| 官方样例 | [Testset revision 60bab76](https://huggingface.co/datasets/manycore-research/SpatialLM-Testset/tree/60bab76febb0c9635f58e156f32e906afc91a499) | Manycore Research，CC-BY-NC-4.0；GT与对应点云，未冒充模型预测 |
| FishBot模型 | 仓库既有`workspaces/fishbot_mujoco_ws/.../mjcf/fishbot.xml` | 沿用原项目来源与许可说明，本模块未改模型参数 |

固定样例`scene0000_00`：

- layout：2085字节，SHA256 `2f3314cee1c864061b20459793a91aafa49bce111325a199f5dbe0340b918893`。
- 点云：10,968,451字节、685,513点，SHA256 `12d8cf9c239791260166837d090334915f7056537a2e35c97959d9842a6c5f92`。
- 官方解析器与实体源码的实际文件哈希由导入器强制校验。`visualize.py`另固定SHA256 `a658b4d640968013aebb4b69836f9a91f7e90d994636fce9681d286089270366`。

代码、数据和模型保持各自许可及归属。原始文件在外部缓存保留许可。校正和几何导出记录输入归属与修改；不把转换产物宣称为不受来源限制的资产。本模块适用于当前个人离线研究，商业用途须另核对相应许可。
