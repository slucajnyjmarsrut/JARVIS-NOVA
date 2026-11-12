# -*- coding: utf-8 -*-
"""No-button autonomous scenario creation and bounded local QA."""
from dataclasses import replace
from unittest import TestCase, mock

from chat_first_intent import route_chat_request
from text_only_main import TextJarvis
from quick_video_brief import quick_brief
from viral_studio import Brief, Shot
from video_scenario_autonomy import assess_scenario, create_checked_scenario


class AutonomousScenarioTests(TestCase):
    def test_chat_routes_specific_scenario_to_generation_not_just_editor(self):
        for request in (
            "создай сценарий про Minecraft",
            "хочу написать сценарий про Roblox",
            "сделай сценарий для ролика на тему готовки",
        ):
            intent=route_chat_request(request)
            self.assertIsNotNone(intent,request)
            self.assertEqual(intent.kind,"scenario")
            self.assertTrue(intent.value)
        self.assertIsNone(route_chat_request("как создать сценарий про minecraft"))

    def test_scenario_request_starts_real_ui_generator_after_open(self):
        app=mock.Mock()
        app._local_model_ready=True
        studio=app.open_viral_studio.return_value
        intent=route_chat_request("создай сценарий про minecraft")
        TextJarvis._dispatch_chat_first(app,intent,"создай сценарий про minecraft")
        app.open_viral_studio.assert_called_once_with(stage="script")
        studio.topic.set.assert_called_once_with("minecraft")
        studio.scenario_mode.set.assert_called_once_with("deep")
        studio.after.assert_called_once()
        self.assertIs(studio.after.call_args.args[1],studio.generate)
        app.execute_plan.assert_not_called()
        app._local_model_ready=False
        app.reset_mock()
        TextJarvis._dispatch_chat_first(app,intent,"создай сценарий про minecraft")
        app.open_viral_studio.return_value.scenario_mode.set.assert_called_with(
            "fast")

    def test_quick_fallback_has_valid_storyboard_and_honest_label(self):
        brief,note,assessment,attempts=create_checked_scenario(
            "minecraft",mode="fast",
            ai_generator=lambda *a,**k:self.fail("Fast must not start model"))
        self.assertTrue(assessment.passed,assessment.issues)
        self.assertIn("без нейросети",note)
        self.assertEqual(attempts,1)
        self.assertNotIn("Qwen",brief.generator)

    def test_autonomous_scenario_produces_saved_shooting_plan(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from viral_studio import save_brief, load_brief, ViralStudioError
        with TemporaryDirectory() as tmp:
            brief,note,quality,_=create_checked_scenario(
                "Minecraft",mode="fast")
            self.assertTrue(quality.passed)
            destination=Path(tmp)/"scenarios"/"project"
            output=save_brief(brief,destination)
            self.assertTrue(output.is_file())
            self.assertEqual(load_brief(output),brief)
            notes=(destination/"WHAT_TO_FILM_RU.md").read_text("utf-8")
            self.assertIn("Что снять",notes)
            self.assertIn("Minecraft",notes)
            with self.assertRaises(ViralStudioError):
                save_brief(brief,destination)

    def test_ai_bad_scenario_is_retried_with_feedback_and_frozen_topic(self):
        weak=Brief("Minecraft — тест","minecraft","Смотри", "Коротко",
                   (Shot(8,"Общий план","План 1"),
                    Shot(8,"Общий план","План 1"),
                    Shot(8,"Общий план","План 1")),
                   "Комментируй","локальная Qwen3-VL")
        self.assertFalse(assess_scenario(weak).passed)
        strong=replace(quick_brief("minecraft"),generator="локальная Qwen3-VL")
        requests=[]
        def generator(topic,trends,**kw):
            requests.append((topic,kw))
            return weak if len(requests)==1 else strong
        brief,note,review,attempts=create_checked_scenario(
            "minecraft",mode="deep",ai_generator=generator)
        self.assertTrue(review.passed)
        self.assertEqual(attempts,2)
        self.assertEqual(len(requests),2)
        self.assertNotIn("quality_feedback",requests[0][1])
        self.assertIn("quality_feedback",requests[1][1])
        self.assertIn("Qwen",note)
        self.assertEqual(brief.generator,"локальная Qwen3-VL")

    def test_duplicate_feedback_names_the_actual_scene_roles(self):
        candidate=replace(quick_brief("салат"),
                          generator="локальная Qwen3-VL")
        shots=list(candidate.shots)
        shots[2]=replace(shots[2],caption=shots[0].caption,
                         film=shots[1].film)
        verdict=assess_scenario(replace(candidate,shots=tuple(shots)))
        self.assertFalse(verdict.passed)
        self.assertTrue(any(
            "Повторяются подписи кадров (hook=action)" in issue
            for issue in verdict.issues),verdict.issues)
        self.assertTrue(any(
            "Повторяются инструкции для съёмки (setup=action)" in issue
            for issue in verdict.issues),verdict.issues)

    def test_revision_contains_rejected_ai_shots_not_just_generic_feedback(self):
        original=replace(quick_brief("minecraft"),generator="локальная Qwen3-VL")
        repeated=replace(original,shots=(
            original.shots[0],*(
                replace(x,film="Один и тот же общий план")
                for x in original.shots[1:]
            )))
        calls=[]
        def generator(topic,trends,**kwargs):
            calls.append((topic,kwargs))
            return repeated if len(calls)==1 else original
        result,note,report,n=create_checked_scenario(
            "minecraft",mode="deep",ai_generator=generator)
        self.assertTrue(report.passed)
        self.assertEqual(n,2)
        self.assertEqual(calls[0][0],"minecraft")
        self.assertEqual(calls[1][1]["previous_brief"],repeated)
        self.assertIn("Повторяются инструкции",calls[1][1]["quality_feedback"])
        self.assertEqual(result.shots,original.shots)

    def test_qwen_shortens_hook_timing_without_rewriting_ai_scenes(self):
        original=quick_brief("minecraft")
        slow=replace(
            original,generator="локальная Qwen3-VL",
            shots=(replace(original.shots[0],seconds=8),*original.shots[1:]))
        brief,note,review,attempts=create_checked_scenario(
            "minecraft",mode="deep",max_revisions=0,
            ai_generator=lambda *args,**kw:slow)
        self.assertTrue(review.passed,review.issues)
        self.assertEqual(brief.shots[0].seconds,3.)
        self.assertEqual(brief.shots[0].film,slow.shots[0].film)
        self.assertEqual(brief.script,slow.script)
        self.assertEqual(attempts,1)

    def test_non_ai_generator_is_never_reported_as_qwen(self):
        brief,note,review,attempts=create_checked_scenario(
            "minecraft",mode="deep",max_revisions=0,
            ai_generator=lambda *a,**k:quick_brief("minecraft"))
        self.assertNotIn("Qwen",brief.generator)
        self.assertIn("БЕЗ нейросети",note)
        self.assertTrue(review.passed)

    def test_russian_topic_inflections_not_falsely_rejected(self):
        topic="Безопасная организация компьютерного рабочего места"
        shots=(
            Shot(3,"Показать провода под столом","Проблема"),
            Shot(6,"Снять вид сверху на стол","Первый шаг"),
            Shot(6,"Уложить кабели за монитор","Порядок"),
            Shot(6,"Показать организованный экран и стол","Результат"),
            Shot(6,"Снять финальную композицию предметов","Проверка"),
        )
        relevant=Brief(
            "Порядок рядом с компьютером",topic,
            "Посмотри, как стало удобно работать!",
            "Раньше на рабочем столе рядом с компьютером всё было "
            "разложено неудобно. Теперь убираю лишнее, укладываю "
            "кабели и проверяю, удобно ли пользоваться мышью. "
            "Показываю результат в конце.",
            shots,"Сохрани идею.","локальная Qwen3-VL")
        verdict=assess_scenario(relevant)
        self.assertTrue(verdict.passed,verdict.issues)
        unrelated=replace(
            relevant,title="Салат за минуту",hook="Что приготовим на ужин?",
            script="Сначала нужно нарезать огурцы и помидоры, затем "
                   "размешать заправку в миске. Добавляем немного масла, "
                   "перемешиваем ингредиенты и сервируем тарелку "
                   "для подачи готовой еды.",
            shots=(
                Shot(3,"Снять свежие овощи","Начало"),
                Shot(6,"Показать острый нож","Подготовка"),
                Shot(6,"Нарезать овощи на доске","Нарезка"),
                Shot(6,"Положить ингредиенты в миску","Соус"),
                Shot(6,"Показать салат на тарелке","Ужин"),
            ))
        verdict=assess_scenario(unrelated)
        self.assertFalse(verdict.passed)
        self.assertIn("Тема пользователя", "; ".join(verdict.issues))

    def test_bad_model_never_claims_ai_success(self):
        calls=[]
        def generator(*a,**kw):
            calls.append(kw)
            raise RuntimeError("No model installed")
        result,note,review,n=create_checked_scenario(
            "Roblox",mode="standard",ai_generator=generator)
        self.assertIn("БЕЗ нейросети",note)
        self.assertTrue(review.passed)
        self.assertEqual(n,3)
        self.assertEqual(len(calls),3)
        self.assertIn("без нейросети",result.generator)

    def test_models_scan_is_not_silent_and_has_explicit_cancel(self):
        for question,expected in (
            ("найди модели на всех дисках","model_scan"),
            ("проверь все модели на компьютере","model_scan"),
            ("останови поиск моделей","cancel_model_scan"),
        ):
            self.assertEqual(route_chat_request(question).kind,expected)
        self.assertIsNone(route_chat_request("не проверяй модели на всех дисках"))
        app=mock.Mock()
        for action,method in (
            ("model_scan","scan_models_on_pc"),
            ("cancel_model_scan","cancel_model_scan"),
        ):
            app.reset_mock()
            TextJarvis._dispatch_chat_first(
                app,mock.Mock(kind=action,value=""),"Пожелание")
            getattr(app,method).assert_called_once()
            app.execute_plan.assert_not_called()


if __name__=="__main__":
    import unittest
    unittest.main()
