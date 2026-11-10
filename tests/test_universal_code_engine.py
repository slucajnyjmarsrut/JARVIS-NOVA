# -*- coding: utf-8 -*-
"""Universal project construction tests; no generated code is ever executed."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from code_languages import SUPPORTED, EXTENSIONS
from code_workspace import (starter_project, preview, apply_plan,
                            WorkspaceError, ChangePlan, ProposedFile)
from code_checks import check_project
from code_project_engine import build_complete_project
from code_autopilot import install_reviewed


def proposal(language,files):
    return json.dumps({"language":language,
                       "files":[{"path":p,"content":c} for p,c in files.items()]})


class UniversalCodingTests(unittest.TestCase):
    def test_twenty_supported_languages_have_starters(self):
        self.assertEqual(len(SUPPORTED),20)
        self.assertTrue({"java","luau","python","javascript","typescript",
                         "cpp","csharp","rust","go","php","ruby","kotlin",
                         "swift","dart","html","css","sql","bash","c","lua"}
                        .issubset(SUPPORTED))
        for language in sorted(SUPPORTED):
            with self.subTest(language=language),tempfile.TemporaryDirectory() as tmp:
                plan=starter_project(language,"ExampleProject")
                self.assertEqual(plan.language,language)
                self.assertGreaterEqual(len(plan.files),2)
                changes=preview(plan,Path(tmp))
                self.assertTrue(all(item["action"]=="create" for item in changes))
                with self.assertRaises(PermissionError):
                    apply_plan(plan,Path(tmp),confirmed=False)
                written=apply_plan(plan,Path(tmp),confirmed=True)
                self.assertEqual(len(written),len(plan.files))
                result=check_project(language,Path(tmp))
                self.assertIn(result["status"],("passed","partial"), f"{language}: {result}")
                self.assertTrue((Path(tmp)/"README.md").is_file())

    def test_busy_rustfmt_timeout_is_unverified_not_false_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"main.rs").write_text("fn main() {}\n",encoding="utf-8")
            with mock.patch("code_checks.shutil.which",return_value="rustfmt"), \
                 mock.patch("code_checks._syntax_process",
                            return_value="Превышено время проверки"):
                result=check_project("rust",root)
            self.assertEqual(result["status"],"partial")
            self.assertEqual(result["verification"],"structure_only")
            self.assertIn("не подтверждён",result["reason"])

    def test_python_real_ast_rejects_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"app.py").write_text("def broken(:\n    pass\n",encoding="utf-8")
            result=check_project("python",root)
            self.assertEqual(result["status"],"failed")
            (root/"app.py").write_text("def working():\n    return 42\n",encoding="utf-8")
            result=check_project("python",root)
            self.assertEqual(result["status"],"passed")
            self.assertEqual(result["verification"],"syntax_only")

    def test_generated_shell_file_never_executed_by_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            flag=root/"executed.flag"
            code=f'echo danger > "{flag}"\n'
            (root/"main.sh").write_text(code,encoding="utf-8")
            result=check_project("bash",root)
            self.assertIn(result["status"],("passed","partial"))
            self.assertFalse(flag.exists(), "Generated script must never execute")

    def test_full_project_three_phases_with_review_and_confirmation(self):
        calls=[]
        def model(task,language):
            calls.append(task)
            if "Phase 1/3:" in task:
                return proposal(language,{"src/app.py":"def greet():\n    return 'hello'\n",
                    "README.md":"# Demo\n"})
            if "Phase 2/3:" in task:
                return proposal(language,{"src/app.py":"def greet(name='world'):\n    return 'hello '+name\n",
                    "src/service.py":"from .app import greet\n"})
            return proposal(language,{"tests/test_app.py":"def test_greet():\n    assert True\n",
                              "README.md":"# Demo\n\nRun unit tests manually.\n"})
        result=build_complete_project("Create a Python application",
            "python",generator=model)
        self.assertEqual(len(calls),3)
        self.assertTrue(result.verified)
        self.assertEqual(result.attempts[-1].status,"passed")
        self.assertEqual(len(result.plan.files),4)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(list(root.iterdir()),[])
            with self.assertRaises(PermissionError):
                install_reviewed(result,root)
            self.assertEqual(list(root.iterdir()),[])
            paths=install_reviewed(result,root,confirmed=True)
            self.assertEqual(len(paths),4)
            self.assertIn("hello", (root/"src/app.py").read_text())
            self.assertTrue((root/"tests/test_app.py").exists())

    def test_compiler_diagnostic_triggers_repair(self):
        calls=[]
        def model(task,language):
            calls.append(task)
            if "Repair the COMPLETE" in task:
                return proposal(language,{"main.py":"def main():\n    return 3\n"})
            if "Phase 1/3:" in task:
                return proposal(language,{"main.py":"def main():\n    return 1\n"})
            if "Phase 2/3:" in task:
                return proposal(language,{"main.py":"def broken(:\n  pass\n"})
            return proposal(language,{"README.md":"# Broken source to be fixed\n"})
        result=build_complete_project("Build robust Python tool",
            "python",generator=model,repair_rounds=2)
        self.assertTrue(result.verified)
        self.assertEqual(len(calls),4)
        self.assertIn("Repair the COMPLETE",calls[-1])
        self.assertIn("return 3",next(x.content for x in result.plan.files
                                      if x.path=="main.py"))

    def test_failed_projects_never_install(self):
        def bad(task,language):
            return proposal(language,{"main.py":"def broken(:\n"})
        result=build_complete_project("Build an app","python",
                                       generator=bad,repair_rounds=1)
        self.assertFalse(result.verified)
        self.assertEqual(result.attempts[-1].status,"failed")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(WorkspaceError):
                install_reviewed(result,root,confirmed=True)
            self.assertEqual(list(root.iterdir()),[])

    def test_existing_python_project_is_not_rewritten_before_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            target=root/"main.py"
            target.write_text("print('original')\n",encoding="utf-8")
            def generator(task,language):
                return proposal(language,{"main.py":"print('updated')\n"})
            result=build_complete_project("Update printing",
                "python",generator=generator,workspace=root)
            self.assertTrue(result.verified)
            self.assertEqual(target.read_text(),"print('original')\n")
            target.write_text("print('concurrent edit')\n",encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                install_reviewed(result,root,confirmed=True)
            self.assertEqual(target.read_text(),"print('concurrent edit')\n")

    def test_no_shell_or_dependency_install_in_check_module(self):
        source=(Path(__file__).resolve().parents[1]/"code_checks.py"
                ).read_text(encoding="utf-8")
        self.assertIn("shell=False",source)
        for unsafe in ("pip install","npm install","cargo build",
                       "dotnet build","pytest.main("):
            self.assertNotIn(unsafe,source)

    def test_disallowed_file_types_cannot_be_smuggled(self):
        with tempfile.TemporaryDirectory() as tmp:
            for language in SUPPORTED:
                with self.subTest(lang=language),self.assertRaises(WorkspaceError):
                    preview(ChangePlan(language,(
                        ProposedFile("run.exe","MZ"),)),Path(tmp))

if __name__=="__main__":
    unittest.main()
