# -*- coding: utf-8 -*-
"""AST review checks risks without executing model-generated code."""
import unittest
import tempfile
from pathlib import Path

from code_quality_review import review_change_plan, unified_plan_diff
from code_workspace import ChangePlan, ProposedFile


def plan(source: str, *, tests=True, readme=True):
    files=[ProposedFile("app.py",source)]
    if tests:
        files.append(ProposedFile(
            "tests/test_app.py","import unittest\n"
            "class Checks(unittest.TestCase):\n"
            "    def test_smoke(self): self.assertTrue(True)\n"))
    if readme:
        files.append(ProposedFile("README.md","# Application\n"))
    return ChangePlan("python",tuple(files))


class StaticCodeReviewTests(unittest.TestCase):
    def test_benign_python_with_tests_has_no_risk_flags(self):
        review=review_change_plan(plan("def add(a,b):\n    return a+b\n"))
        self.assertEqual(review.risk_count,0)
        self.assertEqual(review.test_files,1)
        self.assertEqual(review.source_files,2)
        self.assertIn("Статическая",review.summary())

    def test_ast_detects_dangerous_execution_but_never_runs_it(self):
        source="import os\n\ndef bad():\n    eval('1+1')\n    os.system('echo unsafe')\n"
        review=review_change_plan(plan(source))
        self.assertGreaterEqual(review.risk_count,2)
        self.assertIn("опасные",review.summary())

    def test_shell_true_and_bare_except_reported(self):
        source=("import subprocess\n"
                "def check():\n"
                "    try:\n"
                "        subprocess.run('echo hi',shell=True)\n"
                "    except:\n"
                "        pass\n")
        review=review_change_plan(plan(source))
        self.assertTrue(any("shell=True" in f.message for f in review.findings))
        self.assertTrue(any(f.severity=="warning" for f in review.findings))

    def test_missing_tests_is_not_claimed_professional(self):
        review=review_change_plan(plan("def app(): return 1\n",tests=False,readme=False))
        self.assertEqual(review.test_files,0)
        self.assertIn("Нет проверяемых тестов",review.summary())
        self.assertTrue(any(f.path=="README.md" for f in review.findings))

    def test_unified_diff_shows_actual_line_changes_without_writing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            original=root/"app.py"
            original.write_text("def main():\n    return 1\n",encoding="utf-8")
            before=original.read_bytes()
            proposal=plan("def main():\n    return 2\n")
            diff=unified_plan_diff(proposal,root)
            self.assertIn("--- a/app.py",diff)
            self.assertIn("+++ b/app.py",diff)
            self.assertIn("-    return 1",diff)
            self.assertIn("+    return 2",diff)
            self.assertIn("+++ b/tests/test_app.py",diff)
            self.assertEqual(original.read_bytes(),before)
            self.assertFalse((root/"tests").exists())

    def test_unified_diff_warns_if_preview_is_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            source="x='a'\n"*600
            proposal=plan(source)
            diff=unified_plan_diff(proposal,Path(tmp),max_chars=1000)
            self.assertIn("DIFF ОБРЕЗАН",diff)
            self.assertLessEqual(len(diff),1120)

    def test_syntax_failure_does_not_execute_imports(self):
        review=review_change_plan(plan("def broken(:\n    pass\n"))
        self.assertGreater(review.risk_count,0)
        self.assertTrue(any("AST" in f.message for f in review.findings))


if __name__=="__main__":
    unittest.main()
