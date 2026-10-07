#!/usr/bin/python3
"""Rasterize synthetic MJCF boxes; captured room maps are never used."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    arena, output = map(Path, sys.argv[1:])
    boxes = []
    for geom in ET.parse(arena).getroot().find('worldbody').findall('geom'):
        if geom.get('type') == 'box':
            position = list(map(float, geom.get('pos').split()))
            half_size = list(map(float, geom.get('size').split()))
            if position[2]-half_size[2] <= 0.167 <= position[2]+half_size[2]:
                boxes.append((position, half_size))
    # Must match config/arena.yaml: 8.4m square, 5cm cells, origin (-4.2,-4.2).
    resolution, size, origin = 0.05, 168, -4.2
    pixels = bytearray()
    for row in range(size):
        y = origin+(size-1-row+0.5)*resolution
        for col in range(size):
            x = origin+(col+0.5)*resolution
            occupied = any(abs(x-p[0]) <= s[0] and abs(y-p[1]) <= s[1] for p, s in boxes)
            pixels.append(0 if occupied else 254)
    output.write_bytes(f'P5\n{size} {size}\n255\n'.encode()+pixels)


if __name__ == '__main__':
    main()
