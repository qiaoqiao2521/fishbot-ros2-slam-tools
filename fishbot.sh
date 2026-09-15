#!/usr/bin/env bash
set -euo pipefail
ROOT="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
case "${1:-help}" in
  help|-h|--help)
    echo 'FishBot: ./fishbot.sh check | stack <command> | teleop <command> | save-map <name>'
    echo 'check is offline only. stack/teleop/save-map operate on the live ROS graph.'
    ;;
  check) exec /usr/bin/python3 "$ROOT/tools/check_layout.py" ;;
  stack) shift; exec bash "$ROOT/tools/fishbot_stack.sh" "$@" ;;
  teleop) shift; exec bash "$ROOT/tools/fishbot.sh" "$@" ;;
  save-map) shift; exec bash "$ROOT/tools/fishbot_save_map.sh" "$@" ;;
  *) echo "Unknown command: $1" >&2; exit 2 ;;
esac
