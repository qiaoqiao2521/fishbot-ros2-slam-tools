# 语音任务入口

在工作台点击“语音任务”。连接语音服务后，输入文字、上传音频或点击录音。先检查意图和距离/角度，再确认执行。停止录音只转写，不自动执行；失焦或离开页面会丢弃当前录音并关闭麦克风。

支持单个有界任务：前进/后退5厘米至1米、左右转大于0至180度、返航、配置地点和装货运输。肯定的停止优先于其他动作；否定句、混合动作、未知文本和非法参数明确拒绝。返航点取本会话首次导航派发时的估计位置，并绑定地图身份，不固定原点。

## 数据与控制流

`录音/文件 → FFmpeg归一 → Vosk离线转写 → 意图预览 → 显式确认 → voice gateway → 原任务API → Nav2/车臂执行`

文字直接进入同一预览和确认。语音不创建Twist发布者，既有速度平滑、碰撞监测与底盘保护继续负责执行。`/voice_raw_text` ROS入口也只接受带原时间/ID的JSON envelope，通过网关单次转发；`/voice_command`广播任务回执。缺少ROS不会假装上线。

后退使用原生Nav2 `BackUp`，由MissionBridge从新鲜定位派生后方目标并检查完整扫掠。它保持原停车朝向，不用后方航点触发掉头前进。前进、转向、地点和返航继续复用原航点任务；实际走法仍由原Nav2规划与碰撞检查决定。

- 网关只绑定loopback，端口默认9094、仿真域121。上游必须显式匹配仿真模式/域，重定向、跨源和不完整请求被拒绝。此本机接口不提供公网身份认证。
- 命令携带UUID、会话、递增序号、原发出时间和最多5秒TTL。同UUID相同输入只返回原回执，冲突或过期输入不重发。页面连接时同步服务端序号，刷新页面不会从1开始重放。
- 音频来源绑定会话、原文字、接收时刻和一次命令，识别耗时计入5秒源龄。过期必须重录；编辑文字会显式清除音频来源并按文字任务重新预览。
- 回执丢失保留原命令ID，手动GET核对。身份已经确认的原任务可显式STOP；其他动作继续禁止重发。停止请求被接受仍不等于已停稳。
- 相对导航30秒、地点/返航120秒上限由原MissionBridge的单调时钟取消原目标，不依赖语音节点持续发零。车臂仍沿用原360秒上限。原API兼容旧调用，同时接受可选mission_id和带ID/时间的取消。
- 回充只接受明确声明`purpose=charging`的配置适配器。默认未配置，因此拒绝回充；SO101工位停靠和普通导航到桩旁均不算充电成功。

`accepted=true`表示已核对上游接纳回执，`false`表示明确拒绝，`null`表示未知。上游任务终态、原生ROS Action UUID/状态和独立物理评分分别展示。回执与预览不能代替物理验收。

## 离线识别复用

采用[Vosk Python API](https://github.com/alphacep/vosk-api) 0.3.45和官方[small-cn-0.22中文模型](https://alphacephei.com/vosk/models)，模型42MB、Apache-2.0。格式转换复用现有FFmpeg，参照[官方输入说明](https://alphacephei.com/vosk/install)与[test_ffmpeg示例](https://github.com/alphacep/vosk-api/blob/master/python/example/test_ffmpeg.py)。项目只实现输入边界与任务薄适配，不自研ASR/VAD，也不把读取CPU标志称为硬件加速。识别器内部端点检测加PCM能量门禁拒绝静音；语气词过滤仅处理转写文字，不提供商业剪辑式音频停顿删除。

音频限定WAV/WebM/Ogg、0.15至15秒、最多4MiB；WebM/Ogg经固定stdin转换，不允许FFmpeg读取网络或本机任意文件。模型与运行环境留在缓存，服务不保存录音。词置信度只是模型输出，不是任务成功概率。当前小模型仍会识错，不做谐音动作猜测；用户需核对转写和参数。生产准确率、口音/噪声覆盖和真实麦克风环境尚无统计验收。

## 启动

首次在本机安装独立CPU识别环境和固定模型；该命令会下载官方依赖与模型，不启动任务：

```bash
./fishbot.sh voice install
./fishbot.sh voice asr
./fishbot.sh voice parse '不要前进'
```

默认环境为`~/.cache/fishbot/edge-voice-20261015/venv`。`FISHBOT_VOICE_RUNTIME`可覆盖缓存位置，`FISHBOT_VOSK_MODEL`可指定已存在的中文模型。启动服务不会自动下载。固定模型zip SHA256为`3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba`；这是本轮官方来源下载的内容固定值，不是上游签名声明。

纯导航配置，分终端启动：

```bash
./fishbot.sh voice sim
./fishbot.sh voice serve --allow-origin http://127.0.0.1:5180
```

从控制站前端目录启动工作台：

```bash
FRONTEND_PORT=5180 VITE_FISHBOT_SIM_DOMAIN=121 FISHBOT_MISSION_PORT=9071 FISHBOT_VOICE_PORT=9094 npm run dev -- --host 127.0.0.1 --strictPort
```

打开`http://127.0.0.1:5180/workbench#workbench-voice`。网页麦克风需浏览器支持和用户主动授权；不支持时上传音频或输入文字。loopback不表示手机可直连。

车臂配置复用[原协同启动](COOPERATION.md)，选择独占域121与API9091，再启动语音适配：

```bash
./fishbot.sh voice serve --no-mission --coop-url http://127.0.0.1:9091 --allow-origin http://127.0.0.1:5180
```

切换配置前确认原任务终态与停稳，停止原语音服务和对应仿真实例。每域只能有一个物理世界。若同时配置导航/协同适配器，必须属于同一个世界；网关不提供跨两个独立API的原子全局锁，不得让其他客户端同时争抢写入。本轮分别验收导航与车臂配置，不宣称多客户端竞争已解决。

## 接口与验收

- `GET /voice-api/state`：会话、last_sequence、能力、最新回执和原任务状态。
- `POST /voice-api/preview`：`{text}`，不派发。
- `POST /voice-api/transcribe`：原始音频body与正确Content-Type，返回原来源ID/时刻与意图，不派发。
- `POST /voice-api/execute`：`{command_id,session_id,sequence,issued_at_ms,ttl_ms,text,asr_id?}`。

原`/sim-api/mission`额外支持`{mission_id,operation:"backup",distance_m,issued_at,timeout_s?,map_id?,rules_revision?}`。距离为正数0.05至1米；不接收调用方`waypoints/return_home`，防止输入目标与实际倒车扫掠不一致。结果保留原任务编号和`native_action:/backup`，取消与期限沿用原owner。

`--places`接受显式名称到`{x,y,yaw}`的本地JSON。地点名必须是单一可识别名称；含动作词或连接词的歧义名称可被拒绝。`--dock-url`只接固定loopback充电适配器，其`/dock-api/state/start/cancel`须保留同UUID、仿真域、真实任务终态与purpose标记；本轮未配置或实测回充适配器。

定向测试：`python3 -B -m unittest tools.tests.test_edge_voice_node tools.tests.test_voice_asr tools.tests.test_voice_bridge`。项目`./fishbot.sh check-feedback`包含语音边界与前端合同，不自动启动ROS。实际语音、Nav2与运输结果及保留失败见[本轮进度](../plans/edge-voice-framework-20261015/progress.md)。硬件ISA只作诊断，真实设备、嘈杂环境和生产可靠性仍需相应验证。
