# F2 工位高度编辑

SO101 放料坐标系的 Z 表示蓝盘底座高出台面的距离，单位米。修改后，释放点和脱离点沿原父坐标系平移；托盘尺寸与八步程序保持原样。

本轮使用独立分支 `codex/f2-workcell-20261021` 和本地 `http://127.0.0.1:5192/so101-station`，保留共享无人机工作树。运行需要含 `place_height_m` 的 SO101 执行源；通过 `SO101_ROOT` 指向该项目。工作台本身继续调用已有 `so101-runtime.cjs`。

在 SO101 仓库导入 `experiments/colab-twin/scenarios/factory-loading/raised-10mm.json`，再选择“放料坐标系”修改 Z、保存和刷新。示例的10mm已完成本地物理回合；界面允许其他非负高度，但每个新值仍需实际规划和物理验证。

定向检查：RobotStation Jest 27项、ESLint与生产构建通过。专用浏览器检查 `workbench-review-tests/station-workcell-height.cjs` 验证10mm导入、15mm编辑、五块盘体同步、父系目标、保存刷新和零运动写请求。15mm只验证编辑预览，不代表抓放成功。

依赖按原固定版本安装。复制已有安装时还需保留各workspace局部依赖；仅复制顶层node_modules会令theme误用不同版本的DataGrid，导致类型检查失败。未为绕过该错误修改上游代码或版本。

物理评测、原判据和全部回合结果由SO101仓库的 `plans/factory-loading-20261021/progress.md` 维护；本前端不另造裁判。QA输出、日志与任务记录留在忽略目录，不提交。

最终无运动复验：专用10项通过，包含现有完整任务输入逐字段保持；原桌面/390×844手机13项通过，两个端各13个STL加载，零运动请求、零页面错误。首次手机全页截图超时保留，改视口截图后通过。
