"""Run the pinned upstream point-cloud/layout Rerun viewer without model imports."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys
import types

from scene_import import load_layout, _official_layout_class

_VISUALIZE_HASH = 'a658b4d640968013aebb4b69836f9a91f7e90d994636fce9681d286089270366'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--point-cloud', type=Path, required=True)
    parser.add_argument('--layout', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-points', type=int, default=100000)
    args = parser.parse_args()
    if not 1 <= args.max_points <= 1000000:
        parser.error('max-points must be between 1 and 1000000')
    if args.output.exists():
        parser.error('choose a new .rrd output path')
    script = args.source_dir / 'visualize.py'
    if hashlib.sha256(script.read_bytes()).hexdigest() != _VISUALIZE_HASH:
        raise ValueError('upstream visualize.py differs from the pinned source')
    doc = load_layout(args.layout.read_text(), args.source_dir, {'kind': 'visualization_input'})
    layout_class = _official_layout_class(args.source_dir)[0]
    # The upstream script imports this package; supply only its already-audited
    # geometry interface. Its original pcd modules remain on the external path.
    package = types.ModuleType('spatiallm')
    package.__path__ = [str(args.source_dir / 'spatiallm')]
    package.Layout = layout_class
    previous = sys.modules.get('spatiallm')
    old_argv = sys.argv
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        sys.modules['spatiallm'] = package
        sys.argv = [str(script), '--point_cloud', str(args.point_cloud), '--layout', str(args.layout),
                    '--save', str(args.output), '--max_points', str(args.max_points)]
        runpy.run_path(str(script), run_name='__main__')
    finally:
        sys.argv = old_argv
        if previous is None:
            sys.modules.pop('spatiallm', None)
        else:
            sys.modules['spatiallm'] = previous
    if not args.output.is_file() or args.output.stat().st_size == 0:
        raise RuntimeError('upstream viewer did not write a nonempty recording')
    manifest = {'official_visualize_sha256': _VISUALIZE_HASH, 'layout_source': doc['source'],
                'point_cloud_sha256': hashlib.sha256(args.point_cloud.read_bytes()).hexdigest(),
                'recording_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                'max_points': args.max_points,
                'limits': 'Native upstream Rerun visualization; not MuJoCo collision or model inference acceptance.'}
    args.output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'recording': str(args.output), 'bytes': args.output.stat().st_size}, indent=2))


if __name__ == '__main__':
    main()
