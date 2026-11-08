# -*- coding: utf-8 -*-
"""Release MUST contain no voice files, libraries or speech model checks."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class TextOnlyBundleContract(unittest.TestCase):
    def test_voice_libraries_excluded_from_frozen_exe(self):
        spec=(ROOT/"jarvis_nova.spec").read_text(encoding="utf-8")
        for name in ("'torch'","'whisper'","'vosk'","'sounddevice'",
                     "'pyttsx3'","'speaker'","'voice_engine'",
                     "'trimodal_service'","'silero_engine'"):
            self.assertIn(name,spec)
        self.assertIn("excludes=legacy_voice",spec)
        self.assertIn("assets/models/ollama",spec)
        self.assertNotIn("collect_all('torch')",spec)
        self.assertNotIn("collect_all('whisper')",spec)
    def test_runtime_requirements_have_no_voice(self):
        deps=(ROOT/"requirements-windows.txt").read_text(encoding="utf-8").lower()
        for token in ("vosk", "whisper", "sounddevice", "pyttsx3",
                      "torch","scipy","silero"):
            self.assertNotIn(token,deps)
    def test_release_ci_does_not_download_speech_checkpoints(self):
        workflow=(ROOT/".github/workflows/windows-offline.yml").read_text(encoding="utf-8")
        self.assertNotIn("python build_models.py",workflow)
        self.assertNotIn("python verify_models.py",workflow)
        self.assertNotIn("python offline_e2e_test.py",workflow)
        self.assertNotIn("pip install torch",workflow)
        self.assertIn("python scripts/verify_text_vision_e2e.py",workflow)
        self.assertIn("python scripts/run_text_only_tests.py",workflow)
    def test_bootstrap_no_voice_on_frozen_path(self):
        entry=(ROOT/"bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn("from speaker import assets",entry)
        self.assertNotIn("from offline_e2e_test",entry)
        self.assertIn("from scripts.verify_text_vision_e2e",entry)
        controller=(ROOT/"text_only_main.py").read_text(encoding="utf-8")
        self.assertIn("self.voice_enabled = False",controller)
        self.assertIn("self.voice = NoAudio()",controller)
    def test_text_assets_fail_if_old_voice_checkpoints_present(self):
        from scripts.verify_installer_payload import verify
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,"x64 app"):
                verify(Path(d))
    def test_video_engine_and_qwen_stay_in_release(self):
        spec=(ROOT/"jarvis_nova.spec").read_text(encoding="utf-8")
        for term in ("qwen3-vl", "ffmpeg.exe","ffprobe.exe","code_gui",
                     "filmcraft_bridge","roblox_world_builder"):
            self.assertIn(term,spec)

if __name__=="__main__":
    unittest.main()
