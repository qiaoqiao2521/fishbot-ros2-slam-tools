#!/usr/bin/env bash
set -euo pipefail
_voice_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
_voice_runtime="${FISHBOT_VOICE_RUNTIME:-${XDG_CACHE_HOME:-$HOME/.cache}/fishbot/edge-voice-20261015}"
_voice_action="${1:-help}"
shift || true
case "$_voice_action" in
  install)
    python3 -m venv "$_voice_runtime/venv"
    "$_voice_runtime/venv/bin/python" -m pip install -r "$_voice_root/tools/voice-requirements.txt"
    "$_voice_runtime/venv/bin/python" - "$_voice_runtime" <<'PY'
import hashlib,sys,urllib.request,zipfile
from pathlib import Path
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
name='vosk-model-small-cn-0.22';archive=root/(name+'.zip')
expected='3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba'
if not archive.exists():
    temporary=root/(name+'.download')
    with urllib.request.urlopen('https://alphacephei.com/vosk/models/'+name+'.zip',timeout=30) as response, temporary.open('wb') as output:
        total=0
        while part:=response.read(1024*1024):
            total+=len(part)
            if total>50*1024*1024:raise SystemExit('Model download exceeded expected size')
            output.write(part)
    if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:
        raise SystemExit('Model checksum mismatch; original download retained')
    temporary.replace(archive)
if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise SystemExit('Cached model checksum mismatch')
if not (root/name/'am/final.mdl').is_file():
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target=(root/member.filename).resolve()
            if root not in target.parents or member.file_size>150_000_000:raise SystemExit('Unsafe model archive')
        package.extractall(root)
print('Installed pinned Vosk Chinese model; no audio or robot task executed.')
PY
    ;;
  serve|asr)
    if [[ ! -x "$_voice_runtime/venv/bin/python" ]]; then
      echo 'Missing voice runtime. Run ./fishbot.sh voice install first.' >&2; exit 2
    fi
    export FISHBOT_VOSK_MODEL="${FISHBOT_VOSK_MODEL:-$_voice_runtime/vosk-model-small-cn-0.22}"
    if [[ "$_voice_action" == serve ]]; then
      exec "$_voice_runtime/venv/bin/python" -B "$_voice_root/tools/fishbot_voice_bridge.py" "$@"
    fi
    exec "$_voice_runtime/venv/bin/python" -B "$_voice_root/tools/fishbot_voice_asr.py" "$@"
    ;;
  parse) exec python3 -B "$_voice_root/tools/fishbot_edge_voice_node.py" --phrase "${1:?Provide one phrase}" ;;
  sim)
    export FISHBOT_MUJOCO_DOMAIN_ID="${FISHBOT_VOICE_DOMAIN:-121}"
    exec "$_voice_root/tools/fishbot_mujoco.sh" headless bridge:=true bridge_port:=9071 web_port:=5180 "$@"
    ;;
  help|-h|--help)
    echo 'Usage: ./fishbot.sh voice {install|serve [options]|asr [audio.wav]|parse "text"|sim [ROS launch arguments]}'
    echo 'install downloads the pinned CPU recognizer and model. serve starts loopback voice API 9094; it starts no ROS world.'
    echo 'sim starts isolated domain 121 with mission API 9071; no physical robot. Recording/recognition never executes tasks automatically.'
    ;;
  *) echo "Unknown voice command: $_voice_action" >&2; exit 2 ;;
esac
