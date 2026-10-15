# Findings

- 原节点203行只接收String文字；CPU能力仅探测无后端选择，duration未执行，无VAD/ASR，DOCK无执行。直接最终cmd_vel与当前守卫冲突。
- 原3测试通过但“不要前进”“往后走”“前进，马上停下”均误判前进。全仓语音标识原仅节点/测试，不在启动或工作台。
- 采用现有Wiki/ROS2与FishBot的源时间、任务回执未知不重发、最终唯一速度发布者和多层验收；本轮只补语音输入和任务薄适配。
- 默认新独占domain121与voice API9094候选，启动前由root核对空闲；旧107/114保持。ASR引擎与权重待按本机和官方来源核实，不把CPU标志当加速成绩。
- 复用选择：本机无ASR，采用官方Vosk0.3.45＋small-cn-0.22（42MB，Apache2）及已有FFmpeg；模型zip SHA3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba，权重与venv在项目外，不上传录音。官方https://alphacephei.com/vosk/models、/install与vosk-api/python/example/test_ffmpeg.py已核对；只写格式/来源薄适配，无自研识别器或ISA性能声明。
- 系统libespeak-ng合成的四句预检ASR均不可靠，原音频/输出保留私有；没有据此调关键词或自动执行。补用Piper1.8.0纯CPU神经合成五句预检：停止/左转/装货运输匹配，前进/否定转写错误且意图拒绝。该huayan模型卡标Dataset License Unknown，模型和所有合成素材仅留本机试验，不进入源码或公开产物；不把五句预检当真实环境准确率。模型/音频来源hash记私有fixture。
- 现有mission API原随机任务ID、取消只接受空对象，已薄扩展可选mission_id和绑定ID新鲜取消。timeout_s由原任务owner单调时钟执行取消，voice网关死掉也不依赖语音节点定时发零。
- 网关与UI原首轮accepted合同不一致，由根审查发现并在ROS之前修正；现43网关＋30核心＋26前端专项通过。真实ASR错误保留具体reason，推理不持任务锁。
- 框架DOCK只接受配置purpose=charging的独立adapter，缺配置明确不可用，不拿SO101工位/普通导航冒充回充成功。跨mission/coop外部客户端原子排他尚无共同锁，实际121面板仅voice独占写入口；不宣称全局多客户端仲裁完成。
- 收尾核对发现RPP配置allow_reversing=false，后方航点可能先掉头再前进，不能实现字面“倒车”。因此复用本机Jazzy原生BackUp，保留原owner、几何扫掠、取消、期限与速度后处理。默认航点API和Nav2参数保持兼容；源版本变化后的补验独立记录。
- 浏览器真实MediaRecorder使用隔离合成麦克风，两种宽度均输出WebM并经FFmpeg/Vosk实际转写；循环输入出现多余尾词，意图明确拒绝且执行请求为0。正常stop关闭轨道；这只证明录音与拒绝链，不是人声准确率。
