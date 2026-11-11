# -*- coding: utf-8 -*-
"""Real offline Docker acceptance of JARVIS autonomous coding pipeline.

The generator is deterministic on purpose: this verifies REAL Docker tests,
automatic failure-driven code repair and consented save without pretending
that a language model wrote a complex commercial project. No generated
Python is executed on the host, network is off inside the container.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from code_project_engine import build_one_shot_project
from code_autosave_policy import save_approved_one_shot
from code_test_sandbox import run_python_tests, IMAGE
from code_workspace import WorkspaceError


def _proposal(files):
    return json.dumps({"language":"python","files":[
        {"path":p,"content":code} for p,code in files.items()
    ]})


def generator(prompt, language):
    if language!="python":
        raise RuntimeError("Unexpected language.")
    if "Phase 1/3" in prompt:
        return _proposal({
            "app.py":"def calculate(a,b):\n    return a-b\n",
            "README.md":"# Calculator\nLocal CLI-less library.\n",
        })
    if "Phase 2/3" in prompt:
        return _proposal({"app.py":"def calculate(a,b):\n    return a-b\n"})
    if "Phase 3/3" in prompt:
        return _proposal({"tests/test_calculator.py":
            "import unittest\nfrom app import calculate\n"
            "class CalculatorTests(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(calculate(1,2),3)\n"})
    if "INDEPENDENT ACCEPTANCE TESTS" in prompt:
        return _proposal({"tests/test_acceptance_calculator.py":
            "import unittest\nfrom app import calculate\n"
            "class AcceptanceTests(unittest.TestCase):\n"
            "    def test_positive(self):\n"
            "        self.assertEqual(calculate(2,3),5)\n"
            "    def test_negative(self):\n"
            "        self.assertEqual(calculate(-4,1),-3)\n"})
    if "Repair Python project" in prompt:
        if "failed" not in prompt.lower() and "FAIL" not in prompt:
            raise RuntimeError("No real test failure fed back to the model.")
        return _proposal({"app.py":"def calculate(a,b):\n    return a+b\n"})
    raise RuntimeError("Unexpected generation phase: "+prompt[:100])


def main() -> int:
    try:
        if not shutil.which("docker"):
            raise RuntimeError("This acceptance test needs an installed Docker CLI.")
        with tempfile.TemporaryDirectory(prefix="nova-autocoder-real-") as td:
            home=Path(td)
            result=build_one_shot_project(
                "Create a Python calculator adding signed integers",
                "python",generator=generator,
                allow_sandbox_tests=True,
                test_runner=run_python_tests,
                max_test_repairs=3,
            )
            docker=[step for step in result.attempts if "Docker:" in step.diagnostics]
            statuses=[step.status for step in docker]
            if not (result.verified and statuses==["failed","passed"]):
                raise RuntimeError("Docker repair was not actually performed: "
                                   +str(statuses)+" "+repr(docker[-2:]))
            target=home/"JARVIS-NOVA-Projects"/"Project-1234abcd"
            if target.exists():
                raise RuntimeError("Target unexpectedly already exists.")
            try:
                save_approved_one_shot(result,target,home=home)
            except PermissionError:
                pass
            else:
                raise RuntimeError("Autonomous save skipped explicit permission.")
            written=save_approved_one_shot(
                result,target,authorized=True,home=home)
            if len(written)!=4 or "a+b" not in (target/"app.py").read_text():
                raise RuntimeError("Verified project was not installed correctly.")
            if not (target/"tests"/"test_acceptance_calculator.py").is_file():
                raise RuntimeError("Independent tests were removed during repair.")
            try:
                save_approved_one_shot(
                    result,target,authorized=True,home=home)
            except WorkspaceError:
                pass
            else:
                raise RuntimeError("One-shot workflow overwrote an existing project.")
        print("REAL DOCKER AUTOCODER PASS: first tests failed, source repaired, "
              "independent tests passed, consented save; no host execution.",
              flush=True)
        return 0
    except Exception as exc:
        print("REAL DOCKER AUTOCODER FAIL: "+
              type(exc).__name__+": "+str(exc),
              file=sys.stderr,flush=True)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
