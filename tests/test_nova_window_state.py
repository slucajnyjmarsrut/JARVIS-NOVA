"""Private window layout persistence: bounds, corruption, and atomic writes."""
import json
import tempfile
import unittest
from pathlib import Path

from nova_window_state import load_layout, save_layout, safe_window_geometry


class LayoutStorageTests(unittest.TestCase):
    def test_missing_corrupt_or_oversized_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"ui-layout.json"
            self.assertEqual(load_layout(path),{})
            path.write_text("{ broken",encoding="utf-8")
            self.assertEqual(load_layout(path),{})
            path.write_text("a"*3000,encoding="utf-8")
            self.assertEqual(load_layout(path),{})

    def test_only_geometry_is_persisted_no_transcripts_or_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"subdir"/"ui-layout.json"
            self.assertTrue(save_layout("468x810+1390+80","334x242+1560+100",path))
            self.assertEqual(load_layout(path),{
                "main":"468x810+1390+80","mini":"334x242+1560+100"})
            raw=path.read_text(encoding="utf-8")
            self.assertNotIn("microphone",raw)
            self.assertNotIn("permission",raw)
            self.assertNotIn("message",raw)

    def test_invalid_geometry_does_not_survive_write(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"ui-layout.json"
            self.assertTrue(save_layout("9600x9999-500-400","evil",path))
            self.assertEqual(load_layout(path),{})

    def test_clamp_offscreen_positions_and_respect_fixed_mini_size(self):
        self.assertEqual(safe_window_geometry(
            "468x810+50000+80000","468x810+1434+135",1920,1080),
            "468x810+1452+270")
        self.assertEqual(safe_window_geometry(
            "900x1100+1400+950","334x242+1566+279",1920,1080,fixed=True),
            "334x242+1400+838")
        self.assertEqual(safe_window_geometry(
            "junk","468x810+1434+135",1920,1080),
            "468x810+1434+135")

    def test_one_hundred_thousand_screen_geometry_cases(self):
        # Deterministic property stress, not 100k distinct human voice trials.
        import re
        pattern=re.compile(r"^(\\d+)x(\\d+)\\+(\\d+)\\+(\\d+)$")
        for case in range(100_000):
            width=1+(case*977)%3840
            height=1+(case*613)%2160
            value=(f"{320+case%580}x{380+case%721}+"
                   f"{(case*73)%12000}+{(case*337)%12000}")
            result=safe_window_geometry(value,"334x242+0+0",
                                         width,height,fixed=bool(case%2))
            match=pattern.fullmatch(result)
            self.assertIsNotNone(match)
            w,h,x,y=(int(part) for part in match.groups())
            self.assertGreaterEqual(x,0)
            self.assertGreaterEqual(y,0)
            self.assertLessEqual(x+w,width)
            self.assertLessEqual(y+h,height)

    def test_tiny_display_cannot_leave_unreachable_window(self):
        self.assertEqual(safe_window_geometry(
            "468x810+400+500","468x810+0+0",300,200),
            "300x200+0+0")


if __name__ == "__main__":
    unittest.main()
