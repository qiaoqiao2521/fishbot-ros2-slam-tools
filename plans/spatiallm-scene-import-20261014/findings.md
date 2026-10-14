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
- 模型环境和权重完整不代表官方推理通过。当前GPU窗口由FishBot owner协调，单例CLI尚未执行；待运行入口独立保留，GT转换成果已交付。
- 编辑校正复用同一个document_id并推进revision；机器人默认起点应按文档身份初始化，不能按每次修订重置人工选择。当前UI保护四个起点参数，导出文件和实际MuJoCo初始状态已核对一致。
