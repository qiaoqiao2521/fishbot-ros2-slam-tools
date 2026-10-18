#!/usr/bin/python3
"""Download pinned ROS binaries and extract without apt install or root privileges."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def validate_pins(packages):
    """Require explicit identities and hashes for an optional package set."""
    if not isinstance(packages, list) or not packages:
        raise ValueError('Custom packages file must contain a nonempty package list')
    names, files = set(), set()
    for pin in packages:
        if (not isinstance(pin, dict) or not isinstance(pin.get('package'), str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9+.-]+', pin['package'])
                or not isinstance(pin.get('version'), str) or not pin['version']
                or any(c.isspace() for c in pin['version'])
                or not isinstance(pin.get('file'), str) or Path(pin['file']).name != pin['file']
                or not pin['file'].endswith('.deb')
                or not isinstance(pin.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', pin['sha256'])):
            raise ValueError('Custom package requires package, version, basename file and SHA256')
        if pin['package'] in names or pin['file'] in files:
            raise ValueError('Duplicate custom package or deb filename')
        names.add(pin['package']); files.add(pin['file'])


def verified_debs(debs, packages):
    """Validate every selected archive before the caller extracts any archive."""
    selected = []
    for pin in packages:
        deb = debs / pin['file']
        if not deb.is_file() or deb.is_symlink():
            raise ValueError('Missing selected package archive: ' + pin['file'])
        if hashlib.sha256(deb.read_bytes()).hexdigest() != pin['sha256']:
            raise ValueError('Selected package SHA256 mismatch: ' + pin['file'])
        for field in ('package', 'version'):
            actual = subprocess.run(['dpkg-deb', '-f', str(deb), field.title()],
                                    check=True, capture_output=True, text=True).stdout.strip()
            if actual != pin[field]:
                raise ValueError('Selected package ' + field + ' mismatch: ' + pin['file'])
        selected.append(deb)
    return selected


def main():
    project = Path(__file__).resolve().parent.parent
    ws = project / 'workspaces/fishbot_mujoco_ws'
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, default=ws / '.runtime')
    parser.add_argument('--packages-file', type=Path, help='Select a package/version/file/SHA256 pinned JSON list')
    parser.add_argument('--no-link', action='store_true', help='Do not create the workspace .runtime symlink')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    debs = runtime / 'debs'
    debs.mkdir(exist_ok=True)
    lock = args.packages_file or ws / 'src/fishbot_mujoco/docs/runtime-packages.json'
    packages = json.loads(lock.read_text())
    if args.packages_file:
        validate_pins(packages)
    subprocess.run(['apt-get', 'download', *[f"{p['package']}={p['version']}" for p in packages]],
                   cwd=debs, check=True)
    manifest = []
    selected = verified_debs(debs, packages) if args.packages_file else sorted(debs.glob('*.deb'))
    for deb in selected:
        subprocess.run(['dpkg-deb', '-x', str(deb), str(runtime)], check=True)
        manifest.append({'file': deb.name, 'sha256': hashlib.sha256(deb.read_bytes()).hexdigest()})
    (runtime / 'download-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    link = ws / '.runtime'
    if not args.no_link and not link.exists() and runtime != link:
        link.symlink_to(runtime, target_is_directory=True)
    print(f'Runtime ready: {runtime}')
    print('Next: layer the custom prefix explicitly; no system packages were installed.'
          if args.packages_file else 'Next: tools/fishbot_mujoco.sh build')


if __name__ == '__main__':
    main()
