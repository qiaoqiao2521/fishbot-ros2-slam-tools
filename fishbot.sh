#!/usr/bin/env bash
set -euo pipefail
ROOT="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
case "${1:-help}" in
  help|-h|--help)
    echo 'FishBot: ./fishbot.sh check | check-feedback | sim-suite [options] | sim-campaign [options] | stack-gate <command> | stack <command> | teleop <command> | save-map <name>'
    echo 'check checks layout; check-feedback runs offline behavioral regressions.'
    echo 'Simulation extensions: localization-recovery [options] | object-inspection <new-output-directory> | arena <command>'
    echo 'Cooperation: cooperation {prepare|run|oracle} [options]; prepare accepts --scene-profile JSON.'
    echo 'Scene validation: scene-validation --output DIRECTORY [--cases clear detour blocked]'
    echo 'Hardware lab: hardware-report --real REPORT --base REPORT --suction REPORT [--transition REPORT] --output DIRECTORY (read-only)'
    echo 'Pressure physics: suction --output DIRECTORY [--render]'
    echo 'Mecanum ROS base: mecanum {info|build|args|drive|minimal|mapping|navigation|rviz} [options]'
    echo 'Continuous whole-vehicle transition: wall-transition --output DIRECTORY [--render]'
    echo 'Voice tasks: voice {install|serve|asr|parse|sim}; speech previews never start a task automatically.'
    echo 'stack/teleop/save-map operate on the live ROS graph.'
    ;;
  check) exec /usr/bin/python3 "$ROOT/tools/check_layout.py" ;;
  check-feedback) shift; exec /usr/bin/python3 -B "$ROOT/tools/fishbot_feedback_check.py" "$@" ;;
  sim-suite) shift; exec bash "$ROOT/tools/fishbot_simulation_suite.sh" "$@" ;;
  sim-campaign) shift; exec bash "$ROOT/tools/fishbot_simulation_campaign.sh" "$@" ;;
  scene-validation) shift; exec bash "$ROOT/tools/fishbot_scene_validation.sh" "$@" ;;
  hardware-report) shift; exec /usr/bin/python3 "$ROOT/tools/fishbot_hardware_lab.py" "$@" ;;
  mecanum) shift; exec bash "$ROOT/tools/fishbot_mecanum.sh" "$@" ;;
  suction) shift; exec bash "$ROOT/tools/fishbot_suction.sh" "$@" ;;
  wall-transition) shift; exec bash "$ROOT/tools/fishbot_suction.sh" --ground-wall "$@" ;;
  localization-recovery) shift; exec bash "$ROOT/tools/fishbot_localization_recovery.sh" "$@" ;;
  object-inspection) shift; exec bash "$ROOT/tools/fishbot_object_inspection.sh" "$@" ;;
  stack-gate) shift; exec /usr/bin/python3 -B "$ROOT/tools/fishbot_stack_gate.py" "$@" ;;
  arena) shift; exec /usr/bin/python3 -B "$ROOT/tools/fishbot_arena.py" "$@" ;;
  cooperation) shift; exec bash "$ROOT/tools/fishbot_cooperation.sh" "$@" ;;
  voice) shift; exec bash "$ROOT/tools/fishbot_voice.sh" "$@" ;;
  stack) shift; exec bash "$ROOT/tools/fishbot_stack.sh" "$@" ;;
  teleop) shift; exec bash "$ROOT/tools/fishbot.sh" "$@" ;;
  save-map) shift; exec bash "$ROOT/tools/fishbot_save_map.sh" "$@" ;;
  *) echo "Unknown command: $1" >&2; exit 2 ;;
esac
