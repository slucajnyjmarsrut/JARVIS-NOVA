# -*- coding: utf-8 -*-
"""The user-facing JARVIS NOVA has NO microphone, ASR, wake word or TTS.

Ordinary *video* audio (music, sound effects, imported original soundtracks)
remains because it is media data, not a speaking assistant.
"""
from pathlib import Path
import ast
import inspect
import unittest

ROOT = Path(__file__).resolve().parents[1]
REMOVED = (
    "microphone.py", "audio_io.py", "asr_quality.py",
    "speech_capture.py", "speech_output.py", "voice_engine.py",
    "whisper_engine.py", "whisper_mode.py", "silero_engine.py",
    "speaker.py", "trimodal_pipeline.py", "trimodal_service.py",
    "offline_e2e_test.py", "build_models.py", "verify_models.py",
    "jarvis_agent.spec", "installer/JarvisNova_v2.iss",
)
UI = ("main.py", "text_only_main.py", "nova_ui.py",
      "nova_overlay.py", "text_only_overlay.py", "viral_studio_ui.py")


class NoVoiceContractTests(unittest.TestCase):
    def test_all_legacy_spoken_features_deleted_from_repository(self):
        for path in REMOVED:
            with self.subTest(path=path):
                self.assertFalse((ROOT/path).exists(),path)

    def test_no_speech_hardware_imports_in_visible_runtime(self):
        forbidden = {
            "speaker", "microphone", "voice_engine", "audio_io",
            "speech_capture", "speech_output", "whisper_engine",
            "whisper_mode", "silero_engine", "trimodal_pipeline",
            "trimodal_service", "vosk", "sounddevice", "pyttsx3",
        }
        for name in UI:
            with self.subTest(name=name):
                tree=ast.parse((ROOT/name).read_text(encoding="utf-8"))
                imported=[]
                for node in ast.walk(tree):
                    if isinstance(node,ast.Import):
                        imported.extend(alias.name.split(".")[0]
                                        for alias in node.names)
                    if isinstance(node,ast.ImportFrom):
                        imported.append((node.module or "").split(".")[0])
                self.assertFalse(forbidden.intersection(imported),
                                 (name,imported))

    def test_no_inert_voice_devices_or_voice_buttons(self):
        root=(ROOT/"text_only_main.py").read_text(encoding="utf-8")
        overlay=(ROOT/"nova_overlay.py").read_text(encoding="utf-8")
        studio=(ROOT/"viral_studio_ui.py").read_text(encoding="utf-8")
        for marker in ("self.voice =", "self.speaker =",
                       "self.trimodal =", "NoAudio", "init_voice",
                       "toggle_voice", "mic_toggle_button"):
            self.assertNotIn(marker,root)
        for marker in ("mic_button", "voice_enabled", "app.toggle_voice"):
            self.assertNotIn(marker,overlay)
        for marker in ("self.speaker", "_speak(", "speaker=None"):
            self.assertNotIn(marker,studio)

    def test_video_soundtrack_and_aac_still_supported(self):
        self.assertTrue((ROOT/"audio_highlight_signal.py").is_file())
        self.assertTrue((ROOT/"video_audio_audit.py").is_file())
        video=(ROOT/"topic_video_engine.py").read_text(encoding="utf-8")
        self.assertIn('"aac"',video)
        self.assertIn("original synthesized instrumental tones",video)

    def test_actual_app_entrypoint_is_text_only(self):
        source=(ROOT/"bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("from text_only_main import TextJarvis",source)
        self.assertNotIn("from voice_engine import",source)
        self.assertNotIn("from speaker import",source)


if __name__=="__main__":
    unittest.main()
