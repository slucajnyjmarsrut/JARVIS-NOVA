# -*- coding: utf-8 -*-
"""Regression coverage for responsive dark UI and faster real scenarios."""
import json
import time
import tempfile
import tkinter as tk
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import Mock, patch

from quick_video_brief import quick_brief, select_brief
from viral_studio import create_local_brief, template_brief
from nova_command_palette import clamp_popup, entries


class ScriptSpeedTests(TestCase):
    def test_fast_no_model_calls_and_topic_specific(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("fast mode invoked slow model")
        brief,note=select_brief("гитара / караоки",mode="fast",
                               ai_generator=forbidden)
        self.assertIn("гитар",brief.shots[0].film.lower())
        self.assertIn("песн",brief.shots[1].film.lower())
        self.assertIn("без нейросети",brief.generator)
        self.assertIn("без ожидания",note)
        self.assertGreaterEqual(len(brief.shots),3)

    def test_ai_timeout_and_fallback(self):
        calls=[]
        def model(topic,trends,**kwargs):
            calls.append(kwargs)
            return template_brief(topic)
        select_brief("Roblox",mode="standard",runtime=Mock(),
                     ai_generator=model)
        select_brief("Roblox",mode="deep",runtime=Mock(),
                     ai_generator=model)
        self.assertEqual(calls[0]["timeout_seconds"],20)
        self.assertEqual(calls[1]["timeout_seconds"],75)
        self.assertFalse(calls[0]["stop_runtime"])
        brief,note=select_brief("гитара",mode="standard",
            ai_generator=lambda *a,**kw: (_ for _ in ()).throw(ValueError("bad json")))
        self.assertIn("без нейросети",brief.generator)
        self.assertIn("Qwen не завершила",note)

    def test_qwen_fenced_json_parsed(self):
        runtime=Mock()
        runtime.start.return_value="http://127.0.0.1:4321"
        data={"title":"Ролик","hook":"Смотри","script":"Запиши кадры",
              "shots":[{"seconds":3,"film":"Покажи гитару","caption":"Аккорд"},
                       {"seconds":4,"film":"Сними реакцию","caption":"Вау"}],
              "call_to_action":"Комментируй"}
        raw="<think>internal</think>\n"+chr(96)*3+"json\n"+json.dumps(
            data,ensure_ascii=False)+"\n"+chr(96)*3
        result=create_local_brief("гитара",model_runtime=runtime,
            requester=lambda u,p:{"response":raw},stop_runtime=False)
        self.assertEqual(result.title,"Ролик")
        runtime.stop.assert_not_called()


class PaletteTests(TestCase):
    def test_popup_fits_small_screen(self):
        for width,height in ((430,700),(800,600),(1920,1080),(320,280)):
            x,y,w,h=clamp_popup(width-5,height-9,360,560,width,height)
            self.assertGreaterEqual(x,8)
            self.assertGreaterEqual(y,8)
            self.assertLessEqual(x+w,width-8)
            self.assertLessEqual(y+h,height-8)

    def test_menu_actions_and_no_native_popup(self):
        source=(Path(__file__).resolve().parents[1]/
                "text_only_main.py").read_text(encoding="utf-8")
        self.assertIn("nova_command_palette import show_palette",source)
        self.assertNotIn("menu = tk.Menu(self)",source)
        labels=[row[1] for row in entries(Mock()) if row]
        for label in ("Разрешения","Режимы работы","Выбрать AI",
                      "Видео-студия","FilmCraft · открыть редактор"):
            self.assertIn(label,labels)


class StudioTests(TestCase):
    def _start(self):
        try:
            root=tk.Tk()
            root.withdraw()
            root._closing=False
            return root
        except tk.TclError as exc:
            self.skipTest("No display: "+str(exc))

    def test_dark_studio_and_plan_button(self):
        from viral_studio_ui import ViralStudioWindow
        root=self._start()
        try:
            studio=ViralStudioWindow(root,speaker=None)
            studio.update_idletasks()
            self.assertEqual(studio.scenario_mode.get(),"fast")
            self.assertEqual(studio.viewer.cget("fg"),"#EAF5FC")
            self.assertTrue(studio.filmcraft_button.winfo_exists())
            self.assertTrue(studio.controls_canvas.winfo_exists())
            studio.brief=quick_brief("гитара / караоки")
            studio.read_shots()
            self.assertIn("Сними выбор песни",studio.viewer.get("1.0","end"))
            studio.copy_result()
            self.assertIn("ПЛАН СЪЁМКИ",studio.clipboard_get())
            studio.close()
        finally:
            root.destroy()

    def test_fast_scenario_without_csv_creates_files_and_not_ai(self):
        from viral_studio_ui import ViralStudioWindow
        import viral_studio_ui
        root=self._start()
        try:
            studio=ViralStudioWindow(root,speaker=None)
            studio.topic.set("гитара / караоки")
            studio.scenario_mode.set("fast")
            with tempfile.TemporaryDirectory() as temp:
                with patch.object(viral_studio_ui,"_home",return_value=Path(temp)):
                    with patch("viral_studio.create_local_brief",
                          side_effect=AssertionError("Model started in fast mode")):
                        started=time.monotonic()
                        studio.generate()
                        while studio.running and time.monotonic()-started<8:
                            root.update()
                            time.sleep(.03)
                        root.update()
                        self.assertFalse(studio.running)
                        self.assertIsNotNone(studio.brief)
                        self.assertTrue((studio.project/"brief.json").exists())
            studio.close()
        finally:
            root.destroy()


if __name__=="__main__":
    main()
