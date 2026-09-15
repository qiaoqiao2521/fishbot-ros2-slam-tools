#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${SCRIPT_DIR}/fishbot.sh"

output="$("${TARGET}" help)"

assert_contains() {
  local needle="$1"
  if [[ "${output}" != *"${needle}"* ]]; then
    echo "missing help entry: ${needle}" >&2
    exit 1
  fi
}

assert_contains "tools/fishbot.sh status"
assert_contains "tools/fishbot.sh validate"
assert_contains "tools/fishbot.sh drive"
assert_contains "tools/fishbot.sh estop"
assert_contains "tools/fishbot.sh arrows"

echo "help output contains expected commands"
