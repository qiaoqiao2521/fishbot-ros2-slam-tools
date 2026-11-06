"""CY restricted-zone-pilot 几何编解码摘录；不连接 FishBot 运行链。"""


class DomainFormatError(ValueError):
    """输入形状或数值类型不匹配。"""


def _require_number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainFormatError('%s 需为数值，得到 %r' % (what, value))
    return value


def _require_flat_numbers(flat, count, what):
    if not isinstance(flat, (list, tuple)):
        raise DomainFormatError('%s 需为浮点列表，得到 %r' % (what, type(flat).__name__))
    if len(flat) != count:
        raise DomainFormatError('%s 需恰好 %d 个数值，得到 %d 个' % (what, count, len(flat)))
    return [_require_number(v, '%s[%d]' % (what, i)) for i, v in enumerate(flat)]


def decode_forbidden_zone(flat):
    """8 浮点平铺列表 → 4 角点模型。

    E1：渲染方法取 list[0..3] 与 subList(4,8) 两段（各 2 个角点）绘制顶/底
    面与四面侧墙；允许非轴对齐四边形。仅元数/类型检查，无几何校验（R12）。
    """
    nums = _require_flat_numbers(flat, 8, '禁区角点')
    return {
        'kind': 'forbidden_zone',
        'corners': [[nums[0], nums[1]], [nums[2], nums[3]],
                    [nums[4], nums[5]], [nums[6], nums[7]]],
    }


def encode_forbidden_zone(model):
    if not isinstance(model, dict) or 'corners' not in model:
        raise DomainFormatError('禁区模型需为含 corners 的 dict')
    corners = model['corners']
    if not isinstance(corners, (list, tuple)) or len(corners) != 4:
        raise DomainFormatError('禁区需恰好 4 个角点，得到 %r 个'
                                % (len(corners) if isinstance(corners, (list, tuple)) else corners,))
    flat = []
    for i, point in enumerate(corners):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise DomainFormatError('角点 %d 需为 [x, y]' % i)
        flat.append(_require_number(point[0], '角点%d.x' % i))
        flat.append(_require_number(point[1], '角点%d.y' % i))
    return flat


def decode_virtual_wall(flat):
    """4 浮点 → 虚拟墙模型（C3：RR3DMapVirtualWallsModel(startX,startY,endX,endY)）。"""
    nums = _require_flat_numbers(flat, 4, '虚拟墙线段')
    return {'kind': 'virtual_wall', 'start_x': nums[0], 'start_y': nums[1],
            'end_x': nums[2], 'end_y': nums[3]}


def encode_virtual_wall(model):
    if not isinstance(model, dict):
        raise DomainFormatError('虚拟墙模型需为 dict')
    keys = ('start_x', 'start_y', 'end_x', 'end_y')
    missing = [k for k in keys if k not in model]
    if missing:
        raise DomainFormatError('虚拟墙模型缺字段: %s' % ', '.join(missing))
    return [_require_number(model[k], k) for k in keys]


