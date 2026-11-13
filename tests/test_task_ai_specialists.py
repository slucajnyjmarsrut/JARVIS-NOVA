# -*- coding: utf-8 -*-
"""Each JARVIS task has an explicit isolated model, not a rebranded Qwen."""
import json
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from task_ai_registry import (
    SPECIALISTS, ROLE_ORDER, SpecialistUnavailable,
    get_specialist, local_tags, specialist_available,
    specialist_help, pull_specialist,
)
from scenario_specialist import (
    create_specialist_brief, request_local_writer, WRITER_SYSTEM,
)
from video_scenario_autonomy import create_checked_scenario
from viral_studio import Brief
from viral_studio_ui import ViralStudioWindow


def five_scene_json():
    roles=("hook","setup","action","result","ending")
    descriptions=(
        "Показать готовый красивый рецепт салата на тарелке",
        "Снять сверху овощи и чистую разделочную доску",
        "Показать нарезку огурцов аккуратными ломтиками",
        "Смешать овощи в чаше и показать результат сбоку",
        "Крупный план готового салата на столе с вопросом",
    )
    return dict(
        title="Как сделать свежий овощной салат",
        hook="Удивительно вкусно за пару минут!",
        script=("Сначала показываю сочный свежий салат. Затем объясняю, "
                "какие овощи надо взять и как их тщательно помыть. "
                "Нарезаю огурцы, смешиваю продукты, показываю красивую "
                "подачу и прошу зрителей поделиться любимым рецептом."),
        scenes={role:dict(seconds=3 if i==0 else 6,
                          film=descriptions[i],caption=f"Шаг {i+1} — {role}")
                for i,role in enumerate(roles)},
        call_to_action="Какой салат любишь готовить ты?",
    )


class TaskAIRegistryTests(unittest.TestCase):
    def test_roles_are_explicit_and_writer_is_not_bundled_qwen(self):
        self.assertEqual(set(ROLE_ORDER),set(SPECIALISTS))
        self.assertEqual(get_specialist("scenario").model,"gemma3:4b")
        self.assertEqual(get_specialist("code").model,"qwen2.5-coder:7b")
        self.assertEqual(get_specialist("montage").model,"llama3.2:3b")
        self.assertEqual(get_specialist("vision").model,"qwen3-vl:2b-instruct")
        self.assertEqual(get_specialist("chat").model,"qwen3:4b")
        self.assertEqual(get_specialist("scenario").backend,"ollama")
        self.assertEqual(get_specialist("vision").backend,"bundled")
        with self.assertRaises(ValueError):
            get_specialist("erase-user-files")

    def test_installed_is_from_live_ollama_not_disk_inventory(self):
        tags=lambda:{"models":[{"name":"gemma3:4b","size":3_400_000_000},
                               {"name":"qwen2.5-coder:7b","size":4_700_000_000}]}
        self.assertEqual(local_tags(transport=tags),
                         ("gemma3:4b","qwen2.5-coder:7b"))
        self.assertTrue(specialist_available("scenario",transport=tags))
        self.assertTrue(specialist_available("code",transport=tags))
        self.assertFalse(specialist_available("montage",transport=tags))
        self.assertIn("ollama pull gemma3:4b",specialist_help("scenario"))
        self.assertFalse(specialist_available("chat",transport=tags))
        for malformed in ({},[],{"models":"bad"}):
            with self.subTest(malformed=malformed):
                with self.assertRaises(SpecialistUnavailable):
                    local_tags(transport=lambda:malformed)

    def test_model_download_requires_user_permission_and_fixed_cli(self):
        with mock.patch("task_ai_registry.shutil.which") as which:
            with self.assertRaises(PermissionError):
                pull_specialist("scenario",confirmed=False)
            which.assert_not_called()
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/"ollama.exe"
            exe.write_text("FAKE",encoding="utf-8")
            count=[0]
            def inventory():
                count[0]+=1
                return {"models":[] if count[0]==1 else
                        [{"name":"gemma3:4b"}]}
            class Process:
                returncode=0
                def poll(self):return 0
            launched=[]
            def fake_process(argv,**kwargs):
                launched.append((argv,kwargs))
                return Process()
            model=pull_specialist(
                "scenario",confirmed=True,executable=str(exe),
                transport=inventory,launcher=fake_process)
            self.assertEqual(model,"gemma3:4b")
            argv,options=launched[0]
            self.assertEqual(argv,[str(exe.absolute()),"pull","gemma3:4b"])
            self.assertIs(options["shell"],False)
            self.assertEqual(options["env"]["OLLAMA_HOST"],"127.0.0.1:11434")
            self.assertNotIn("HTTP_PROXY",options["env"])
        with self.assertRaises(PermissionError):
            pull_specialist("montage")
        with self.assertRaises(SpecialistUnavailable):
            pull_specialist("vision",confirmed=True)

    def test_cancelled_download_does_not_launch_process_or_delete_weights(self):
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/"ollama.exe"
            exe.write_text("FAKE",encoding="utf-8")
            stopped=threading.Event();stopped.set()
            with mock.patch("task_ai_registry.subprocess.Popen") as process:
                with self.assertRaisesRegex(SpecialistUnavailable,"отмен"):
                    pull_specialist(
                        "scenario",confirmed=True,cancel=stopped,
                        transport=lambda:{"models":[]},executable=str(exe))
                process.assert_not_called()
            self.assertTrue(exe.exists())


