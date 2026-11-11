# -*- coding: utf-8 -*-
"""Mutation acceptance must use independent tests, never edit real files."""
from pathlib import Path
import tempfile
import unittest

from code_mutation_gate import acceptance_mutant, verify_independent_tests
from code_test_sandbox import TestGateReport
from code_workspace import ChangePlan, ProposedFile, WorkspaceError


def project():
    return ChangePlan("python",(
        ProposedFile("calculator.py","def add(a,b):\n    return a+b\n"),
        ProposedFile("tests/test_generated.py",
            "import unittest\nfrom calculator import add\n"
            "class Fake(unittest.TestCase):\n"
            " def test_pass(self): self.assertTrue(True)\n"),
        ProposedFile("tests/test_acceptance_calculator.py",
            "import unittest\nfrom calculator import add\n"
            "class Acceptance(unittest.TestCase):\n"
            " def test_positive(self): self.assertEqual(add(2,3),5)\n"
            " def test_negative(self): self.assertEqual(add(-2,1),-1)\n"),
    ))


class MutationAcceptanceTests(unittest.TestCase):
    def test_mutation_breaks_code_not_tests_or_original(self):
        plan=project()
        before=plan.files[0].content
        mutant,target=acceptance_mutant(plan)
        self.assertEqual(target,"calculator.py:add")
        self.assertIn("return None",mutant.files[0].content)
        self.assertEqual(plan.files[0].content,before)
        self.assertEqual(len(mutant.files),2)
        self.assertNotIn("test_generated",repr(mutant.files))
        self.assertEqual(mutant.files[-1].content,plan.files[-1].content)

    def test_only_failed_real_assertions_certify_mutation(self):
        calls=[]
        def runner(root,*,confirmed):
            self.assertTrue(confirmed)
            self.assertFalse((Path(root)/"tests"/"test_generated.py").exists())
            self.assertTrue((Path(root)/"tests"/"test_acceptance_calculator.py").is_file())
            self.assertIn("return None",(Path(root)/"calculator.py").read_text())
            calls.append(root)
            return TestGateReport(
                "failed",2,
                "FAIL: test_positive (tests.test_acceptance_calculator)\n"
                "AssertionError: None != 5",2)
        r=verify_independent_tests(project(),runner=runner,confirmed=True)
        self.assertTrue(r.detected)
        self.assertEqual(r.cases,2)
        self.assertEqual(len(calls),1)
        self.assertFalse(calls[0].exists())

    def test_infrastructure_errors_do_not_count_as_test_mutation(self):
        verdict=verify_independent_tests(
            project(),confirmed=True,
            runner=lambda *a,**k:TestGateReport(
                "failed",2,"ERROR: test_import\nImportError: missing",2))
        self.assertFalse(verdict.detected)

    def test_trivial_or_crashing_tests_cannot_claim_mutation_detected(self):
        for status,count in (("passed",2),("failed",0),("skipped",0)):
            with self.subTest(status=status):
                result=verify_independent_tests(
                    project(),confirmed=True,
                    runner=lambda *a,**kw:TestGateReport(
                        status,count,"test output",2))
                self.assertFalse(result.detected)

    def test_consent_required_even_for_mutation(self):
        with self.assertRaises(PermissionError):
            verify_independent_tests(
                project(),runner=lambda *a,**k:self.fail("No execution"))

    def test_class_method_can_be_mutated_without_changing_class_name(self):
        original=ChangePlan("python",(
            ProposedFile("service.py",
                "class Service:\n    def compute(self,n):\n"
                "        return n*n\n"),
            ProposedFile("tests/test_acceptance_service.py",
                "import unittest\nfrom service import Service\n"
                "class Tests(unittest.TestCase):\n"
                " def test_a(self): self.assertEqual(Service().compute(3),9)\n"
                " def test_b(self): self.assertEqual(Service().compute(4),16)\n")
        ))
        mutant,target=acceptance_mutant(original)
        self.assertEqual(target,"service.py:Service.compute")
        self.assertIn("return None",mutant.files[0].content)
        self.assertNotIn("return None",original.files[0].content)

    def test_no_source_function_never_passes(self):
        with self.assertRaises(WorkspaceError):
            acceptance_mutant(ChangePlan("python",(
                ProposedFile("data.py","ANSWER=42\n"),
                ProposedFile("tests/test_acceptance_data.py",
                    "import unittest\nfrom data import ANSWER\n"
                    "class Tests(unittest.TestCase):\n"
                    " def test_a(self): self.assertEqual(ANSWER,42)\n"
                    " def test_b(self): self.assertTrue(ANSWER>0)\n"),
            )))


if __name__=="__main__":
    unittest.main()
