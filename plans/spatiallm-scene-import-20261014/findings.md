# 发现

- 主工作区main=aab0da4且视觉停靠源码仍在修改；已通过原对话告知隔离分工，不复制dirty状态、不编辑main。
- SpatialLM源码8913c44d84a450c53e9340b13317f8cf7144a738；官方testset60bab76febb0c9635f58e156f32e906afc91a499。GT scene0000_00共6墙/2门/1窗/9bbox，layout SHA2f3314cee1c864061b20459793a91aafa49bce111325a199f5dbe0340b918893；点云SHA12d8cf9c239791260166837d090334915f7056537a2e35c97959d9842a6c5f92、685513点。
- 官方Layout.from_str会吞异常并跳过错误引用，Bbox把负尺寸abs化；薄验证层必须先拒绝。to_boxes将墙厚设0，不适合碰撞导出。
- 最终txt已反量化并平移到世界米制，不得二次反量化；z向上、墙端点底线、opening中心、bbox全尺寸/yaw弧度。
- 源码根声明Llama3.2，entity有SceneScript派生；Qwen发布权重、编码器权重及Testset是NC边界，底座Apache不覆盖整个模型。外部源码与数据不复制入Git。
- 现有栅格/固定工位工具与React控制站未提供语义layout编辑或MJCF导出；新增模块只补已核实缺口，界面不接生产ROS。
- 本机RTX3050 Laptop 4GB sm8.6，观察空闲约2.89GB；没有依据绝对拒绝GPU型号，推理峰值需单独评估。
- 采用既有开发协作接入/Memory的静态检查与实际验收分层，范围只此实验模块；根总研究文件和共享Wiki不写。
- GT墙厚为0时直接碰撞导出并不可信。显式6墙厚度校正及7次细调两个实际网页回合均保留原身份和before/after。
- 原生MJCF模型加载/步进、墙负例和门洞采样必须分别验收；合成JSON或仅XML生成不能替代。家具bbox及窗板始终标明保守近似。
- 伴随layout缺失可使门洞采样退化成空列表而假通过。最终校验器要求scene/layout/manifest三者完整，先核对两份输出哈希，再进行加载、步进和几何探针。
- 浏览器实际操作发现三项API测试覆盖不了的UI问题：墙厚step与默认值冲突、SVG hidden属性未移除、空机器人坐标转0。已修复并实际读回。
- 模型环境和权重完整不代表官方推理通过。2026-10-14准备阶段CLI未运行；2026-10-15owner释放窗口后，固定官方单例真实执行完成。16预测实体与GT18实体存在差异，不以单例退出0推断精度。
- 编辑校正复用同一个document_id并推进revision；机器人默认起点应按文档身份初始化，不能按每次修订重置人工选择。当前UI保护四个起点参数，导出文件和实际MuJoCo初始状态已核对一致。

## Rerun保存文件的收尾边界

原`official-gt.rrd`实际1,697,215字节、SHA256 `65007fc3348ba1e1aa14ef2bba05e7fdba63634e8e478b2d776b97e1fde6ec41`，原manifest声明`20654cd1456c3919f39295a4a78cf146e1e7b2c824dc62f867700acf0fe4a1c6`。原进度写出的1,697,207字节是退出前观测，属于失配证据，原件全部保留。

旧wrapper独立复现：正常退出前1,660,631字节，退出后1,660,639字节，SHA变化。受控探针中`rr.disconnect()`使RRD增加8字节；随后的SDK shutdown及进程退出均保持相同SHA和大小。Rerun0.21.0的`script_teardown()`只处理serve等待，并不关闭save文件；Python没有可用的`RecordingStream.flush`。

复用[官方0.21.0 disconnect API](https://ref.rerun.io/docs/python/0.21.0/common/initialization_functions/#rerun.disconnect)关闭保存文件，再生成hash/字节数。无需子进程writer或固定等待时长。关闭失败、上游失败均保留partial输出并传播错误；已有RRD或manifest拒绝覆盖。

真实新记录`acceptance/rerun-finalize-20261015/official-gt-finalized-v1.rrd`为1,716,075字节，SHA256 `eb967c10525b643b3e67d86d53b1d654da87d751d24350d421ab9e1a700b2371`，与manifest匹配。原生`rerun rrd print`正常读取点云及6墙/2门/1窗/9bbox，读取前后两次hash稳定。本次仅CPU生成和解码，没有GUI、GPU、ROS或新MuJoCo运行。

## 官方预测单例读回

冻结0d执行产生的`inference-single-v1/handoff-manifest.json`已逐项核对14产物及17执行源，receipt起止官方源码hash相同。原预测保留16实体，6墙显式校正0.12米后形成CPU100步衍生场景；不补入GT缺失实体。采样GPU峰值2014MiB是每秒采样下界，所属进程和lease已释放。原始推理、衍生转换与当前wrapper修复使用各自源码证据。
