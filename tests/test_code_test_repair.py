# -*- coding: utf-8 -*-
"""Never apply generated fixes until isolated tests and user approval."""
import json
import tempfile
import unittest
from pathlib import Path

from code_test_repair import repair_after_tests
from code_test_sandbox import TestGateReport
from code_workspace import ChangePlan, ProposedFile, WorkspaceError


def example(code="def add(a,b): return a-b\n"):
    return ChangePlan("python", (
        ProposedFile("app.py",code),
        ProposedFile("tests/test_app.py",
            "import unittest\nfrom app import add\n"
            "class Checks(unittest.TestCase):\n"
            "    def test_add(self): self.assertEqual(add(2,3),5)\n"),
        ProposedFile("README.md","# Calculator\n"),
    ))


class SafeTestRepairTests(unittest.TestCase):
    def test_requires_consent_before_any_execution(self):
        def deny(*args,**kwargs):
            self.fail("No test or generation permitted without consent")
        with self.assertRaises(PermissionError):
            repair_after_tests(
                "fix math",example(),confirmed=False,
                generator=deny,runner=deny)

    def test_failed_then_repaired_passes_only_repaired_staged_copy(self):
        workspaces=[]
        prompts=[]
        def runner(root,*,confirmed):
            self.assertTrue(confirmed)
            root=Path(root)
            self.assertTrue((root/"tests/test_app.py").exists())
            workspaces.append(root)
            content=(root/"app.py").read_text(encoding="utf-8")
            if "a-b" in content:
                return TestGateReport(
                    "failed",1,"Ran 1 test in 0.01s\nFAILED (failures=1)",3)
            return TestGateReport(
                "passed",1,"Ran 1 test in 0.01s\nOK",3)
        def generator(prompt, language):
            self.assertEqual(language,"python")
            prompts.append(prompt)
            return json.dumps({"language":"python","files":[{
                "path":"app.py","content":"def add(a,b): return a+b\n"
            }]})
        before=example()
        result=repair_after_tests(
            "make add pass",before,generator=generator,
            runner=runner,confirmed=True)
        self.assertTrue(result.success)
        self.assertEqual([x.status for x in result.steps],["failed","passed"])
        self.assertEqual(result.steps[-1].tests_run,1)
        self.assertEqual(len(prompts),1)
        files_after={item.path:item.content for item in result.plan.files}
        files_before={item.path:item.content for item in before.files}
        self.assertEqual(files_after["app.py"],"def add(a,b): return a+b\n")
        self.assertEqual(files_before["app.py"],"def add(a,b): return a-b\n")
        self.assertFalse(any(path.exists() for path in workspaces))

    def test_missing_docker_stops_without_model_patching(self):
        calls=[]
        def runner(root,*,confirmed):
            calls.append("runner")
            return TestGateReport("skipped",0,"Docker unavailable",3)
        def generator(*args):
            self.fail("A missing Docker image is not evidence code is broken")
        result=repair_after_tests(
            "add",example(),confirmed=True,runner=runner,generator=generator)
        self.assertFalse(result.success)
        self.assertEqual(result.steps[0].status,"skipped")
        self.assertEqual(calls,["runner"])

    def test_static_risk_blocks_container_test_execution(self):
        project=example("import os\ndef risky(): os.system('hello')\n")
        def forbidden(*args,**kwargs):
            self.fail("Unsafe project should be held for manual review")
        result=repair_after_tests(
            "fix",project,confirmed=True,runner=forbidden,generator=forbidden)
        self.assertEqual(result.steps[0].status,"blocked")
        self.assertFalse(result.success)

    def test_two_repairs_max_and_all_fail_not_marked_success(self):
        count=[]
        def runner(root,*,confirmed):
            return TestGateReport("failed",1,"Ran 1 test in 0.01s\nFAILED",3)
        def generator(prompt, language):
            count.append(prompt)
            return json.dumps({"language":"python","files":[{
                "path":"app.py","content":"def add(a,b): return a-b\n"
            }]})
        result=repair_after_tests(
            "fix",example(),confirmed=True,runner=runner,
            generator=generator,max_repairs=2)
        self.assertFalse(result.success)
        self.assertEqual(len(result.steps),3)
        self.assertEqual(len(count),2)

    def test_model_cannot_weaken_or_replace_tests(self):
        seen=[]
        def runner(root,*,confirmed):
            seen.append((Path(root)/"tests/test_app.py").read_text(
                encoding="utf-8"))
            return TestGateReport("failed",1,"Ran 1 test in 0.01s\nFAILED",3)
        for path in ("tests/test_app.py","tests/helpers.py",
                     "src/tests/test_hidden.py","test_app.py"):
            with self.subTest(path=path):
                patch=json.dumps({"language":"python","files":[{
                    "path":path,
                    "content":"import unittest\nclass Tests(unittest.TestCase): pass\n",
                }]})
                with self.assertRaisesRegex(WorkspaceError,
                                            "не может изменять тесты"):
                    repair_after_tests(
                        "fix",example(),confirmed=True,runner=runner,
                        generator=lambda *args: patch,max_repairs=1)
        self.assertEqual(len(seen),4)
        self.assertTrue(all("self.assertEqual(add(2,3),5)" in x
                            for x in seen))

    def test_generated_malicious_paths_and_languages_rejected(self):
        def fail_test(root,*,confirmed):
            return TestGateReport("failed",1,"Ran 1 test in 0.01s\nFAILED",3)
        for malicious in (
            {"language":"python","files":[{"path":"../secrets.py",
                                            "content":"print(1)"}]},
            {"language":"java","files":[{"path":"Main.java","content":"class Main {}"}]},
        ):
            with self.subTest(malicious=malicious):
                with self.assertRaises(WorkspaceError):
                    repair_after_tests(
                        "fix",example(),confirmed=True,runner=fail_test,
                        generator=lambda *_: json.dumps(malicious))
    
    def test_no_tests_reported_success_with_zero_count_is_rejected(self):
        def falsely_successful(root,*,confirmed):
            return TestGateReport("passed",0,"Ran 0 tests\nOK",3)
        def generated(prompt, language):
            return json.dumps({"language":"python","files":[{
                "path":"app.py","content":"def add(a,b): return a+b\n"}]})
        result=repair_after_tests(
            "fix",example(),confirmed=True,runner=falsely_successful,
            generator=generated,max_repairs=1)
        self.assertFalse(result.success)
        self.assertEqual(result.steps[-1].status,"failed")
