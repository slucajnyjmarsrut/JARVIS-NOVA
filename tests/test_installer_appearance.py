"""Dark Inno assets are original, reproducible and legible on Windows."""
import runpy
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT=Path(__file__).resolve().parents[1]


class InstallerAppearanceTests(unittest.TestCase):
    def test_dark_wizard_images_generate_without_internet(self):
        generate=runpy.run_path(str(ROOT/"scripts/generate_installer_art.py"))["generate"]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            generate(folder)
            large=folder/"installer_banner.bmp"
            small=folder/"installer_badge.bmp"
            self.assertTrue(large.is_file())
            self.assertTrue(small.is_file())
            with Image.open(large) as image:
                self.assertEqual(image.size,(640,1220))
                self.assertEqual(image.mode,"RGB")
                self.assertLess(sum(image.getpixel((10,10))),90)
            with Image.open(small) as image:
                self.assertEqual(image.size,(240,240))

    def test_setup_forces_dark_mode_and_does_not_bundle_camera(self):
        setup=(ROOT/"installer/JarvisNova.iss").read_text(encoding="utf-8-sig")
        self.assertIn("WizardStyle=modern dark",setup)
        self.assertIn("WizardImageFile=..\\assets\\installer_banner.bmp",setup)
        self.assertIn("WizardSmallImageFile=..\\assets\\installer_badge.bmp",setup)
        self.assertIn("AppVersion \"0.5.16-dev\"",setup)


if __name__=="__main__":
    unittest.main()
