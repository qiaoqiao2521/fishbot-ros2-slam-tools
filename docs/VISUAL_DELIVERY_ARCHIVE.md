# 视觉配送原件与恢复

工作台入口为 `/results`。原件使用已指定的 Google Drive 账号保存，不把浏览器缓存视为备份。

[本轮归档文件夹](https://drive.google.com/drive/folders/1VFpP8qsDs_4dIVigPUWHp3RMd3ikaV_L)包含 v6、首次本机失败/首单成功和仓库D原件。仓库D已完整读回10卷全部tar成员与最终gzip CRC，共9632项、738,985,119解码字节。早期v1–v5的恢复入口见下表。

| 数据集 | Drive原件 | 范围 |
| --- | --- | --- |
| v1/v2 | [归档](https://drive.google.com/file/d/1YqKqoBOeLqX-3WpOhHsawCpbw2ELsn4i/view) | 冻结输入、失败、原生安装恢复包 |
| v3/v4 | [归档](https://drive.google.com/file/d/1AOuKbKN0Lwr22YB3JlDm0J-vCCcyMUGw/view) | 原始失败与来源版本 |
| v5 | [归档](https://drive.google.com/file/d/1XUIq0DCgp3GkAxdpILgFlb_CoBypZOYf/view) | 实际模型输入/候选/推理时间，原30秒规划失败 |
| v6 | [归档](https://drive.google.com/file/d/1iFbVFE0yK9FMDXJg5_BYBeBxjiL-4CMI/view) | 实际视觉装货链和旧缺件补录 |
| 首次本机批次 | 文件夹内“本机原始相机”4卷及“本机证据与成果”2卷 | 仓库B通过/A失败、早期车间和原生诊断 |
| 仓库D | 文件夹内“仓库D-essential”3卷及“仓库D-rear-camera”7卷 | 同世界B→A原评分、四次RGB-D输入/候选、原生速度袋、相机/录像及网页材料 |

## 恢复方式

每卷都是独立的 `.tar.gz`，无需拼接二进制分片。按需要下载并解压：

```bash
mkdir -p fishbot-restored
tar -xzf warehouse-D-essential-01.tar.gz -C fishbot-restored
```

先恢复essential，再按需恢复相机卷。归档内清单记录原路径、配置和缺件；保留原source时间、episode、task与Goal UUID。恢复后的旧绝对路径需要按新目录修正，不运行隐藏的路径或内容锁。

仓库D生产源码为 `08b0cb2`，远端为 `qiaoqiao2521/fishbot-ros2-slam-tools`；SO101与原生环境引用在归档清单中。当前网页源码使用本仓Git恢复。公共预训练权重、venv、可重建MJB和仿真栅格不当作独有原件归档；重建方法以原prepare命令和来源配置为准。

## 证据边界

仓库D四次官方扩散模型调用均完成，实际执行的四个抓取候选均为混合候选池的OBB几何候选。传感器材料是明确源时间的有限启动样本及原生消费探针，不是完整路线点云录制，也不证明真实Mid-360硬件或sim-to-real。原生导航终态、停车保护辅助与物理评分分别保留。

其余四个终态失败回合与仅规划对照已另存文件夹内“剩余失败”4卷，3173项、285,260,116解码字节，均已完整读回。它们不与仓库D混记。车间F也已存文件夹内“车间F-essential”两卷，170项、120,778,495解码字节，全部成员和最终gzip CRC读回通过。源输入、评分和配置不与ideal以外的视觉能力混称。已验证卷可移除本机重复上传包；独有原件须等对应Drive完整读回后再清理。


## 车间F原件

- [essential-01](https://drive.google.com/file/d/1QzusL5_U1KXzO0QNPDN6yZGy26v_9qfa/view)：原场景/清单及首批记录。
- [essential-02](https://drive.google.com/file/d/1pFf4djw5I6_Av82zFWl8IIPNFoTJ390d/view)：其余原记录与恢复材料。

车间F生产源码为 `c786c47`。原件内保留旧主货物K与命名货物完整评分的区别；A单原主货物K false仍保留，按cargo_2身份的命名K和实体交付通过。返站起步有一次0.36秒源采样空档，不插值、不称无损；两个任务均无源时间倒退。

## 本机清理与按需恢复

Drive完整读回后，本轮下载的GraspGen-X环境和缓存已移除，实际可用空间增加约9.1GB；公共权重并非用户训练产物。恢复材料包含上游源码/权重精确版本、配置、许可与 `frozen-setup.sh`。当前query运行环境保留，独有视觉输入/候选和网页材料保留。

已确认归档的相机/observer大文件本机重复件另清理521,833,724B，所在原目录留下 `ARCHIVED_TO_DRIVE.md`。重新评分前先从对应卷恢复 `observer.jsonl.gz`；不要仅因路径位于tmp/cache就删除尚未确认备份的原件。网页派生数据不承担原件备份职责。


## 最终工作台与验收补充卷

[最终补充卷](https://drive.google.com/file/d/17HMMSAJtevi2zcjrXNjQ0ASqsDKY-Ubi/view)包含最新工作台overlay、D/F独立重算、实际生产QA、原件恢复清单和清理回执。114个文件成员、41,035,374解码字节均已完整读回，成员路径/大小与声明一致。该卷保留上传前的状态快照；读回确认后的索引与最终SpecMesh以本仓Git为准，不把归档历史快照写成已知未来上传结果。

本轮原件和派生材料均已归档，重复上传包已删除；仅保留当前网页资源、源配置、必要评分/审计、恢复入口与query环境。全部失败也在对应原件卷内。
