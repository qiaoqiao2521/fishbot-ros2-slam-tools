# 进度

## Current

软件转换、编辑器和真实MuJoCo验收完成。65项Python测试、100物理步、源码指纹与网页负例已读回。初版`03e37eb166eeff553d9149d55a934e4d6db7c13b`及收尾`ef1a7f6`已推送；起点修复提交`fcf0e919cbbfb75540d87227161b5758f8d1d411`完成2项JavaScript行为测试和受影响网页导出复验。有效源和最终远端tip绑定于v5交接证据；此收尾仅更新计划。
2026-10-15官方单例已由总协调根的内置helper完成：冻结0d执行26.903秒、退出0，16实体严格解析与原始/序列化ID对账通过。六墙显式校正0.12米后完成原FishBot CPU100步；未渲染、起点净空未检查，GT18与预测有差异。14产物/17执行源逐项读回一致，所属进程及GPU lease已释放。
可选Rerun原manifest失配已复现并修复：官方disconnect完成后才取hash。新真实GT RRD与manifest大小/SHA匹配，正常退出及原生SDK读取后二次稳定；4项定向CPU测试及独立复审通过。修复代码提交`6f5dd4aeef7eecdb4d112ee036083ab34f2fbc4e`，原worktree继续冻结；主区串行整合仍待owner完成。

## Done

- 独立worktree与分支建立，main owner已收到协作边界。
- 官方GT、点云与来源哈希读回；源码/权重/编码器/样例许可分层。
- 严格导入、逐次校正、官方文本序列化及MJCF导出实现；18实体完整保留。
- 6面零厚度墙必须显式校正。门洞形成真实空隙，窗采用明确保守碰撞板。
- MuJoCo 3.3.5实际编译、100步独立验证通过；浏览器导出20步通过。带FishBot模型为29几何体、9位置自由度、2执行器。
- 接触探针检查13个墙/窗实体；2个门各在中心及较低截面采样9点，无墙碰撞。此证据不等于整车导航验收。
- 原始官方点云和GT经未修改的官方visualize.py生成旧RRD；退出前1,697,207字节、实际最终1,697,215字节，旧manifest hash失配。旧原件保留为失败证据，不能声明绑定通过。
- 新RRD关闭后1,716,075字节、SHA256 `eb967c10525b643b3e67d86d53b1d654da87d751d24350d421ab9e1a700b2371`，manifest一致；原生rrd读取确认点云及18结构图层，前后hash稳定。
- 桌面和390px网页实际选择、参数校正、导出、真实PNG及下载通过；键盘Enter可选门实体。
- 实际下载scene.xml/layout.txt哈希与manifest一致。原输入为GT，7次人工校正保留before/after。
- 65项行为测试通过，无跳过；涵盖真实物理验证、旧版本409、篡改下载409、失败后无下载、来源/请求边界、错误输入和伴随证据缺失/变化。
- 独立模型环境导入通过：Torch2.4.1+cu124、flash-attn2.7.4.post1、spconv-cu1202.3.6、torch-scatter2.1.2+pt24cu124、官方SpatialLMQwen类。
- RTX3050 capability8.6、BF16可用；参数估算约1.425GB，不包括激活/KV。单例实际完成，每秒采样峰值2014MiB仅为下界，不代表精确allocator峰值。
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
- `acceptance/handoff-evidence-v5.json`：17个模块文件当前源码指纹；保留v4原件和Python不变核对，绑定2项Node行为验收和新网页导出。
- `browser-scene-v5.xml`、`browser-manifest-v5.json`、`browser-validation-v5.json`、`browser-layout-v5.txt`及`editor-export-v5.png`、`editor-mobile-v5.png`：起点保护修复后实际下载和截图。7次校正，用户起点保持；20步真实加载与PNG通过，截图已查看。
- `inference-preflight.json`及`model/SpatialLM1.1-Qwen-0.5B/`：兼容导入与固定权重缓存。
- `inference-single-v1/receipt.json`：真实官方单例退出/耗时/采样GPU/源码起止；SHA256 `a2901ac1ebb965c3f4aacd496d0e1f30990993383b8d01c75c902a0e465d0d94`。
- `inference-single-v1/handoff-manifest.json`：14产物、17执行源及预测CPU转换边界；SHA256 `4f8face87fef0f9cc863ff754408cd27ac4e7391b5b267b19a49324d857ab2a3`。执行版本是冻结0d，不是当前修订文档。
- `inference-single-v1/prediction-corrected-cpu-v1/`：显式6墙校正、原FishBot CPU100步、27geom/9nq/363sensor、12固体探针/1门2截面；原预测16实体未填入GT遗漏。
- `acceptance/rerun-finalize-20261015/`：旧入口独立复现、关闭边界探针、新真实GT RRD/manifest及`fixed-proof.json`。SDK解码读回与4定向测试均通过，无新GPU/ROS/服务。
- `acceptance/rerun-finalize-20261015/handoff-finalized-v1.json`：本轮修复源码/产物绑定、未改转换器/editor的v5继承边界、真实推理0d版本原件及最终分支远端读回。

## Repairs and limits

