# Findings

- launch无条件指定physics.jsonl，sim以50Hz源状态write/flush，duration默认None，任务结束和空闲不停止。既无容量上限，也无轮转。
- 三个历史文件各只读首2行：约33–36KB/帧，按名义50Hz估算6.1–6.4GB/小时；重复source占75.6%–78.3%。这是小样本估算，不能冒充原90GB文件全程统计。
- 本轮旧session目录已不存在；可读FishBot进程无被删但仍打开的physics/observer fd。当前仅121/122小ROS日志增长，未发现活跃physics writer。不声称全系统不可读root进程已排除。
- oracle评分读取独立observer.jsonl，不读滚动诊断physics。原评分在内存已去掉第二个physics起的source.manifest，因此在磁盘按实际内容去重可沿用语义；ROS发布消息保持完整。
- 不新造通用日志系统：滚动诊断复用Python标准RotatingFileHandler；证据只加薄预算/身份去重。知识采用Wiki/ROS2 与 FishBot第17节：写入失败不跳过清理、计数和省略必须明示；第20节：不完整采样不冒充成功。
- 原write/flush在物理发布调用链中，异常会经过finally与launch on_exit Shutdown结束整组。新诊断sink隔离运行时记录失败，ROS状态保留具体原因，节点继续发布。标准库emit已包含flush，因此原独立record_flush计数为0，元数据明确说明计入record_write，不能伪造计时次数。
- 诊断日志使用墙钟限频；原50Hz是源时间发布周期，实际墙钟写入率取决于实时因子。字节上限独立于频率，不靠降频保证永不写满。
- 原始observer不轮转；先核完整性再解析可能半写的JSON，失败统一关闭最终验收声明。初审发现passed=false但live/task/safety声明仍true的可能，已修正并加反例。
- 32MiB不是整个运行目录预算；RGB/相机/检测素材本轮不改，未声称所有缓存都有同一限额。原session现已清理，历史文档补充原件现存状态，未改变历史评分。
