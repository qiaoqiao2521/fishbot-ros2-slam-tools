"""Audio boundary tests; real Vosk decoding is a separate recorded acceptance."""
import array
import io
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from tools.fishbot_voice_asr import (decode_audio, audio_energy, create_transcriber,
    VoiceAudioError, MAX_AUDIO_BYTES)


def wav_data(seconds=.5, rate=16000, amplitude=6000):
    pcm = array.array('h', (int(amplitude*math.sin(2*math.pi*330*i/rate)) for i in range(int(seconds*rate))))
    out = io.BytesIO()
    with wave.open(out, 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(pcm.tobytes())
    return out.getvalue()


class AudioBoundaries(unittest.TestCase):
    def test_pcm_wav_uses_original_samples(self):
        raw = wav_data()
        pcm = decode_audio(raw)
        self.assertEqual(len(pcm), 16000)
        self.assertGreater(audio_energy(pcm), .05)

    def test_invalid_type_container_empty_and_size_fail(self):
        for data, mime, reason in [(b'', 'audio/wav', 'audio_size'),
                (b'x'*(MAX_AUDIO_BYTES+1), 'audio/wav', 'audio_size'),
                (b'RIFFgarbage', 'audio/wav', 'audio_container'),
                (wav_data(), 'audio/webm', 'audio_container'),
                (wav_data(), 'text/plain', 'audio_type')]:
            with self.subTest(reason=reason), self.assertRaises(VoiceAudioError) as caught:
                decode_audio(data, mime)
            self.assertEqual(caught.exception.reason, reason)

    def test_long_short_and_truncated_wav_rejected(self):
        for data in [wav_data(.1), wav_data(15.1), wav_data()[:-40]]:
            with self.assertRaises(VoiceAudioError):
                decode_audio(data)

    def test_silence_never_enters_model(self):
        engine = create_transcriber('/missing-model')
        with self.assertRaises(VoiceAudioError) as caught:
            engine.transcribe(wav_data(amplitude=0))
        self.assertEqual(caught.exception.reason, 'silence')
        self.assertIsNone(engine._model)

    def test_missing_model_reports_unavailable_not_fake_text(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_transcriber(directory)
            self.assertFalse(engine.availability()['available'])
            with self.assertRaises(VoiceAudioError) as caught:
                engine.transcribe(wav_data())
            self.assertEqual(caught.exception.reason, 'asr_unavailable')

    def test_non_pcm_wav_requires_real_decoder(self):
        with patch('tools.fishbot_voice_asr.shutil.which', return_value=None):
            with self.assertRaises(VoiceAudioError) as caught:
                decode_audio(wav_data(rate=22050))
        self.assertEqual(caught.exception.reason, 'ffmpeg_unavailable')

    def test_busy_decoder_cannot_block_task_control(self):
        engine = create_transcriber()
        with patch.object(engine, 'availability', return_value={'available': True}):
            engine._lock.acquire()
            try:
                with self.assertRaises(VoiceAudioError) as caught:
                    engine.transcribe(wav_data())
                self.assertEqual(caught.exception.reason, 'asr_busy')
            finally:
                engine._lock.release()


if __name__ == '__main__':
    unittest.main()
