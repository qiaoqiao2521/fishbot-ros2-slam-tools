# Progress — 麦克纳姆合并

## Current

2026-10-24 运行包已迁入FishBot独立工作区，根CLI和/results底盘接入面板完成。原驱动/配置与九月修复已整合，保留Apache来源与旧目录；没有地图、会话、旧构建或嵌套Git。范围内实施和验收完成，Git修订与发布由仓库历史及最终远端读回核实；未实施新的MuJoCo麦轮模型。

## Verification

- 包发现为一个robot_base；独立colcon构建通过，输出`~/.cache/fishbot/mecanum-build/`。drive与minimal的show-args解析通过，未执行硬件launch。
- 真Jazzy节点在独占domain181、内核伪终端上验收。pty-a先复现重连漏开反馈；最小补丁后pty-b八项通过：启动归零/回传、前进/横移/旋转、超时停车、MSPD→Odometry/TF、非有限指令归零、看门狗重连恢复回传。实收vy=.05、vx/wz=0，反馈为测试合成，不是车体真值。原失败与成功报告位于`~/.cache/fishbot/mecanum-import-20261024/`；节点、线程、PTY均清理。
- 3项合并行为测试与7项耗时导入测试通过；前端4文件18项、TypeScript/生产构建与新增文件lint通过。布局检查0失败，98处相对文档链接存在，diff检查通过。
- 最终既有反馈入口：control987项中7项仍因旧planning-venv/bin/python缺失失败；mission209、autonomy61、frontend入口460项通过。与M1a首轮同一组环境失败，没有新失败；没有将460称为全前端测试全集。单列定向18项与真实ROS/PTY证据，不称全仓全绿。
- Playwright桌面/390px共10组行为通过，增加三车型入口与麦轮待接入边界检查；写请求0、页面未捕获错误0，测试浏览器已关闭，截图在`ui-b/`。只读Vite5191保留供查看。
- 外层dev工作树有既有大规模迁移和独立Git，未整仓stage或发布；本次有效运行代码只交付FishBot既有远端。旧robot_base九月dirty保留历史，后续维护以新包和本PROJECT为准。

## Knowledge Writeback

knowledge_status=already_covered。采用FishBot§19/20，新增接入状态留项目；未写共享知识或改动既有知识库dirty，owner=root。

## Next

本次源码统一维护完成。若继续车型复用，先补麦轮接触/外廓/传感器/托盘与交接模型并验证横移，再在同任务面板验收；不直接冒充已通过的第三个运输车型。连续世界计划M1b以后继续保留，owner=root。
