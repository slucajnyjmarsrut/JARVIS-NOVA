# -*- coding: utf-8 -*-
"""Chat-first text commands do not bypass permissions or invoke unsafe actions."""
import unittest
from unittest.mock import Mock
from chat_first_intent import ChatIntent, route_chat_request
from text_only_main import TextJarvis


class ChatFirstTests(unittest.TestCase):
    def test_natural_requests_open_existing_features(self):
        phrases={
            "хочу смонтировать видео":("timeline",""),
            "Джарвис, хочу сделать монтаж":("timeline",""),
            "хочу добавить озвучку к видео":("multitrack",""),
            "хочу наложить логотип":("multitrack",""),
            "хочу эдит":("edits",""),
            "хочу создать ролик":("studio",""),
            "хочу опубликовать видео":("publish",""),
            "хочу зарегистрироваться в tiktok":("accounts",""),
            "открой FilmCraft":("filmcraft",""),
            "хочу показать скриншот":("screenshot",""),
            "открой настройки":("settings",""),
            "проверь обновления":("updates",""),
            "установи Qwen":("model",""),
            "отмени загрузку Qwen":("cancel_model",""),
            "давай поиграем":("gaming",""),
            "хочу открыть браузер":("open_desktop","браузер"),
            "хочу использовать FreeLLM":("engine","freellm"),
            "покажи команды":("help",""),
        }
        for sentence,(kind,value) in phrases.items():
            with self.subTest(sentence=sentence):
                intent=route_chat_request(sentence)
                self.assertIsNotNone(intent)
                self.assertEqual((intent.kind,intent.value),(kind,value))

    def test_model_commands_accept_ui_text_and_natural_infinitives(self):
        # These phrases are shown to users by JARVIS or typed in the chat.
        phrases={
            "проверить локальную модель":"model",
            "проверь локальную модель":"model",
            "скачать модель":"model",
            "скачай модель":"model",
            "скачать Qwen":"model",
            "проверить Qwen":"model",
            "найди модели":"model_scan",
            "найти модели":"model_scan",
            "найди модели на всех дисках":"model_scan",
        }
        for phrase,kind in phrases.items():
            with self.subTest(phrase=phrase):
                intent=route_chat_request(phrase)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.kind,kind)
                app=Mock()
                TextJarvis._dispatch_chat_first(app,intent,phrase)
                method="check_models" if kind=="model" else "scan_models_on_pc"
                getattr(app,method).assert_called_once_with()
                app.execute_plan.assert_not_called()
                app.download_local_model.assert_not_called()

    def test_model_questions_negations_do_not_start_model_actions(self):
        for phrase in (
            "как скачать модель", "почему проверить локальную модель",
            "не скачай модель", "не надо скачивать модель",
            "объясни как установить qwen", "если я напишу скачать модель",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(route_chat_request(phrase))

    def test_longform_chat_requests_one_permission_autoexport(self):
        request="хочу сделать 15 минут из двухчасового видео"
        intent=route_chat_request(request)
        self.assertEqual(intent.kind,"longform")
        app=Mock()
        TextJarvis._dispatch_chat_first(app,intent,request)
        app.open_timeline.assert_called_once()
        window=app.open_timeline.return_value
        window.after.assert_called_once()
        callback=window.after.call_args.args[1]
        callback()
        window.prepare_longform.assert_called_once_with(auto_export=True)
        app.execute_plan.assert_not_called()

    def test_code_language_and_ambiguous_tasks(self):
        for phrase,language in (
            ("хочу написать программу на Python","python"),
            ("хочу создать игру на Roblox","luau"),
            ("хочу написать сайт","html"),
            ("хочу сделать приложение","python"),
            ("хочу создать приложение на Java","java"),
            ("хочу написать программу на Python и Java",""),
        ):
            with self.subTest(phrase=phrase):
                intent=route_chat_request(phrase)
                self.assertEqual(intent.kind,"code")
                self.assertEqual(intent.value,language)

    def test_questions_negations_and_quotes_are_not_actions(self):
        for sentence in (
            "как смонтировать видео?", "почему лучше Qwen?",
            "расскажи про настройки", "что будет если открыть браузер",
            "не открывай настройки", "я не хочу открыть браузер",
            "если я скажу хочу сделать монтаж, что будет?",
            "объясни как разрешить управление ПК",
            "давай поспорим", "открой Chrome", "открой cmd",
            "", "а"*1201,
        ):
            with self.subTest(sentence=sentence[:50]):
                self.assertIsNone(route_chat_request(sentence))

    def test_dispatch_uses_exact_existing_methods_not_dynamic_eval(self):
        for kind,method in (
            ("timeline","open_timeline"),("multitrack","open_multitrack"),
            ("studio","open_viral_studio"),("edits","open_viral_studio"),
            ("publish","open_publish_preparation"),("screenshot","open_screenshot_review"),
            ("updates","show_update_center"),("model","check_models"),
            ("settings","show_settings_menu"),("cancel_model","cancel_local_model_download"),
        ):
            with self.subTest(kind=kind):
                app=Mock()
                TextJarvis._dispatch_chat_first(app,ChatIntent(kind),"Пожелание")
                getattr(app,method).assert_called_once()
                app.execute_plan.assert_not_called()
                app.log.assert_called_once_with("Вы","Пожелание")

    def test_desktop_plan_reuses_safe_existing_parser(self):
        app=Mock()
        TextJarvis._dispatch_chat_first(
            app,ChatIntent("open_desktop","калькулятор"),
            "хочу открыть калькулятор")
        plan=app.execute_plan.call_args.args[0]
        self.assertEqual(len(plan.steps),1)
        self.assertEqual(plan.steps[0].kind,"open_app")
        self.assertEqual(plan.steps[0].value,"Calculator")
        bad=Mock()
        TextJarvis._dispatch_chat_first(
            bad,ChatIntent("open_desktop","powershell"),
            "хочу открыть powershell")
        bad_plan=bad.execute_plan.call_args.args[0]
        self.assertEqual(bad_plan.steps,[])
        self.assertTrue(bad_plan.question)

    def test_privacy_operations_only_call_existing_confirmation_handlers(self):
        for kind,name in (
            ("permission_control","grant_control"),
            ("permission_screen","grant_vision"),
            ("revoke","revoke"),("engine","set_engine"),
        ):
            with self.subTest(kind=kind):
                app=Mock()
                TextJarvis._dispatch_chat_first(
                    app,ChatIntent(kind,"freellm" if kind=="engine" else ""),
                    "разрешение")
                getattr(app,name).assert_called_once()
                app.execute_plan.assert_not_called()
        app=Mock()
        TextJarvis._dispatch_chat_first(
            app,ChatIntent("code",""),"хочу написать на Python и Java")
        app.open_code_assistant.assert_not_called()
        app.reply.assert_called_once()

    def test_text_handler_routes_before_generic_model_chat(self):
        app=Mock()
        app._closing=False
        TextJarvis.handle_text(app,"хочу смонтировать видео")
        app._dispatch_chat_first.assert_called_once()
        intent,original=app._dispatch_chat_first.call_args.args
        self.assertEqual(intent.kind,"timeline")
        self.assertEqual(original,"хочу смонтировать видео")
        app.open_code_assistant.assert_not_called()


if __name__=="__main__":
    unittest.main()
