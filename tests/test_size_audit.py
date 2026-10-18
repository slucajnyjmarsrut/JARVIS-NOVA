import pathlib
import tempfile
import unittest
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from scripts.size_audit import category, summarize


class SizeAuditTests(unittest.TestCase):
    def test_file_classification(self):
        checks = {
            "_internal/assets/models/ollama/blobs/sha256-123": "Vision model weights",
            "_internal/assets/models/base.pt": "Whisper and Silero",
            "_internal/assets/models/v5_ru.pt": "Whisper and Silero",
            "_internal/assets/ollama/ollama.exe": "Ollama inference",
            "_internal/assets/bin/ffmpeg.exe": "FFmpeg video",
            "_internal/torch/include/ATen/Generator.h": "PyTorch runtime",
            "JarvisNova.exe": "Windows application",
        }
        for name, prefix in checks.items():
            with self.subTest(file=name):
                self.assertTrue(category(pathlib.Path(name)).startswith(prefix))

    def test_directory_summary_counts_all_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            sizes = {
                "JarvisNova.exe": 90,
                "_internal/torch/include/torch/example.h": 13,
                "_internal/assets/models/ollama/blobs/sha256-123": 700,
                "_internal/assets/models/base.pt": 120,
                "_internal/assets/bin/ffmpeg.exe": 50,
            }
            for name, size in sizes.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"Z" * size)
            info = summarize(root, top_n=2)
            self.assertEqual(info["total_bytes"], sum(sizes.values()))
            self.assertEqual(info["files"], len(sizes))
            self.assertEqual(info["largest_files"][0]["bytes"], 700)
            self.assertEqual(sum(c["bytes"] for c in info["categories"]), sum(sizes.values()))
            self.assertEqual(len(info["largest_files"]), 2)

    def test_missing_root_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                summarize(pathlib.Path(temp) / "absent")


if __name__ == "__main__":
    unittest.main()
