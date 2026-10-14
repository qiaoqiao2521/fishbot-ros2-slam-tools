# Progress

## Current

本次规划交付 complete。三文件规划、源码合同和实验协议已建立；标准入口与索引已补齐，文档已提交推送并经GitHub API读回。视觉停靠实现与实验 pending。没有启动实验、GPU 或运动。

## Done

- 核对 SpecMesh v1.1、项目状态与 Arena 已交付边界。
- 阅读根研究 REPORT 的项目基础、分工和实验范围。
- 保留已有未提交 release.sh 与两个独立 Git 边界。
- 只读核对 StationBeacon、原生停靠、AMCL合同、相机、SO101规划、取消/清理与独立oracle；root重算三个私有评分脚本SHA。
- 定义P0合同、P1基线、P2受扰面板、P3实际RGB的实施顺序，保留原物理与完整运输评分。
- 补CLAUDE.md、docs/DECISIONS.md与README/PROJECT/ARCHITECTURE/COOPERATION渐进入口；纠正README仍称Arena待GPU/许可的旧状态。
- 独立审查指出视觉观测与既有物理安全反馈不可混称、基线面板须预声明；root已修正两处。
- root检查6个标准核心文件、10份文档及49个相对链接，缺文件/断链均0；git diff --check通过。本轮只改文档，不重复运行代码回归或仿真。
- 有效GitHub账号qiaoqiao2521/id238822818与既有public目标仓库/main均已读回。10份文档提交954be89e723e77982691e69a4219e45256fe7691，已推送并经GitHub API确认同SHA；本条状态收尾随后单独同步，最新版本以远端Git为准。

## Remaining

- 后续实现与实验 pending，owner=root；本次不执行。

## Issues

此前把待建计划留为 pending，没有完成已派发的规划责任。本次补齐，不将计划建立称作视觉停靠能力完成。

初次猜测tools/fishbot_cooperation_oracle.py不存在，已回源实际私有缓存。一次组合文档补丁未匹配COOPERATION行，工具整体拒绝、未留下部分改动；读取准确行后重做。源码与历史证据均未修改。

独立oracle仍在私有缓存，真视觉合同与车载标定尚未实现；由root在P0审查最小持久化范围。原release.sh继续按协同计划Retained work的阻碍保留，不执行/提交。

## Knowledge closeout

already_covered：已核对Wiki/ROS2 与 FishBot第19、20节，原文准确覆盖理想信标、完整物理交接与候选配对边界。本次只纠正项目计划/索引的漏项，没有新增可复用认识，不重复改知识库；根研究总表仍由研究协调者维护。

## Next

后续实施唯一入口是task_plan的P0传感器与评分合同；root负责，实验未开始。本次SpecMesh补漏无需再等待额外运行验收。
