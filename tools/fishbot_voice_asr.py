#!/usr/bin/env python3
"""Local Vosk audio adapter. No network, recording, task execution, or ISA promises."""
from __future__ import annotations

import array
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import wave

SAMPLE_RATE = 16000
MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 15.0
MODEL_NAME = "vosk-model-small-cn-0.22"
DEFAULT_MODEL = Path.home() / ".cache/fishbot/edge-voice-20261015" / MODEL_NAME


class VoiceAudioError(ValueError):
    def __init__(self, reason, message, status=422):
        super().__init__(message)
        self.reason, self.status = reason, status


def decode_audio(data: bytes, mime_type="audio/wav") -> bytes:
    """Bound containers before decoding. FFmpeg sees only stdin; no network/file protocols."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_AUDIO_BYTES:
        raise VoiceAudioError("audio_size", "音频为空或超过4MiB", 413)
    mime = mime_type.split(";")[0].strip().lower()
    wav = data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    webm = data[:4] == b"\x1aE\xdf\xa3"
    ogg = data[:4] == b"OggS"
    if mime not in {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg"}:
        raise VoiceAudioError("audio_type", "请上传WAV、WebM或Ogg音频", 415)
    if not ((wav and mime in {"audio/wav", "audio/x-wav", "audio/wave"})
            or (webm and mime == "audio/webm") or (ogg and mime == "audio/ogg")):
        raise VoiceAudioError("audio_container", "音频内容与格式不匹配")
    if wav:
        try:
            with wave.open(io.BytesIO(data), "rb") as stream:
                seconds = stream.getnframes() / stream.getframerate()
                if not .15 <= seconds <= MAX_SECONDS:
                    raise VoiceAudioError("audio_duration", "每段音频须为0.15至15秒")
                if stream.getframerate() == SAMPLE_RATE and stream.getnchannels() == 1 and stream.getsampwidth() == 2:
                    pcm = stream.readframes(stream.getnframes())
                    if len(pcm) != stream.getnframes() * 2:
                        raise VoiceAudioError("audio_truncated", "音频数据不完整")
                    return pcm
        except (wave.Error, EOFError, ZeroDivisionError) as error:
            raise VoiceAudioError("audio_invalid", "WAV音频无法读取") from error
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise VoiceAudioError("ffmpeg_unavailable", "缺少FFmpeg，请上传16kHz单声道16位PCM WAV", 503)
    try:
        result = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-protocol_whitelist", "pipe", "-i", "pipe:0", "-vn", "-t", str(MAX_SECONDS + .1),
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False)
    except subprocess.TimeoutExpired as error:
        raise VoiceAudioError("audio_decode_timeout", "音频转换超时，请缩短录音") from error
    if result.returncode or not result.stdout:
        raise VoiceAudioError("audio_decode_failed", "音频转换失败，请重新录音或上传WAV")
    pcm = result.stdout
    if not .15 <= len(pcm) / (SAMPLE_RATE * 2) <= MAX_SECONDS or len(pcm) % 2:
        raise VoiceAudioError("audio_duration", "每段音频须为0.15至15秒")
    return pcm


def audio_energy(pcm):
    samples = array.array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return math.sqrt(sum(x * x for x in samples) / max(1, len(samples))) / 32768.0


class VoskTranscriber:
    """One cached CPU model, one recognizer per request. Task cancel never waits on this lock."""
    def __init__(self, model_path=None):
        self.model_path = Path(model_path or os.environ.get("FISHBOT_VOSK_MODEL", str(DEFAULT_MODEL))).expanduser()
        self.model_name = self.model_path.name
        self._model = None
        self._failure = None
        self._lock = threading.Lock()

    def availability(self):
        files = ("am/final.mdl", "conf/model.conf", "graph/HCLr.fst")
        available = importlib.util.find_spec("vosk") is not None and all((self.model_path / f).is_file() for f in files)
        reason = self._failure or ("ready" if available else "vosk_or_model_missing")
        return {"available": bool(available and not self._failure), "backend": "vosk", "model": self.model_name,
            "language": "zh-CN", "mode": "offline_cpu", "reason": reason,
            "max_audio_bytes": MAX_AUDIO_BYTES, "max_duration_s": MAX_SECONDS,
            "audio_formats": ["audio/wav", "audio/webm", "audio/ogg"],
            "hardware_acceleration": "not_measured", "recording_stored": False}

    def transcribe(self, data, mime_type="audio/wav"):
        started = time.perf_counter()
        pcm = decode_audio(data, mime_type)
        energy = audio_energy(pcm)
        if energy < .004:
            raise VoiceAudioError("silence", "没有检测到足够清晰的声音，请重新录音")
        if not self.availability()["available"]:
            raise VoiceAudioError("asr_unavailable", "离线识别引擎或中文模型尚未配置", 503)
        if not self._lock.acquire(blocking=False):
            raise VoiceAudioError("asr_busy", "正在处理另一段录音，请稍后再试", 409)
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            if self._model is None:
                SetLogLevel(-1)
                try:
                    self._model = Model(str(self.model_path))
                except Exception as error:
                    self._failure = "model_load_failed"
                    raise VoiceAudioError("model_load_failed", "离线模型加载失败，请检查安装", 503) from error
            recognizer = KaldiRecognizer(self._model, SAMPLE_RATE)
            recognizer.SetWords(True)
            segments = []
            for offset in range(0, len(pcm), 4000):
                if recognizer.AcceptWaveform(pcm[offset:offset + 4000]):
                    segments.append(json.loads(recognizer.Result()))
            segments.append(json.loads(recognizer.FinalResult()))
            text = " ".join(part.get("text", "") for part in segments).strip()
            # Vosk Chinese token separators are not spoken pauses.
            text = "".join(text.split())
            words = [word for part in segments for word in part.get("result", [])]
            if not text:
                raise VoiceAudioError("no_speech", "没有识别出文字，请重录或输入文字")
            confidence = sum(float(w.get("conf", 0.)) for w in words) / len(words) if words else None
            return {"text": text, "model": self.model_name, "language": "zh-CN", "backend": "vosk",
                "duration_s": len(pcm) / (SAMPLE_RATE * 2), "inference_ms": (time.perf_counter() - started) * 1000,
                "word_confidence_mean": confidence, "confidence_is_success_probability": False,
                "rms": energy, "recording_stored": False}
        finally:
            self._lock.release()


def create_transcriber(model_path=None):
    return VoskTranscriber(model_path)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", nargs="?", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--mime-type", default="audio/wav")
    args = parser.parse_args()
    engine = create_transcriber(args.model)
    try:
        print(json.dumps(engine.transcribe(args.audio.read_bytes(), args.mime_type) if args.audio
                         else engine.availability(), ensure_ascii=False, indent=2))
    except VoiceAudioError as error:
        print(json.dumps({"error": str(error), "reason": error.reason}, ensure_ascii=False))
        raise SystemExit(2)
