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
            "установи Qwen":("model_download",""),
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

    def test_visible_action_names_are_recognized_as_safe_requests(self):
        phrases={
            "создать видео":"studio",
            "смонтировать видео":"timeline",
            "написать код":"code_start",
            "разобрать снимок":"screenshot",
        }
        for phrase,kind in phrases.items():
            with self.subTest(phrase=phrase):
                intent=route_chat_request(phrase)
                self.assertEqual(intent.kind,kind)
                app=Mock()
                TextJarvis._dispatch_chat_first(app,intent,phrase)
                app.execute_plan.assert_not_called()
                app.grant_vision.assert_not_called()
                app.grant_control.assert_not_called()
                app.download_local_model.assert_not_called()
                if kind=="code_start":
                    app.open_code_assistant.assert_called_once_with(
                        "python", "", auto_start=False)
                elif kind=="studio":
                    app.open_viral_studio.assert_called_once_with(
                        stage="audience")
                elif kind=="timeline":
                    app.open_timeline.assert_called_once_with()
                elif kind=="screenshot":
                    app.open_screenshot_review.assert_called_once_with()

    def test_short_ambiguous_requests_get_choices_not_actions(self):
        prompts={
            "видео":"clarify_video",
            "Джарвис, ролик":"clarify_video",
            "модели":"clarify_model",
            "Qwen":"clarify_model",
            "экран":"clarify_screen",
            "скриншот":"clarify_screen",
            "код":"clarify_code",
            "программа":"clarify_code",
            "помоги":"help",
            "не понимаю что делать":"help",
        }
        for phrase,expected in prompts.items():
            with self.subTest(phrase=phrase):
                intent=route_chat_request(phrase)
                self.assertEqual(intent.kind,expected)
                app=Mock()
                app._local_model_ready=False
                TextJarvis._dispatch_chat_first(app,intent,phrase)
                app.reply.assert_called_once()
                self.assertTrue(app.reply.call_args.args[0])
                app.execute_plan.assert_not_called()
                app.grant_vision.assert_not_called()
                app.grant_control.assert_not_called()
                app.download_local_model.assert_not_called()
                app.open_screenshot_review.assert_not_called()
        for sentence in ("как скачать модель", "не разрешаю экран",
                         "почему видео не работает", "если я скажу модель"):
            with self.subTest(negative=sentence):
                self.assertIsNone(route_chat_request(sentence))

    def test_screen_consent_phrasing_does_not_skip_the_confirmation(self):
        requests=(
            "зрение и экран разрешаю",
            "экран и зрение разрешаю",
            "зрение разрешаю",
            "разрешаю доступ к экрану",
            "разрешить доступ к экрану",
            "включи зрение",
            "разреши видеть экран",
            "хочу дать доступ к экрану",
        )
        for phrase in requests:
            with self.subTest(phrase=phrase):
                intent=route_chat_request(phrase)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.kind,"permission_screen")
                app=Mock()
                app.vision_allowed=False  # User has not approved modal.
                TextJarvis._dispatch_chat_first(app,intent,phrase)
                app.grant_vision.assert_called_once_with()
                app.reply.assert_called_once()
                self.assertIn("не предоставлен",app.reply.call_args.args[0])
                app.execute_plan.assert_not_called()

        app=Mock()
        app.vision_allowed=False
        def approved():
            app.vision_allowed=True
        app.grant_vision.side_effect=approved
        TextJarvis._dispatch_chat_first(
            app,ChatIntent("permission_screen"),"зрение и экран разрешаю")
        self.assertIn("Доступ к экрану разрешён",app.reply.call_args.args[0])
        app.grant_control.assert_not_called()
        app.request_trimodal.assert_not_called()

    def test_model_commands_accept_ui_text_and_natural_infinitives(self):
        # These phrases are shown to users by JARVIS or typed in the chat.
        phrases={
            "проверить локальную модель":"model",
            "проверь локальную модель":"model",
            "скачать модель":"model_download",
            "скачай модель":"model_download",
            "скачать Qwen":"model_download",
            "скачай qwen":"model_download",
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
                if kind=="model_download":
                    app.check_models.assert_called_once_with(offer_scan=False)
                else:
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

    def test_direct_download_skips_search_but_requires_permission(self):
        from unittest.mock import patch
        app=Mock()
        app._model_download_busy=False
        app._model_scan_busy=False
        app._asset_root="assets"
        app.runtime.config.model_store="empty"
        with patch("bundled_vision_runtime.validate_offline_model_store",
                   side_effect=RuntimeError("No Qwen")):
            with patch("text_only_main.messagebox.askyesno",return_value=True) as ask:
                TextJarvis.check_models(app,offer_scan=False)
        ask.assert_called_once()
        self.assertIn("Скачать",ask.call_args.args[0])
        app.scan_models_on_pc.assert_not_called()
        app.download_local_model.assert_called_once()

        app.reset_mock()
        with patch("bundled_vision_runtime.validate_offline_model_store",
                   side_effect=RuntimeError("No Qwen")):
            with patch("text_only_main.messagebox.askyesno",return_value=False) as ask:
                TextJarvis.check_models(app,offer_scan=False)
        ask.assert_called_once()
        app.scan_models_on_pc.assert_not_called()
        app.download_local_model.assert_not_called()

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
            "как разрешить зрение", "почему ты не видишь экран",
            "не разрешаю зрение", "не разрешай экран",
            "если я напишу зрение и экран разрешаю, что будет",
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
            ("model_download","check_models"),
            ("settings","show_settings_menu"),("cancel_model","cancel_local_model_download"),
        ):
            with self.subTest(kind=kind):
                app=Mock()
                TextJarvis._dispatch_chat_first(app,ChatIntent(kind),"Пожелание")
                if kind=="model_download":
                    app.check_models.assert_called_once_with(offer_scan=False)
                else:
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
        # A regular command must bypass semantic inference and its state.
        app._semantic_busy=False
        app._semantic_epoch=0
        TextJarvis.handle_text(app,"хочу смонтировать видео")
        app._dispatch_chat_first.assert_called_once()
        intent,original=app._dispatch_chat_first.call_args.args
        self.assertEqual(intent.kind,"timeline")
        self.assertEqual(original,"хочу смонтировать видео")
        app.open_code_assistant.assert_not_called()
        self.assertEqual(app._semantic_epoch,0)
        app._semantic_queue.put.assert_not_called()


if __name__=="__main__":
    unittest.main()
