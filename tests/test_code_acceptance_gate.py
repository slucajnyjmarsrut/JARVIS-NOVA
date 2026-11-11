# -*- coding: utf-8 -*-
"""Independent Python acceptance checks fail closed and never weaken test oracles."""
import unittest
from code_acceptance_gate import validate_acceptance, independent_acceptance_tests
from code_workspace import ChangePlan, ProposedFile, WorkspaceError


def plan(body):
    return ChangePlan("python", (ProposedFile(
        "tests/test_acceptance_api.py",body),))


OK = (
    "import unittest\nfrom app import add\n"
    "class BlackBox(unittest.TestCase):\n"
    "    def test_example(self):\n"
    "        self.assertEqual(add(2,3),5)\n"
    "    def test_negative(self):\n"
    "        self.assertEqual(add(-3,1),-2)\n"
)


class IndependentAcceptanceTests(unittest.TestCase):
    def test_two_real_behavioral_assertions(self):
        self.assertEqual(validate_acceptance(plan(OK)).language,"python")

    def test_fake_success_and_missing_tests_are_rejected(self):
        bad=(
            "import unittest\nclass Tests(unittest.TestCase):\n"
            " def test_one(self): self.assertTrue(True)\n"
            " def test_two(self): self.assertEqual(1,1)\n"
        )
        for item in ("",bad,OK.replace("def test_negative","def helper")):
            with self.subTest(length=len(item)),self.assertRaises(WorkspaceError):
                validate_acceptance(plan(item))

    def test_dangerous_imports_or_file_writes_never_pass(self):
        for bad in (
            OK+"\nimport subprocess\n",
            OK+"\nfrom os import system\n",
            OK+"\nopen('secrets.txt','w')\n",
            OK.replace("from app import add","from socket import add"),
        ):
            with self.subTest(bad=bad[-45:]),self.assertRaises(WorkspaceError):
                validate_acceptance(plan(bad))

    def test_acceptance_prompt_has_only_original_task(self):
        def make_tests(prompt,language):
            self.assertEqual(language,"python")
            self.assertIn("my calculator",prompt)
            self.assertNotIn("def add(a,b)",prompt)
            return '{"language":"python","files":[{"path":"tests/test_acceptance_api.py",'+\
                   '"content":'+__import__("json").dumps(OK)+'}]}'
        suite=independent_acceptance_tests("my calculator",generator=make_tests)
        self.assertEqual(len(suite.files),1)
        self.assertEqual(suite.files[0].content,OK)


if __name__=="__main__":
    unittest.main()
