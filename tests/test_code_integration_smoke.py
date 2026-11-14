"""Smoke checks on packaged runtime imports that don't require a GUI display."""
import ast
import unittest
from pathlib import Path


class CodingIntegrationSmoke(unittest.TestCase):
    def test_modules_compile(self):
        location=Path(__file__).resolve()
        base=location.parent if (location.parent/'code_workspace.py').exists() else location.parents[1]
        for name in ('code_workspace.py','code_agent.py','code_autopilot.py',
                     'code_gui.py','coding_intent.py'):
            with self.subTest(name=name):
                ast.parse((base/name).read_text(encoding='utf-8'))

    def test_integration_registered(self):
        location=Path(__file__).resolve()
        base=location.parent if (location.parent/'code_workspace.py').exists() else location.parents[1]
        if not (base/'main.py').is_file():
            self.skipTest('Пакет расширения ещё не установлен в полное приложение')
        main=(base/'main.py').read_text(encoding='utf-8')
        self.assertIn('def open_code_assistant',main)
        self.assertIn('detect_coding_intent(text)',main)
        # The legacy audio-era menu was removed; verify the actual typed UI.
        text_ui=(base/'text_only_ui.py').read_text(encoding='utf-8')
        self.assertIn('app.open_code_assistant',text_ui)
        self.assertIn("'code_gui'",(base/'jarvis_nova.spec').read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
