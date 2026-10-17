#!/usr/bin/env bash
# Run the pinned upstream toolchain without changing the user's global Node setup.
set -euo pipefail

station_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export COREPACK_HOME="${WORKBENCH_COREPACK_HOME:-${XDG_CACHE_HOME:-${HOME}/.cache}/robot-workbench/corepack}"
mkdir -p "$COREPACK_HOME"
# Corepack's yarn.js must not inherit an unrelated ancestor's ESM package scope.
if [[ ! -f "$COREPACK_HOME/package.json" ]]; then
  printf '%s\n' '{"private":true,"type":"commonjs"}' > "$COREPACK_HOME/package.json"
fi

# Installing the nested upstream must not replace FishBot's Git hooks.
export HUSKY=0
export ELECTRON_SKIP_BINARY_DOWNLOAD=1
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
cd "$station_dir/workbench"
exec npx --yes corepack@0.34.0 yarn "$@"
