# -*- coding: utf-8 -*-
"""Real-model code acceptance never executes generated Python on the host."""
from pathlib import Path
import tempfile
import unittest

from code_workspace import ChangePlan, ProposedFile, parse_model_proposal
from scripts.verify_real_qwen_coding_e2e import _assert_small_real_project


def valid_plan():
    return ChangePlan("python",(
        ProposedFile("calculator.py",
            "def add(a,b):\n    return a+b\n\n"
            "def subtract(a,b):\n    return a-b\n"),
        ProposedFile("tests/test_calculator.py",
            "import unittest\nfrom calculator import add, subtract\n"
            "class CalculatorTests(unittest.TestCase):\n"
            "    def test_positive(self):\n"
            "        self.assertEqual(add(2,3),5)\n"
            "    def test_negative(self):\n"
            "        self.assertEqual(subtract(1,4),-3)\n"),
        ProposedFile("README.md",
            "# Calculator\nA small project with tested addition and subtraction."),
    ))


class RealQwenCodingContractTests(unittest.TestCase):
    def test_static_acceptance_reads_real_source_but_never_runs_it(self):
        with tempfile.TemporaryDirectory() as td:
            count,cases=_assert_small_real_project(valid_plan(),Path(td))
            self.assertEqual(count,3)
            self.assertEqual(cases,2)
            self.assertTrue((Path(td)/"calculator.py").is_file())

    def test_wrong_implementation_is_rejected_before_writing_files(self):
        bad=list(valid_plan().files)
        bad[0]=ProposedFile("calculator.py",
            "def add(a,b):\n    return a-b\n"
            "def subtract(a,b):\n    return a+b\n")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError,"static contract"):
                _assert_small_real_project(
                    ChangePlan("python",tuple(bad)),Path(td))
            self.assertEqual(list(Path(td).iterdir()),[])

    def test_bogus_tests_cannot_pass_contract(self):
        bad=list(valid_plan().files)
        bad[1]=ProposedFile("tests/test_calculator.py",
            "import unittest\n"
            "class Fake(unittest.TestCase):\n"
            "    def test_a(self): pass\n"
            "    def test_b(self): pass\n")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError,"two real assertions"):
                _assert_small_real_project(
                    ChangePlan("python",tuple(bad)),Path(td))

    def test_json_shape_blocks_path_traversal_as_before(self):
        import json
        raw=json.dumps({"language":"python","files":[
            {"path":"../../private.py","content":"print(1)"}
        ]})
        with self.assertRaises(ValueError):
            parse_model_proposal(raw)

    def test_empty_readme_does_not_count_as_project(self):
        bad=list(valid_plan().files)
        bad[2]=ProposedFile("README.md","# No")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError,"README"):
                _assert_small_real_project(
                    ChangePlan("python",tuple(bad)),Path(td))


if __name__=="__main__":
    unittest.main()
