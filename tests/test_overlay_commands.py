"""Safe local voice HUD commands and RAM-only text preview."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from overlay_commands import overlay_intent, preview_line
from main import Jarvis


class OverlayCommandsTests(unittest.TestCase):
    def test_show_and_hide_utterances_are_exact(self):
        for phrase in (
            "Джарвис, покажи интерфейс!", "открой интерфейс",
            "верни главное окно", "покажи окно джарвиса"):
            with self.subTest(phrase=phrase):
                self.assertEqual(overlay_intent(phrase),"show")
        for phrase in (
            "покажи оверлей", "Джарвис, скрой интерфейс!",
            "спрячь интерфейс", "сверни окно джарвиса"):
            with self.subTest(phrase=phrase):
                self.assertEqual(overlay_intent(phrase),"hide")

    def test_mentions_and_unrelated_desktop_commands_do_not_trigger(self):
        for phrase in (
            "расскажи мне что такое оверлей", "открой блокнот",
            "покажи оверлей в моём приложении",
            "отключи Windows", "открой экран", "закрой джарвис"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(overlay_intent(phrase))

    def test_live_handle_text_uses_only_window_visibility_methods(self):
        app=SimpleNamespace(_closing=False,log=Mock(),show_main=Mock(),
            hide_main=Mock(),reply=Mock(),
            modes=SimpleNamespace(parse=Mock(side_effect=AssertionError("Should be handled early"))))
        Jarvis.handle_text(app,"джарвис открой интерфейс")
        app.show_main.assert_called_once()
        app.hide_main.assert_not_called()
        app.reply.assert_called_once()
        Jarvis.handle_text(app,"покажи оверлей")
        app.hide_main.assert_called_once()

    def test_preview_is_bounded_one_line_and_nonprintable_stripped(self):
        s=preview_line("Вы","  тайная\nмногострочная\tфраза  "+("x"*250))
        self.assertEqual(len(s),len("Вы: ")+72)
        self.assertNotIn("\n",s)
        self.assertNotIn("\t",s)
        self.assertTrue(s.endswith("…"))

    def test_opt_in_preview_only_stores_new_messages_and_clear_on_off(self):
        history=SimpleNamespace(configure=Mock(),insert=Mock(),see=Mock())
        app=SimpleNamespace(history=history,overlay_show_text=False,
            overlay_last_user="",overlay_last_answer="")
        Jarvis.log(app,"Вы","секретная фраза")
        self.assertEqual(app.overlay_last_user,"")
        Jarvis.set_overlay_preview(app,True)
        self.assertEqual(app.overlay_last_user,"")
        Jarvis.log(app,"Вы","новая команда")
        Jarvis.log(app,"JARVIS","новый ответ")
        self.assertIn("новая команда",app.overlay_last_user)
        self.assertIn("новый ответ",app.overlay_last_answer)
        Jarvis.set_overlay_preview(app,False)
        self.assertEqual(app.overlay_last_user,"")
        self.assertEqual(app.overlay_last_answer,"")


if __name__=="__main__":
    unittest.main()
