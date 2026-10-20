# 进度

## Current

P0–P3本轮实施与实际面板验收完成。起始工作区干净，源码为d9fa3f5。首轮三个真实ROS/MuJoCo案例已完成并清理；保留失败和取证缺口，正在定向修复。

## Done

- 确认沿用现有MuJoCo执行链及独立评分。
- 发现可直接采用的官方三维雷达插件，避免自行实现射线传感器。
- 三个案例独立汇总；非致命元数据缺失不阻塞批量运行。
- 默认采用尺寸化合成参考场景。两次定向定位没有取得当前私有工作图路径，没有继续搜索；仍提供source-map导入接口，不宣称默认场景为实测住宅。
- 官方3D包装器0.1.1与扩展均使用当前C++ MuJoCo3.12.0 vendor。原生250步、16行均有距离返回；不是ROS导航验收。
- 新增只读ContactAudit。首轮探针发现C++17中迭代临时Parameter数组引用导致段错误；已改为局部值并重建。修后实际3/3：地板接触排除、墙碰撞被记录、缺body明确不可用。每例1100步，插件不改qpos/qvel/time，domain131清空；首轮exit139独立保留。
- 前端报告组件、固定只读报告端点及已有工作台21项局部测试通过。导航往返与货物交付命名分开，报告可编辑、可重读。
- 仅构建fishbot_mujoco包成功。现有runtime的ament前缀缺local_setup提示保留，不影响本次构建；没有全仓构建或完整回归。
- 网页初轮5188/results读取acceptance-a，最终切换为D报告。后台真实Chrome完整16项检查通过：GET取报告、三个实际结果、导航范围、390px无横溢和零ROS写入；另有最终D的实际GET/三行UUID核对。原runtime GET有4项资源500，单列为现有离线链路状态。
- 首次wrapper因setup.bash与nounset不兼容，在启动ROS前退出。移除wrapper的nounset后正常启动，未修改ROS脚本。
- acceptance-a：clear往返完成、原生4、独立停车/轨迹/碰撞检查全过，实际碰撞增量0；detour原生6/航点104，RPP预测轨迹碰撞反复失败，实际碰撞增量0，路线未完成；blocked原生5，取消/清理/连续停稳全部通过。
- 三例均有360×16真实点云，且全局/局部Nav2订阅，低障碍区域有21个lethal格。独立读取基图该区域100格均为254，实体存在但静态地图未画入。
- 首轮三维探针吞掉TF异常，导致target_cloud为空，故clear/blocked顶层incomplete、detour failed。未将costmap存在占用替代同源回波证据。
- acceptance-b仅复现clear并补诊断：5075次均Extrapolation into future。原时间戳点云比TF早到0.35–1.25s，而探针只保留最近5帧；缺口属于探针待配准队列/回调处理，不据此改控制器或以latest TF替代。b仍记incomplete，不改写旧报告。

## Knowledge

already_covered：采用Wiki/ROS2 与 FishBot第19/20节的真值、观测、动作与交接分层经验。本轮暂无新增通用结论。

## Next

本轮闭环完成。后续选定真实地图或新底盘，再核对完整足迹、转弯扫掠和传感器标定；当前不自动派发新任务。

## C/D接续

- C轮三例真实完成并清理：clear passed，blocked passed；detour途中到达目标，但90秒期限到达取消，仍failed。末段仍在返程，不称卡死。
- 探针改为单一executor持续回调、有限待配准队列后，C三例均五项3D证据完整。clear原stamp14.022s取得56个低矮物点，源龄0.052s、TF等待0.0349s。原高度门槛、控制器与物理评分不改。
- D轮仅给detour独立120秒，保持动作/控制/物理评分源码后再次运行全部三例，全部通过。不将延长预算称为算法精度改进；运行中准备错误统计修复只影响报告，不改变该轮动作。
- 有效源码局部测试：Python29项、网页21项通过，生产构建成功、受影响TS lint通过。浏览器QA16项通过。构建保留旧Browserslist与既有大chunk提示，不扩展为全站优化。
- 根审查另发现准备失败可能被总表省略。已将准备错误保留为unknown/incomplete行，正常例继续；该统计修复不改变D的物理/动作路径。新增真实prepare-only坏输入回归，相关17项通过。

## 最终D轮验收

私有输出：`~/.cache/fishbot/scene-validation-20261020/acceptance-d/`。当前工作台`http://127.0.0.1:5188/results`读取该报告。既有A/B/C原始报告与各次launch/mission/diagnostic仍保留。

| 工况 | 任务 / 原生UUID | 终态 | 路线 / 验收 | 实际碰撞增量 | 停稳源时间 |
|---|---|---|---|---|---|
| clear | 0a66d552-e3ba-4851-aa96-5bee3d039a8b / 637309d6c61a4a1c999aea43e2867841 | 4 | 完成 / passed | 0 | 2.240s |
| detour | a3088234-9e5b-4c69-983b-656838c84798 / 9604edf7fffd4ca6922a44088a8c3927 | 4 | 完成 / passed | 0 | 2.364s |
| blocked | bab2420a-7256-4b48-ae58-583d00024384 / 1c1ab5325f044c32a3e5e72c5e6aa32f | 5 | 未完成 / 正确取消passed | 0 | 3.796s |

三例所有独立checks均passed、3D探针均complete且各有56个低障碍点。clear末误差0.0576m/0.1436rad、净距0.1818m；detour行程8.2849m、末误差0.0622m/0.1758rad、净距0.04287m。沿用原路线评分容差，不套用更严格的视觉Dock评分，也不声称提高了精度。

每例cleanup_complete=true。结束后独立`ros2 node list --no-daemon`在domain130为空，9100无监听。仅保留本轮只读报告网页5188。root核对原始JSON、所有checks与各case实际预算；构建、29项Python、21项网页、16项后台浏览器QA和三项原生接触探针构成不同层证据。

源码有效改动、SpecMesh与项目入口按当前已核验qiaoqiao2521既有origin/main收尾交付。运行数据、地图、二进制扩展和浏览器日志均保留私有缓存，不提交；源码依赖安装与后续入口见docs/SCENE_VALIDATION.md。