- 浏览器验证发现批量墙厚输入的step与0.12默认值不匹配；改为0.001后真实保存通过。
- SVG的hidden属性没有被布尔赋值移除；改为显式移除后平面图可见，桌面/移动端已读回。
- 空机器人坐标原先可被Number空字符串转成0；增加必填和条件禁用后，空x的valueMissing=true、表单valid=false；关闭机器人时valid=true。
- 错误布局`wall_0=Wall(bad)`实际显示`line 1: wall expects 8 parameters`，原18实体未改变；随后合法用户布局读入成功，输入身份显示为用户提供。
- 旧v3执行validator SHA256为`6baaf3c241a5870970ce3ecd27f70b55015b37b72e4d52a284bb876cc0cf582d`。
- 审查发现缺layout.json会导致门探针为空仍通过，根已复现。修复后强制伴随文件存在并核对scene/layout SHA，加载前拒绝缺失/不一致；5项新增负例通过。
- 当前v4执行validator SHA256为`f16aafa7b7b7e8e46ce447e8282e5ae228af1c2c64a2c3c8990c89abb0844345`，独立100步和当前网页20步validation均一致。审查Agent已只读确认闭合，无剩余代码交付阻碍。
- 协调根发现setDocument每次校正后都会重设用户机器人xy。修复为仅新document_id初始化建议；同id修订保留xyz/yaw。
- 2项Node测试实际调用生产JS状态逻辑，覆盖连续单体/批量修订保留起点、新文档重新初始化。实浏览器先填`3.25/-2.8/0.002/0.4`，再单体及批量保存，各次读回均保持；最终manifest和MuJoCo initial_qpos一致，20步/PNG/下载hash通过。
- 此补丁只改前端JS、增加Node测试及文档。所有Python源码hash与v4相同，不重复CPU全套或100步；v4原件保留，当前v5网页实际运行同一validator指纹。只读审查已确认起点修复闭合。
- Rerun依赖链最初安装到pyarrow26，与NumPy1.26不兼容；固定pyarrow19.0.1后实际记录/读回通过。
- 可选Rerun原件hash失配根因为runpy返回后save文件仍开放，进程收尾追加8字节。修复为finally调用官方`rr.disconnect()`，然后生成manifest；写入/关闭失败保留partial并向外报错，已有旁账拒绝覆盖。wrapper SHA256 `8ba4ee2867f86f56b391522638cae360b351f577b68d27b4872e862c79228ef9`。
- 4定向测试覆盖正常关闭后的绑定、上游失败、关闭失败和旧manifest保护；独立复审核对真实RRD、原生解码、输入/源码hash及错误传播通过。转换器/validator/editor源码未改，沿用v4/v5原验收；不重复100步或网页验收。
- 原始source、样例、模型、运行输出和依赖环境均不进入Git。
- 不连接ROS、不操作实机、不停止107/114、不修改生产地图或主区并行工作。

## Remaining

本轮官方单例及CPU衍生转换完成，未进行数据集评测、预测GUI渲染、起点净空或导航验收。后续新运行入口为`experiments/spatiallm/INFERENCE.md`，使用新目录并由owner协调GPU窗口。
主区已由FishBot owner串行整合，main/REST读回ddbfeab714f0cec76b755908324c82eaa5afa04f；此特性分支不独立推main。

## Delivery

- 分支：`codex/spatiallm-scene-import-20261014`。
- 既有目标：`qiaoqiao2521/fishbot-ros2-slam-tools`，未更改可见性。
- 初版代码提交：`03e37eb166eeff553d9149d55a934e4d6db7c13b`。
- 起点修复提交：`fcf0e919cbbfb75540d87227161b5758f8d1d411`。当前共20个文件，仍严格限于本模块及本计划。
- 最新交接证据：`acceptance/handoff-evidence-v5.json`，保存当前源码和产物哈希、Python验收继承边界、实际起点合同和最终远端tip。
- 基线：`aab0da4`。只包含本模块和本计划，不包含主区视觉停靠改动。
- `experiments/spatiallm/README.md`提供安装、准备、运行和测试入口。
- 当前本地演示：`http://127.0.0.1:8867`，独立服务，不连接ROS。
- 项目总协调对话：`01a13a98-c3ea-7760-aeb8-e5a7396a5574`。
- FishBot主区整合及GPU窗口协调：`01a101eb-92b4-78b3-a725-361dc7342c05`。
- 原0d软件交付完成，本轮官方单例完成；main整合仍由FishBot owner接续。此模块没有改变107/114运行实例。
- 收尾修复worktree：`/home/muqiao/worktrees/fishbot-spatiallm-rerun-finalize-20261015`；分支`codex/spatiallm-rerun-finalize-20261015`，基线`0d11a5b`。代码提交`6f5dd4aeef7eecdb4d112ee036083ab34f2fbc4e`；仅wrapper、定向测试、本模块说明/计划。最终tip与远端读回见Git及`handoff-finalized-v1.json`，不从本分支推main。

## Knowledge closeout

already_covered：采用既有开发协作接入的“静态结果与实际验收分层”和独立项目边界原则，已用真实物理/浏览器证据落实。
already_covered：源码与实际验收绑定、SVG/空值经验已在本模块记录，原Wiki通用验收原则覆盖。本worker未写共享Wiki。
updated：总协调root已将writer原生关闭后hash/manifest内部绑定经验写回Wiki/自动化开发范式与智能体协作“持久事件与复核记录绑定原件”，开发知识入口新增Rerun触发；FishBot root已读回这两处。知识库提交80ab374a3c545ebf32a6cb5c288ebd56154b1307由知识owner独立推送/REST核对；本模块worker未并行写Wiki。

## 主区最终整合

root在无活动world安全边界依次合入0d11a5b、代码6f5dd4a和文档a84d9ce。18模块/3计划与最终交接源一致；合入后69CPU＋2Node通过，零skip，1第三方弃用warning；12模块/入口文档36相对链接无缺失。固定官方推理14产物实际hash/bytes逐项核对，GPU已释放。原RRD失配原件、旧GT/起点修复版本、预测与显式六墙校正均保留；当前不宣称起点净空、导航、数据集指标或真机能力。main仅保留原release.sh未跟踪，root不执行。
