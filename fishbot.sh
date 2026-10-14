#!/usr/bin/env bash
set -euo pipefail
ROOT="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
case "${1:-help}" in
  help|-h|--help)
    echo 'FishBot: ./fishbot.sh check | check-feedback | sim-suite [options] | sim-campaign [options] | stack <command> | teleop <command> | save-map <name>'
    echo 'check checks layout; check-feedback runs offline behavioral regressions.'
    echo 'Simulation extensions: localization-recovery [options] | object-inspection <new-output-directory> | arena <command>'
    echo 'stack/teleop/save-map operate on the live ROS graph.'
    ;;
  check) exec /usr/bin/python3 "$ROOT/tools/check_layout.py" ;;
  check-feedback) shift; exec /usr/bin/python3 -B "$ROOT/tools/fishbot_feedback_check.py" "$@" ;;
  sim-suite) shift; exec bash "$ROOT/tools/fishbot_simulation_suite.sh" "$@" ;;
  sim-campaign) shift; exec bash "$ROOT/tools/fishbot_simulation_campaign.sh" "$@" ;;
  localization-recovery) shift; exec bash "$ROOT/tools/fishbot_localization_recovery.sh" "$@" ;;
  object-inspection) shift; exec bash "$ROOT/tools/fishbot_object_inspection.sh" "$@" ;;
  arena) shift; exec /usr/bin/python3 -B "$ROOT/tools/fishbot_arena.py" "$@" ;;
  stack) shift; exec bash "$ROOT/tools/fishbot_stack.sh" "$@" ;;
  teleop) shift; exec bash "$ROOT/tools/fishbot.sh" "$@" ;;
  save-map) shift; exec bash "$ROOT/tools/fishbot_save_map.sh" "$@" ;;
  *) echo "Unknown command: $1" >&2; exit 2 ;;
esac
