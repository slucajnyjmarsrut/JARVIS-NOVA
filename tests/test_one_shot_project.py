# -*- coding: utf-8 -*-
"""One submission builds a complete project, self-checks, and self-repairs."""
import json
from pathlib import Path
import tempfile
import unittest

from code_project_engine import build_one_shot_project
from code_test_sandbox import TestGateReport
from code_autopilot import install_reviewed
from code_workspace import WorkspaceError


def offer(files,language="python"):
    return json.dumps({"language":language,"files":[
        {"path":path,"content":contents} for path,contents in files.items()
    ]})


class OneShotCodingTests(unittest.TestCase):
    def model(self,requests):
        def generate(request,language):
            requests.append((request,language))
            if "Phase 1/3" in request:
                return offer({"app.py":"def calculate(a,b): return a-b\n",
                              "README.md":"# Calculator\n"})
            if "Phase 2/3" in request:
                return offer({"app.py":"def calculate(a,b): return a-b\n"})
            if "Phase 3/3" in request:
                return offer({"tests/test_app.py":
                    "import unittest\nfrom app import calculate\n"
                    "class CalculatorTests(unittest.TestCase):\n"
                    "    def test_sum(self):\n"
                    "        self.assertEqual(calculate(2,3),5)\n"})
            if "Repair Python project" in request:
                return offer({"app.py":"def calculate(a,b): return a+b\n"})
            raise AssertionError("Unexpected model prompt: "+request[:90])
        return generate

    def test_one_request_generates_tests_repairs_and_keeps_workspace_untouched(self):
        requests=[]
        folders=[]
        def runner(root,*,confirmed):
            self.assertTrue(confirmed)
            root=Path(root)
            folders.append(root)
            self.assertTrue((root/"tests"/"test_app.py").exists())
            source=(root/"app.py").read_text()
            return (TestGateReport("passed",1,"Ran 1 test in 0.01s OK",3)
                    if "a+b" in source else
                    TestGateReport("failed",1,"Ran 1 test in 0.01s FAILED",3))
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)
            result=build_one_shot_project(
                "Create a calculator", "python",generator=self.model(requests),
                allow_sandbox_tests=True,test_runner=runner)
            self.assertTrue(result.verified)
            self.assertEqual([entry.status for entry in result.attempts[-2:]],
                             ["failed","passed"])
            self.assertEqual(len(requests),4)
            self.assertEqual(list(target.iterdir()),[])
            self.assertFalse(any(path.exists() for path in folders))
            with self.assertRaises(PermissionError):
                install_reviewed(result,target)
            installed=install_reviewed(result,target,confirmed=True)
            self.assertEqual(len(installed),3)
            self.assertIn("a+b",(target/"app.py").read_text())
            self.assertIn("assertEqual",(target/"tests"/"test_app.py").read_text())

    def test_denied_sandbox_never_runs_generated_code(self):
        calls=[]
        result=build_one_shot_project(
            "Create a calculator","python",generator=self.model(calls),
            allow_sandbox_tests=False,
            test_runner=lambda *a,**kw:self.fail("No run permission"))
        self.assertTrue(result.verified)  # Syntax only, no functional claim.
        self.assertEqual(len(calls),3)
        self.assertFalse(any("Docker" in t.diagnostics for t in result.attempts))

    def test_blocked_docker_cannot_be_reported_as_working(self):
        requests=[]
        def runner(root,*,confirmed):
            return TestGateReport("skipped",0,"Docker not available",3)
        result=build_one_shot_project(
            "Create a calculator","python",generator=self.model(requests),
            allow_sandbox_tests=True,test_runner=runner)
        self.assertFalse(result.verified)
        self.assertEqual(result.attempts[-1].status,"skipped")
        self.assertEqual(len(requests),3)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(WorkspaceError):
                install_reviewed(result,Path(temp),confirmed=True)

    def test_static_only_for_other_languages_does_not_run_python_tests(self):
        calls=[]
        def model(prompt,language):
            calls.append(prompt)
            if "Phase 1/3" in prompt:
                return offer({"index.html":"<!doctype html><html></html>"},language="html")
            if "Phase 2/3" in prompt:
                return offer({"style.css":"body {color: black;}"},language="html")
            return offer({"README.md":"# Website"},language="html")
        result=build_one_shot_project(
            "Build a site","html",generator=model,
            allow_sandbox_tests=True,
            test_runner=lambda *a,**kw:self.fail("Python runner for HTML"))
        self.assertEqual(len(calls),3)
        self.assertEqual(result.plan.language,"html")
        self.assertFalse(any("Docker" in a.diagnostics for a in result.attempts))


if __name__=="__main__":
    unittest.main()
