# -*- coding: utf-8 -*-
"""Plan, separately verify each step, then check the combined project.

All generated Python is AST-parsed only; no model-provided code runs here.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from code_project_engine import (
    build_complete_project, build_one_shot_project, describe_execution_plan,
)
from code_autopilot import install_reviewed
from code_workspace import WorkspaceError


def proposal(files, language="python"):
    return json.dumps({
        "language": language,
        "files": [{"path": path, "content": content}
                  for path, content in files.items()]}, ensure_ascii=False)


class StepwiseProjectTests(unittest.TestCase):
    def test_human_plan_precedes_first_model_call_and_is_bounded(self):
        printed=[]
        requests=[]
        def generate(prompt, language):
            requests.append(prompt)
            self.assertGreater(len(printed),0)
            if "Phase 1/3:" in prompt:
                return proposal({"app.py": "def calculate(a,b): return a+b\n"})
            if "Phase 2/3:" in prompt:
                return proposal({"README.md": "# Arithmetic project\n"})
            if "Phase 3/3:" in prompt:
                return proposal({"tests/test_app.py":
                    "import unittest\n"
                    "class AppTests(unittest.TestCase):\n"
                    "    def test_ok(self): self.assertTrue(True)\n"})
            self.fail("Unexpected request: "+prompt[:90])
        result=build_complete_project(
            "Напиши калькулятор", "python", generator=generate,
            stepwise=True,progress=printed.append)
        self.assertTrue(result.verified)
        self.assertEqual(len(requests),3)
        self.assertIn("ПЛАН JARVIS",printed[0])
        self.assertIn("1/4 Архитектура",printed[0])
        self.assertIn("4/4",printed[0])
        self.assertEqual([a.status for a in result.attempts],
                         ["passed","passed","passed","passed"])
        self.assertTrue(all(
            "Шаг "+str(i)+"/4" in result.attempts[i-1].diagnostics
            for i in range(1,5)))
        self.assertTrue(any("все файлы вместе" in p.lower()
                            for p in printed))

    def test_bad_second_phase_is_fixed_before_third_phase(self):
        calls=[]
        def generator(prompt,language):
            calls.append(prompt)
            if "Phase 1/3" in prompt:
                return proposal({"app.py": "def start(): return 1\n"})
            if "Phase 2/3" in prompt:
                if "REJECTED PHASE RESPONSE" not in prompt:
                    return proposal({"app.py": "def broken(:\n  pass\n"})
                self.assertIn("Проверка этапа не пройдена",prompt)
                return proposal({"app.py": "def start(): return 2\n"})
            if "Phase 3/3" in prompt:
                self.assertEqual(len(calls),4)
                return proposal({"README.md": "# Verified code\n"})
            self.fail("Unexpected model call")
        status=[]
        result=build_complete_project(
            "Сделай приложение", "python", generator=generator,
            stepwise=True,progress=status.append)
        self.assertTrue(result.verified)
        self.assertEqual(len(calls),4)
        self.assertIn("повторов: 1",result.attempts[1].diagnostics)
        self.assertIn("return 2",next(
            item.content for item in result.plan.files
            if item.path=="app.py"))
        self.assertTrue(any("Шаг 2/4: проверен" in s for s in status))

    def test_three_invalid_first_steps_stop_execution_before_next_step(self):
        generated=[]
        def generator(prompt,language):
            generated.append(prompt)
            self.assertIn("Phase 1/3",prompt)
            return proposal({"app.py":"def broken(:\n"})
        with tempfile.TemporaryDirectory() as d:
            destination=Path(d)
            with self.assertRaisesRegex(WorkspaceError,"трижды"):
                build_complete_project("Напиши код","python",
                                      generator=generator,
                                      stepwise=True)
            self.assertEqual(len(generated),3)
            self.assertEqual(list(destination.iterdir()),[])

    def test_final_integrated_check_is_additional_and_gates_writes(self):
        calls=[]
        def generator(prompt,language):
            calls.append(prompt)
            if "Phase 1/3" in prompt:
                return proposal({"app.py":"def a(): return 1\n"})
            if "Phase 2/3" in prompt:
                return proposal({"lib.py":"def b(): return 2\n"})
            return proposal({"README.md":"# Combined project\n"})
        real_checker={"status":"passed","reason":"Python AST parse only"}
        failed_checker={"status":"failed","reason":"Whole-project gate failed"}
        with mock.patch("code_project_engine.check_project",
                        side_effect=[
                            real_checker,real_checker,real_checker,failed_checker
                        ]) as check:
            result=build_complete_project(
                "Напиши код","python",generator=generator,
                stepwise=True,repair_rounds=0)
        self.assertEqual(check.call_count,4)
        self.assertFalse(result.verified)
        self.assertEqual(result.attempts[-1].status,"failed")
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaises(WorkspaceError):
                install_reviewed(result,root,confirmed=True)
            self.assertEqual(list(root.iterdir()),[])

    def test_generated_code_is_parsed_but_never_run_on_host(self):
        with tempfile.TemporaryDirectory() as d:
            flag=Path(d)/"danger.flag"
            malicious="from pathlib import Path\nPath("+repr(str(flag))+").write_text('BAD')\n"
            def generator(prompt,language):
                if "Phase 1/3" in prompt:
                    return proposal({"app.py":malicious})
                if "Phase 2/3" in prompt:
                    return proposal({"README.md":"# No execution\n"})
                return proposal({"tests/test_app.py":
                    "import unittest\nclass T(unittest.TestCase):\n"
                    "    def test_example(self): self.assertTrue(True)\n"})
            result=build_complete_project(
                "Write harmless files", "python",
                generator=generator,stepwise=True)
            self.assertTrue(result.verified)
            self.assertFalse(flag.exists())
            self.assertFalse(list(Path(d).iterdir()))

    def test_other_languages_are_only_partially_checked_at_each_step(self):
        seen=[]
        def generator(prompt,language):
            seen.append(prompt)
            if "Phase 1/3" in prompt:
                return proposal({"index.html":"<html>Hi</html>"},"html")
            if "Phase 2/3" in prompt:
                if "REJECTED PHASE RESPONSE" not in prompt:
                    return proposal({"style.css":"body { color: black;"},"html")
                return proposal({"style.css":"body { color: black; }"},"html")
            return proposal({"README.md":"# HTML site\n"},"html")
        result=build_complete_project(
            "Website","html",generator=generator,stepwise=True)
        self.assertEqual([x.status for x in result.attempts[:3]],
                         ["partial","partial","partial"])
        self.assertEqual(len(seen),4)
        self.assertEqual(result.attempts[-1].status,"partial")
        self.assertFalse(result.verified)

    def test_only_explicit_options_are_accepted(self):
        for kwargs in ({"stepwise":"yes"}, {"stepwise":True,"progress":43}):
            with self.subTest(kwargs=kwargs),self.assertRaises(WorkspaceError):
                build_complete_project(
                    "Demo","python",
                    generator=lambda *_:self.fail("Should not request model"),
                    **kwargs)
        self.assertIn("4/4",describe_execution_plan("Demo","python"))

    def test_code_window_uses_stepwise_engine_and_reports_progress(self):
        from code_gui import CodeWindow
        view=mock.Mock()
        view._target.return_value=Path("C:/Temp/SafeProject")
        view.language.get.return_value="html"
        view.task.get.return_value="Build UI"
        view.modify_existing.get.return_value=False
        view.full_project.get.return_value=True
        view._generation_busy=False
        view.master.engine="bundled"
        view.master._local_model_ready=True
        with mock.patch("code_gui.threading.Thread") as thread, \
             mock.patch("code_gui.build_one_shot_project") as build, \
             mock.patch("code_gui.messagebox.askyesno",return_value=True):
            CodeWindow.generate(view)
            self.assertIn("ПЛАН JARVIS",view.show.call_args.args[0])
            thread.assert_called_once()
            thread.call_args.kwargs["target"]()
            kwargs=build.call_args.kwargs
            self.assertIs(kwargs["stepwise"],True)
            self.assertTrue(callable(kwargs["progress"]))
            kwargs["progress"]("Шаг 1/4: проверен")
            callback=view._on_ui.call_args.args[0]
            callback()
            view._append_plan_progress.assert_called_with("Шаг 1/4: проверен")
        view.log=mock.Mock()
        view.winfo_exists.return_value=True
        CodeWindow._append_plan_progress(view,"Шаг 1/4: проверен")
        view.log.insert.assert_called_once()


if __name__=="__main__":
    unittest.main()
