# 控制站视觉改版

## Goal
用户明确选择 Figma，要求解决根首页米色渐变、大圆角、信息密度低的问题，并落实到现有 App。

## Scope
根首页整体重排、四工作区统一导航、共享组件与视觉 tokens、桌面和手机布局；Figma 提供可编辑设计。
复用 React、Lucide、Zustand、现有持按控制、雷达、导航、任务和相机缓冲。无需新增前端框架或依赖。
不启动运动，不改 ROS/物理、任务状态、网络、停止语义或固件。Figma 数据为设计示例。

## Design
蓝白工作面和深蓝侧导航；中文层级；小圆角、平面表面；状态横条代替 hero。控制与机器人观测并排，地图和日志紧随；技术来源放可展开详情。
Tokens: background #f3f6fb, surface #fff, ink #172b4d, sidebar #14263d, primary #2563eb, border #dde5ef。
字体优先 Noto Sans CJK SC / Noto Sans SC，数据使用等宽数字。旧 Aptos Windows 字体在当前 Linux 无对应字族。

## Acceptance
- Figma 可编辑层、组件与文字，提供读回和视觉检查；不把截图当设计成果。
- 根首页937px首屏可见控制与观测；1440px与390px无水平溢出。
- 所有工作区可导航；保留停止、持按松手、日志导出、地图、任务状态与来源提示。
- 全前端测试、类型、lint、domain107生产构建；隔离浏览器拦截所有写请求，无新运动。
- 当前 App 显示新版，完成源码提交推送与远端读回。

## Ownership
根负责 React/样式整合与验收。coop_ui 负责四个状态/日志组件。coop_nav_diagnostic 负责既有新建 Figma 文件。其它文件由根串行处理。

## Status
实施与本轮验收完成。配套 Figma 桌面及手机版已读回；当前网页已部署并刷新。根首页完整重排；雷达、仿真、协同保留各自工作区交互，仅统一外壳、组件和相应中性色。
