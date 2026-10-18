import pathlib, sys, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from main import Jarvis

class ViralUiWiringTest(unittest.TestCase):
    def test_ui_entry_point_exists(self):
        self.assertTrue(callable(Jarvis.open_viral_studio))
        self.assertTrue(callable(Jarvis.handle_text))

if __name__=='__main__':unittest.main()
