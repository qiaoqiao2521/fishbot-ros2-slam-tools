# CY 地图规则几何备选

状态：独立代码备选，未接入 FishBot 页面、规则存储或 Nav2。项目现有能力和验收入口见 [地图规则](../../docs/MAP_RULES.md)。

## 来源与范围

`map_geometry.py` 摘录自 CY `/opt/re-workbench/re-packages/restricted-zone-pilot/adapter.py`，来源仓库提交 `ad7c833`（2026-10-18）。保留了原适配器的四角禁区、线段虚拟墙编解码和输入形状检查；去掉了厂商 RPC、protobuf、超时和清扫区数量等无关内容。`DomainFormatError` 保持原错误名称，改为继承标准 `ValueError`，以便独立使用。

该适配器是工作台基于 Roborock Android 4.74.08 静态观察制作的研究代码，不包含 APK 或反编译源码。来源包未发现独立许可证，后续公开分发或合入其他许可范围前需核实权利和许可。原厂动态保存、坐标单位与坐标系尚未证实。

## 使用

```python
from map_geometry import decode_forbidden_zone, encode_virtual_wall

zone = decode_forbidden_zone([0, 0, 2, 0, 2, 1, 0, 1])
wall = encode_virtual_wall({"start_x": 0, "start_y": 0, "end_x": 1, "end_y": 1})
```

在本目录运行 Python 时可直接导入。`encode_forbidden_zone` 和 `decode_virtual_wall` 提供反向转换。输入四角顺序由调用方负责；函数只检查点数和数值类型，不检查有限数、闭合、自交或有效面积，也不做坐标转换。

FishBot 的 `no_go` 目前仅支持矩形，坐标为 map 坐标系的米，墙使用 `kind=wall` 和两点 `points`。本备选允许非轴对齐四边形，不能直接视作 FishBot 可执行规则；实际接入前需先明确坐标变换、矩形和几何校验，再复用现有 DTO、规则应用确认与 Nav2 链。未执行此映射。

局部验证：`python3 -m unittest discover -s plans/cy-map-rule-candidate -p 'test_*.py'`。这些测试仅验证独立编解码，不代表厂商协议或机器人导航验收。
