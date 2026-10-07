#!/usr/bin/python3
"""Download pinned ROS binaries and extract without apt install or root privileges."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    project = Path(__file__).resolve().parent.parent
    ws = project / 'workspaces/fishbot_mujoco_ws'
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, default=ws / '.runtime')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    debs = runtime / 'debs'
    debs.mkdir(exist_ok=True)
    lock = ws / 'src/fishbot_mujoco/docs/runtime-packages.json'
    packages = json.loads(lock.read_text())
    subprocess.run(['apt-get', 'download', *[f"{p['package']}={p['version']}" for p in packages]],
                   cwd=debs, check=True)
    manifest = []
    for deb in sorted(debs.glob('*.deb')):
        subprocess.run(['dpkg-deb', '-x', str(deb), str(runtime)], check=True)
        manifest.append({'file': deb.name, 'sha256': hashlib.sha256(deb.read_bytes()).hexdigest()})
    (runtime / 'download-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    link = ws / '.runtime'
    if not link.exists() and runtime != link:
        link.symlink_to(runtime, target_is_directory=True)
    print(f'Runtime ready: {runtime}')
    print('Next: tools/fishbot_mujoco.sh build')


if __name__ == '__main__':
    main()
