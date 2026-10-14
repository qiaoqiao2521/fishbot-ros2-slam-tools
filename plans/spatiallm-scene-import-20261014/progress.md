# 进度

## Current

软件转换、编辑器和真实MuJoCo验收完成。最终65项测试、100物理步、源码指纹与网页负例已读回。19文件代码提交`03e37eb166eeff553d9149d55a934e4d6db7c13b`已推送至独立特性分支并由`git ls-remote`读回一致；此收尾记录仅更新计划。
官方单例推理尚未运行。已联系FishBot owner，等待其RGB时序批次安全收尾后的GPU窗口。

## Done

- 独立worktree与分支建立，main owner已收到协作边界。
- 官方GT、点云与来源哈希读回；源码/权重/编码器/样例许可分层。
- 严格导入、逐次校正、官方文本序列化及MJCF导出实现；18实体完整保留。
- 6面零厚度墙必须显式校正。门洞形成真实空隙，窗采用明确保守碰撞板。
- MuJoCo 3.3.5实际编译、100步独立验证通过；浏览器导出20步通过。带FishBot模型为29几何体、9位置自由度、2执行器。
- 接触探针检查13个墙/窗实体；2个门各在中心及较低截面采样9点，无墙碰撞。此证据不等于整车导航验收。
- 原始官方点云和GT经未修改的官方visualize.py生成1,697,207字节Rerun记录；原生rrd读取确认点云及结构图层。
- 桌面和390px网页实际选择、参数校正、导出、真实PNG及下载通过；键盘Enter可选门实体。
- 实际下载scene.xml/layout.txt哈希与manifest一致。原输入为GT，7次人工校正保留before/after。
- 65项行为测试通过，无跳过；涵盖真实物理验证、旧版本409、篡改下载409、失败后无下载、来源/请求边界、错误输入和伴随证据缺失/变化。
- 独立模型环境导入通过：Torch2.4.1+cu124、flash-attn2.7.4.post1、spconv-cu1202.3.6、torch-scatter2.1.2+pt24cu124、官方SpatialLMQwen类。
- RTX3050 capability8.6、BF16可用；参数估算约1.425GB，不包括激活/KV。不能据4GB型号直接判定不兼容，实际峰值仍未核实。
- SpatialLM1.1-Qwen-0.5B固定revision b3ae9ad7a8689bc130a242c7f922a8cc290c1b59下载完整。safetensors 2,414,130,784字节，SHA256 ed2e1ca161d9ca51342bdee27e801ff7aac4f6ef4b2585f530b7ba657ed8a827。

## Evidence locations

原始来源、权重和运行输出保存在Git外的`~/.cache/fishbot-spatiallm/`。

- `acceptance/official-gt-load-v1/`：实际MJCF、布局、manifest和100步证据。
- `acceptance/official-gt-load-v2/`：更完整取景的真实PNG及物理验证。
- `acceptance/official-gt-load-v3/`：最终validator指纹、100步和真实PNG。
- `acceptance/official-gt-load-v4/`：伴随证据核查修复后最终100步及真实PNG。v1–v3保留为历史复验，不能替代v4指纹。
- `acceptance/official-gt.rrd`及对应manifest、`rrd-contents.txt`：官方查看器输出和读回。
- `browser-scene.xml`、`browser-layout.txt`、`browser-manifest.json`：实际浏览器下载。
- `editor-desktop.png`、`editor-mobile.png`、`editor-export.png`：根已查看的实际截图。
- `editor-export-final.png`、`editor-mobile-final.png`：最终代码真实截图，根已查看；移动端documentWidth=390，plotWidth=360。
- `browser-scene-final.xml`、`browser-manifest-final.json`、`browser-validation-final.json`、`browser-layout-final.txt`：最终网页实际下载。
- `browser-scene-v4.xml`、`browser-manifest-v4.json`、`browser-validation-v4.json`、`browser-layout-v4.txt`：当前校验器下的实际网页下载；6次显式墙厚校正，20步和29几何体。
- `editor-export-v4.png`、`editor-mobile-v4.png`：当前校验器下实际截图，已查看；390px宽度和键盘door_0选择再次通过。
- `acceptance/handoff-evidence.json`：16个模块文件源码指纹、当前验收摘要和外部产物哈希。
- `inference-preflight.json`及`model/SpatialLM1.1-Qwen-0.5B/`：兼容导入与固定权重缓存。

## Repairs and limits

- 浏览器验证发现批量墙厚输入的step与0.12默认值不匹配；改为0.001后真实保存通过。
- SVG的hidden属性没有被布尔赋值移除；改为显式移除后平面图可见，桌面/移动端已读回。
- 空机器人坐标原先可被Number空字符串转成0；增加必填和条件禁用后，空x的valueMissing=true、表单valid=false；关闭机器人时valid=true。
- 错误布局`wall_0=Wall(bad)`实际显示`line 1: wall expects 8 parameters`，原18实体未改变；随后合法用户布局读入成功，输入身份显示为用户提供。
- 旧v3执行validator SHA256为`6baaf3c241a5870970ce3ecd27f70b55015b37b72e4d52a284bb876cc0cf582d`。
- 审查发现缺layout.json会导致门探针为空仍通过，根已复现。修复后强制伴随文件存在并核对scene/layout SHA，加载前拒绝缺失/不一致；5项新增负例通过。
- 当前v4执行validator SHA256为`f16aafa7b7b7e8e46ce447e8282e5ae228af1c2c64a2c3c8990c89abb0844345`，独立100步和当前网页20步validation均一致。审查Agent已只读确认闭合，无剩余代码交付阻碍。
- Rerun依赖链最初安装到pyarrow26，与NumPy1.26不兼容；固定pyarrow19.0.1后实际记录/读回通过。
- 原始source、样例、模型、运行输出和依赖环境均不进入Git。
- 不连接ROS、不操作实机、不停止107/114、不修改生产地图或主区并行工作。

## Remaining

官方推理由根在owner提供GPU窗口后接续；若窗口尚不可用，将此条件和最短运行入口一并交接。
接续入口为`experiments/spatiallm/INFERENCE.md`，命令尚未执行，当前不声称模型推理或评测通过。
主区整合由FishBot owner串行执行，当前分支不同时推main。

## Delivery

- 分支：`codex/spatiallm-scene-import-20261014`。
- 既有目标：`qiaoqiao2521/fishbot-ros2-slam-tools`，未更改可见性。
- 代码提交：`03e37eb166eeff553d9149d55a934e4d6db7c13b`。
- 基线：`aab0da4`。只包含本模块和本计划，不包含主区视觉停靠改动。
- `experiments/spatiallm/README.md`提供安装、准备、运行和测试入口。
- 当前本地演示：`http://127.0.0.1:8867`，独立服务，不连接ROS。
- 项目总协调对话：`01a13a98-c3ea-7760-aeb8-e5a7396a5574`。
- FishBot主区整合及GPU窗口协调：`01a101eb-92b4-78b3-a725-361dc7342c05`。
- 软件交付完成，官方推理和main整合仍明确待接续。此模块没有改变107/114运行实例。

## Knowledge closeout

already_covered：采用既有开发协作接入的“静态结果与实际验收分层”和独立项目边界原则，已用真实物理/浏览器证据落实。
pending：SVG属性与空值转换的通用经验记录在此计划。按派发边界不编辑共享Wiki，是否回写由协调根决定。
