#!/usr/bin/env bash
# Build only the pinned Nav2 lifecycle manager, outside the checkout.
set -eo pipefail
umask 077

task_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_patch="$task_project/tools/patches/nav2-1.3.13-state-query.patch"
task_commit=f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501
task_archive_sha=dcc59eef3c0be52194707b827917212b8d6eeca8003e09b92f21343a48f9bdcb
task_original_sha=7d56021ac5c47315eda2a5a1003ecbcbb63355364696835d4300084de8b00f81
task_cache="${FISHBOT_NAV2_STATE_QUERY_OVERLAY_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/fishbot/nav2-state-query-overlay}"
task_patch_sha="$(sha256sum "$task_patch" | cut -d ' ' -f 1)"
task_workspace="$task_cache/$task_commit-${task_patch_sha:0:12}"
task_archive="$task_cache/downloads/navigation2-$task_commit.tar.gz"
task_source="$task_workspace/src/nav2_lifecycle_manager/src/lifecycle_manager.cpp"
task_prefix="$task_workspace/install"
task_receipt="$task_workspace/receipt.json"

prepare_source() {
    mkdir -p "$task_cache/downloads" "$task_workspace"
    if [[ ! -f "$task_archive" ]]; then
        curl --fail --silent --show-error --location --retry 2 --max-time 120 \
            "https://codeload.github.com/ros-navigation/navigation2/tar.gz/$task_commit" \
            -o "$task_archive.tmp"
        printf '%s  %s\n' "$task_archive_sha" "$task_archive.tmp" | sha256sum --check --status
        mv -- "$task_archive.tmp" "$task_archive"
    fi
    printf '%s  %s\n' "$task_archive_sha" "$task_archive" | sha256sum --check --status
    if [[ ! -f "$task_source" ]]; then
        mkdir -p "$task_workspace/src"
        tar -xzf "$task_archive" -C "$task_workspace/src" --strip-components=1 \
            "navigation2-$task_commit/nav2_lifecycle_manager"
        tar -xzf "$task_archive" -C "$task_workspace" --strip-components=1 \
            "navigation2-$task_commit/LICENSE"
        printf '%s  %s\n' "$task_original_sha" "$task_source" | sha256sum --check --status
        patch --batch --fuzz=0 -p1 -d "$task_workspace/src" < "$task_patch"
        sha256sum "$task_source" > "$task_workspace/patched-source.sha256"
    fi
    sha256sum --check --status "$task_workspace/patched-source.sha256"
    # Reject unrelated cached edits even if somebody regenerated the local checksum.
    local task_reverse
    task_reverse="$(mktemp "$task_workspace/original-check.XXXXXX")"
    if ! patch --batch --fuzz=0 --reverse --output "$task_reverse" "$task_source" \
        < "$task_patch" > /dev/null; then
        rm -- "$task_reverse"
        return 1
    fi
    local task_reverse_ok=0
    printf '%s  %s\n' "$task_original_sha" "$task_reverse" | sha256sum --check --status || task_reverse_ok=1
    rm -- "$task_reverse"
    return "$task_reverse_ok"
}

check_receipt() {
    /usr/bin/python3 - "$task_receipt" "$task_commit" "$task_archive_sha" "$task_patch_sha" <<'PY'
import hashlib
import json
import pathlib
import sys

receipt_path = pathlib.Path(sys.argv[1])
try:
    receipt = json.loads(receipt_path.read_text())
    if [receipt['upstream_commit'], receipt['archive_sha256'], receipt['patch_sha256']] != sys.argv[2:]:
        raise ValueError('receipt does not match the requested source and patch')
    for item in receipt['files']:
        path = receipt_path.parent / item['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'changed overlay file: {item["path"]}')
    required = {'install/local_setup.bash',
                'install/lib/libnav2_lifecycle_manager_core.so',
                'install/lib/nav2_lifecycle_manager/lifecycle_manager',
                'src/nav2_lifecycle_manager/src/lifecycle_manager.cpp'}
    if not required <= {item['path'] for item in receipt['files']}:
        raise ValueError('missing required manager binary, library, setup or source')
    if not receipt['files'] or not receipt['behavior_test_passed']:
        raise ValueError('missing overlay files or behavior-test acceptance')
except (OSError, ValueError, KeyError) as error:
    print(f'Nav2 state-query overlay is not ready: {error}', file=sys.stderr)
    sys.exit(1)
PY
}

behavior_test() {
    FISHBOT_NAV2_PATCHED_SOURCE="$task_source" /usr/bin/python3 \
        "$task_project/tools/tests/test_nav2_state_query_patch.py" -v
}

build_overlay() {
    prepare_source
    # Reuse the project's installed dependencies. The script never installs packages.
    source "$task_project/tools/fishbot_mujoco_env.sh"
    export CMAKE_BUILD_PARALLEL_LEVEL=1
    export MAKEFLAGS=-j1
    colcon --log-base "$task_workspace/log" build \
        --base-paths "$task_workspace/src" --packages-select nav2_lifecycle_manager \
        --allow-overriding nav2_lifecycle_manager --executor sequential --merge-install \
        --build-base "$task_workspace/build" --install-base "$task_prefix" \
        --event-handlers console_direct+ \
        --cmake-args -DBUILD_TESTING=OFF -DPython3_EXECUTABLE=/usr/bin/python3 \
        -DCMAKE_BUILD_TYPE=RelWithDebInfo
    behavior_test
    /usr/bin/python3 - "$task_workspace" "$task_commit" "$task_archive_sha" "$task_patch_sha" <<'PY'
import hashlib
import json
import pathlib
import sys

workspace = pathlib.Path(sys.argv[1])
paths = sorted(p for p in (workspace / 'install').rglob('*') if p.is_file())
paths += [workspace / 'src/nav2_lifecycle_manager/src/lifecycle_manager.cpp', workspace / 'LICENSE']
receipt = {
    'schema_version': 1,
    'upstream_tag': '1.3.13',
    'upstream_commit': sys.argv[2],
    'archive_sha256': sys.argv[3],
    'patch_sha256': sys.argv[4],
    'package': 'nav2_lifecycle_manager',
    'behavior_test_passed': True,
    'ros_fault_injection_passed': None,
    'files': [{'path': str(p.relative_to(workspace)),
               'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
}
(workspace / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
PY
    check_receipt
    printf '%s\n' "$task_prefix"
}

case "${1:-build}" in
    build|prepare|test)
        mkdir -p "$task_workspace"
        exec 9>"$task_workspace/build.lock"
        flock -n 9 || { echo 'This overlay is already being built.' >&2; exit 1; }
        case "${1:-build}" in
            build) build_overlay ;;
            prepare) prepare_source; printf '%s\n' "$task_source" ;;
            test) prepare_source; behavior_test ;;
        esac
        ;;
    prefix) check_receipt; printf '%s\n' "$task_prefix" ;;
    check) check_receipt ;;
    *) echo 'Usage: fishbot_nav2_state_query_overlay.sh [build|prepare|test|check|prefix]' >&2; exit 2 ;;
esac
