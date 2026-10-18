"""Regression: Silero v5 package's .to() is an in-place method returning None."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from silero_engine import SileroConfig, SileroSynthesizer

class _SileroInPlaceStub:
    def __init__(self):
        self.to_device = None
    def to(self, device):
        self.to_device = device
        return None

class SileroLoadTests(unittest.TestCase):
    def test_initialize_retains_package_model_if_to_returns_none(self):
        with TemporaryDirectory() as tmp:
            pt = Path(tmp) / "v5_ru.pt"
            pt.write_bytes(b"silero-model-test-" * 80000)
            model = _SileroInPlaceStub()
            tts = SileroSynthesizer(SileroConfig(pt), loader=lambda _: model)
            tts.initialize()
            self.assertTrue(tts.ready)
            self.assertIs(tts._model, model)
            self.assertEqual(model.to_device, "cpu")

if __name__ == "__main__":
    unittest.main()
