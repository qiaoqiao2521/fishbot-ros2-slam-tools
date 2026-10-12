#!/usr/bin/env bash
set -euo pipefail
ROOT="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
case "${1:-help}" in
  help|-h|--help)
    echo 'FishBot: ./fishbot.sh check | check-feedback | sim-suite [options] | stack <command> | teleop <command> | save-map <name>'
    echo 'check checks layout; check-feedback runs offline behavioral regressions.'
    echo 'stack/teleop/save-map operate on the live ROS graph.'
    ;;
  check) exec /usr/bin/python3 "$ROOT/tools/check_layout.py" ;;
  check-feedback) shift; exec /usr/bin/python3 -B "$ROOT/tools/fishbot_feedback_check.py" "$@" ;;
  sim-suite) shift; exec bash "$ROOT/tools/fishbot_simulation_suite.sh" "$@" ;;
  stack) shift; exec bash "$ROOT/tools/fishbot_stack.sh" "$@" ;;
  teleop) shift; exec bash "$ROOT/tools/fishbot.sh" "$@" ;;
  save-map) shift; exec bash "$ROOT/tools/fishbot_save_map.sh" "$@" ;;
  *) echo "Unknown command: $1" >&2; exit 2 ;;
esac