class ScreenwriterSpecialistTests(unittest.TestCase):
    def test_dedicated_gemma_generates_actual_json_not_vision_qwen(self):
        prompts=[]
        def requester(url,payload):
            prompts.append((url,payload))
            return {"response":json.dumps(five_scene_json(),ensure_ascii=False)}
        with mock.patch("scenario_specialist.specialist_available",
                        return_value=True):
            brief=create_specialist_brief(
                "Овощной салат",requester=requester)
        self.assertIsInstance(brief,Brief)
        self.assertEqual(brief.generator,"локальная Gemma3:4b")
        self.assertEqual(len(brief.shots),5)
        self.assertEqual(len(prompts),1)
        url,payload=prompts[0]
        self.assertEqual(url,"http://127.0.0.1:11434/api/generate")
        self.assertEqual(payload["model"],"gemma3:4b")
        self.assertNotIn("tools",payload)
        self.assertIn(WRITER_SYSTEM,payload["prompt"])
        self.assertEqual(payload["format"]["type"],"object")

    def test_legacy_brief_path_never_uses_vision_qwen(self):
        from quick_video_brief import quick_brief, select_brief
        from dataclasses import replace
        draft=replace(quick_brief("Овощной салат"),
                      generator="локальная Gemma3:4b")
        with mock.patch("scenario_specialist.create_specialist_brief",
                        return_value=draft) as writer, \
             mock.patch("viral_studio.create_local_brief") as vision_writer:
            result,note=select_brief("Овощной салат",mode="standard")
        writer.assert_called_once()
        self.assertEqual(result.generator,"локальная Gemma3:4b")
        self.assertIn("Gemma3:4b",note)
        vision_writer.assert_not_called()
        with mock.patch("scenario_specialist.create_specialist_brief",
                        side_effect=RuntimeError("Gemma not ready")), \
             mock.patch("viral_studio.create_local_brief") as vision_writer:
            result,note=select_brief("Овощной салат",mode="deep")
        self.assertIn("БЕЗ нейросети",note)
        self.assertNotIn("Qwen3-VL",result.generator)
        vision_writer.assert_not_called()

    def test_studio_defaults_to_real_writer_not_unmarked_template(self):
        from pathlib import Path
        src=(Path(__file__).resolve().parents[1]/
             "viral_studio_ui.py").read_text(encoding="utf-8")
        self.assertIn('self.scenario_mode=tk.StringVar(value="standard")',src)
        self.assertIn('("standard","ИИ-сценарист · Gemma3")',src)

    def test_model_absence_never_silently_uses_qwen3_vl(self):
        with mock.patch("scenario_specialist.specialist_available",
                        return_value=False):
            with mock.patch("viral_studio.create_local_brief") as bundled:
                with self.assertRaisesRegex(SpecialistUnavailable,"Gemma|ИИ-сценарист"):
                    create_specialist_brief("Сюжет")
                bundled.assert_not_called()

    def test_default_scenario_workflow_routes_to_writer_not_vision(self):
        from quick_video_brief import quick_brief
        from dataclasses import replace
        written=replace(quick_brief("Овощной салат"),
                        generator="локальная Gemma3:4b")
        with mock.patch("scenario_specialist.create_specialist_brief",
                        return_value=written) as writer:
            with mock.patch("viral_studio.create_local_brief") as vision_writer:
                brief,note,quality,attempts=create_checked_scenario(
                    "Овощной салат",mode="deep")
        self.assertTrue(quality.passed)
        self.assertEqual(brief.generator,"локальная Gemma3:4b")
        self.assertIn("Gemma3:4b",note)
        self.assertEqual(attempts,1)
        writer.assert_called_once()
        vision_writer.assert_not_called()

    def test_ollama_writer_url_and_model_cannot_escape_localhost(self):
        for endpoint in ("https://127.0.0.1:11434/api/generate",
                         "http://evil.example/api/generate",
                         "http://127.0.0.1:11434/api/delete",
                         "http://127.0.0.1:11434/api/generate?x=1",
                         "http://localhost:11434/api/generate"):
            with self.subTest(endpoint=endpoint),self.assertRaises(SpecialistUnavailable):
                request_local_writer(endpoint,{"model":"gemma3:4b"})
        with self.assertRaises(SpecialistUnavailable):
            request_local_writer(
                "http://127.0.0.1:11434/api/generate",
                {"model":"qwen3-vl:2b-instruct"})

    def test_studio_refuses_ai_mode_until_writer_is_installed(self):
        studio=mock.Mock()
        with mock.patch("task_ai_registry.specialist_available",return_value=False),\
             mock.patch("viral_studio_ui.messagebox.showinfo") as shown:
            self.assertFalse(
                ViralStudioWindow._check_writer_for_generation(studio,"deep"))
            shown.assert_called_once()
            self.assertIn("ПОДКЛЮЧИТЬ ИИ-СЦЕНАРИСТА",
                          shown.call_args.args[1])
        with mock.patch("task_ai_registry.specialist_available",return_value=True):
            self.assertTrue(ViralStudioWindow._check_writer_for_generation(
                studio,"standard"))
        self.assertTrue(ViralStudioWindow._check_writer_for_generation(
            studio,"fast"))

    def test_hub_connect_button_requires_explicit_confirmation(self):
        from task_ai_hub import TaskAIHub
        try:
            window=tk.Tk()
        except tk.TclError:
            self.skipTest("No Tk on runner")
        try:
            window.withdraw()
            hub=TaskAIHub(window)
            with mock.patch("task_ai_hub.messagebox.askyesno",
                            return_value=False):
                with mock.patch("task_ai_hub.pull_specialist") as pull:
                    hub.connect("scenario")
                    pull.assert_not_called()
            self.assertEqual(len(hub._buttons),4)
            self.assertEqual(hub._states["scenario"].get(),"не проверено")
            hub.destroy()
        finally:
            window.destroy()



    def test_hub_legacy_chat_button_requires_real_chat_instance(self):
        from task_ai_hub import TaskAIHub
        try:
            window=tk.Tk()
        except tk.TclError:
            self.skipTest("No Tk on runner")
        try:
            window.withdraw()
            hub=TaskAIHub(window)
            self.assertFalse(hub.use_legacy_chat())
            window.local_chat=mock.Mock()
            self.assertTrue(hub.use_legacy_chat())
            window.local_chat.prefer_task_specialist.assert_called_once_with(False)
            self.assertIn("прежний чат",hub.status.get().lower())
            hub.destroy()
        finally:
            window.destroy()

    def test_dedicated_chat_uses_different_weights_when_available(self):
        from local_chat import LocalChat
        from types import SimpleNamespace
        class Bundled:
            config=SimpleNamespace(model="qwen3-vl:2b-instruct")
            def start(self):
                raise AssertionError("Bundled vision should not start")
        requests=[]
        def fake(endpoint,payload):
            requests.append((endpoint,payload))
            return {"message":{"content":"Отдельный разговорный ответ"}}
        chat=LocalChat(Bundled(),requester=fake)
        chat.prefer_task_specialist(True)
        with mock.patch("task_ai_registry.specialist_available",
                        return_value=True):
            answer=chat.ask("Объясни понятными словами, как устроен JARVIS")
        self.assertIn("разговорный",answer)
        self.assertEqual(requests[0][0],"http://127.0.0.1:11434")
        self.assertEqual(requests[0][1]["model"],"qwen3:4b")
        self.assertNotIn("tools",requests[0][1])
        chat.close()

    def test_selected_chat_never_falls_back_to_vision_without_model(self):
        from local_chat import LocalChat, LocalChatError
        from types import SimpleNamespace
        class Bundled:
            config=SimpleNamespace(model="qwen3-vl:2b-instruct")
            def start(self):
                raise AssertionError("Vision must not start in specialist mode")
        request=mock.Mock(side_effect=AssertionError("No model call allowed"))
        chat=LocalChat(Bundled(),requester=request)
        chat.prefer_task_specialist(True)
        with mock.patch("task_ai_registry.specialist_available",
                        return_value=False):
            with self.assertRaisesRegex(LocalChatError,"Qwen3:4b"):
                chat.ask("Расскажи о своих возможностях")
        request.assert_not_called()

    def test_opt_out_restores_legacy_vision_chat_explicitly(self):
        from local_chat import LocalChat
        from types import SimpleNamespace
        class Bundled:
            config=SimpleNamespace(model="qwen3-vl:2b-instruct")
            def start(self):
                return "http://127.0.0.1:23333"
        calls=[]
        chat=LocalChat(Bundled(),requester=lambda endpoint,payload:(
            calls.append((endpoint,payload)),
            {"message":{"content":"Ответ прежнего режима"}})[1])
        chat.prefer_task_specialist(True)
        chat.prefer_task_specialist(False)
        self.assertIn("прежнего",chat.ask("Расскажи о возможностях"))
        self.assertEqual(calls[0][0],"http://127.0.0.1:23333")
        self.assertEqual(calls[0][1]["model"],"qwen3-vl:2b-instruct")

    def test_montage_is_separate_read_only_llama_advice(self):
        from montage_specialist import advise_montage, MontageAdvice
        from quick_video_brief import quick_brief
        brief=quick_brief("видеоролик")
        requests=[]
        advice_data={
            "pace":"Начни быстро, замедли финал и оставь паузу",
            "transitions":"Используй простые плавные склейки без вспышек",
            "shot_notes":[f"Для сцены {i} используй отдельный ракурс"
                          for i in range(1,6)],
        }
        with mock.patch("montage_specialist.specialist_available",
                        return_value=True):
            result=advise_montage(
                brief,requester=lambda endpoint,payload:(
                    requests.append((endpoint,payload)),
                    {"response":json.dumps(advice_data,ensure_ascii=False)})[1])
        self.assertIsInstance(result,MontageAdvice)
        self.assertEqual(result.model,"llama3.2:3b")
        self.assertEqual(len(result.shot_notes),5)
        self.assertIn("НЕ выполненные действия",result.render())
        self.assertNotIn("tools",requests[0][1])
        self.assertEqual(requests[0][1]["model"],"llama3.2:3b")
        with mock.patch("montage_specialist.specialist_available",
                        return_value=False):
            with self.assertRaises(SpecialistUnavailable):
                advise_montage(brief)

if __name__=="__main__":
    unittest.main()
