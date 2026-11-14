# -*- coding: utf-8 -*-
"""Screenshot annotations stay local and cannot authorize self-modification."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from screenshot_review import (
    load_screenshot, annotate_jpeg, save_annotated,
    MAX_FILE_BYTES, MAX_JPEG_BYTES,
)


class ScreenshotReviewTests(unittest.TestCase):
    def test_annotation_keeps_original_and_marks_result_red(self):
        with tempfile.TemporaryDirectory() as root:
            original = Path(root) / "screen.png"
            Image.new("RGB", (250, 140), "white").save(original)
            before = original.read_bytes()
            image = load_screenshot(original)
            payload = annotate_jpeg(image, [[(30, 35), (180, 35), (180, 100)]])
            self.assertTrue(payload.startswith(bytes.fromhex("ffd8ff")))
            self.assertTrue(payload.endswith(bytes.fromhex("ffd9")))
            self.assertLessEqual(len(payload), MAX_JPEG_BYTES)
            self.assertEqual(original.read_bytes(), before)
            result = Image.open(BytesIO(payload))
            red = result.getpixel((110, 35))
            self.assertGreater(red[0], 140)
            self.assertLess(red[1], 140)
            copied = save_annotated(payload, Path(root) / "reviews")
            self.assertNotEqual(copied, original)
            self.assertEqual(copied.read_bytes(), payload)
            self.assertEqual(original.read_bytes(), before)

    def test_refuses_unknown_and_overlarge_screenshots(self):
        with tempfile.TemporaryDirectory() as root:
            bad = Path(root) / "not_image.png"
            bad.write_bytes(b"not an image")
            with self.assertRaises(ValueError):
                load_screenshot(bad)
            bad.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
            with self.assertRaises(ValueError):
                load_screenshot(bad)
            with self.assertRaises(ValueError):
                save_annotated(b"bad", Path(root))

    def test_annotations_reject_unbounded_or_invalid_coordinates(self):
        image = Image.new("RGB", (180, 120), "white")
        cases = (
            [[(float("nan"), 5)]],
            [[(float("inf"), 5)]],
            [[(-1, 5)]],
            [[(180, 5)]],
            [[("7", 8)]],
            [["bad"]],
            "not strokes",
            [[]] * 1025,
            [[(1, 1)] * 50_001],
        )
        for marks in cases:
            with self.subTest(case=str(marks)[:45]), self.assertRaises(ValueError):
                annotate_jpeg(image, marks)

    def test_copied_jpeg_requires_real_jpeg_markers(self):
        with tempfile.TemporaryDirectory() as root:
            fake = b"not a JPEG" * 15
            with self.assertRaises(ValueError):
                save_annotated(fake, Path(root) / "reports")
            self.assertFalse((Path(root) / "reports").exists())

    def test_writes_only_after_explicit_save_or_send(self):
        import inspect
        from screenshot_review import ScreenshotReview
        source = inspect.getsource(ScreenshotReview)
        self.assertIn("def save_copy(", source)
        self.assertIn("def send(", source)
        self.assertIn("def choose(", source)
        self.assertIn("parent.screenshot_ready()", source)
        self.assertIn("parent.submit_screenshot(", source)
        self.assertNotIn("requests.post", source)
        self.assertNotIn("github", source.casefold())

    def test_submit_rejects_nonlocal_or_missing_model_without_mutation(self):
        from text_only_main import TextJarvis
        from types import SimpleNamespace
        for engine, ready in (("freellm", True), ("bundled", False)):
            app = SimpleNamespace(
                engine=engine, _closing=False, _local_model_ready=ready)
            self.assertFalse(TextJarvis.screenshot_ready(app))
        app = Mock()
        app.screenshot_ready.return_value = True
        app.executing = True
        self.assertFalse(TextJarvis.submit_screenshot(app, "Исправь", b"x"*50))
        app.executing = False
        self.assertFalse(TextJarvis.submit_screenshot(app, "Исправь", b"x"))
        app.log.assert_not_called()

    def test_screenshot_submission_is_read_only_and_routes_through_local_vision(self):
        import inspect
        from text_only_main import TextJarvis
        source = inspect.getsource(TextJarvis.submit_screenshot)
        self.assertIn("LocalOllamaVision", source)
        self.assertIn("runtime.start()", source)
        self.assertIn('self.q.put(("chat_result"', source)
        self.assertNotIn("git", source.lower())
        self.assertNotIn("subprocess", source.lower())


if __name__ == "__main__":
    unittest.main()
