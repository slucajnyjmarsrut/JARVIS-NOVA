# -*- coding: utf-8 -*-
"""One authorization may only save fresh, independently tested Python files."""
from pathlib import Path
import tempfile
import unittest

from code_autopilot import AutopilotResult, Attempt
from code_autosave_policy import (
    safe_new_project_folder, save_approved_one_shot)
from code_workspace import ChangePlan, ProposedFile, WorkspaceError


def prepared():
    plan=ChangePlan("python",(
        ProposedFile("app.py","def add(a,b): return a+b\n"),
        ProposedFile("tests/test_acceptance_app.py",
            "import unittest\nfrom app import add\n"
            "class Cases(unittest.TestCase):\n"
            " def test_add(self): self.assertEqual(add(2,3),5)\n"
            " def test_negative(self): self.assertEqual(add(-2,1),-1)\n"),
        ProposedFile("README.md","# Project\n")
    ))
    return AutopilotResult(
        plan,[Attempt(1,"passed","Docker: 3 tests. verified")],True)


class AutoSaveSafetyTests(unittest.TestCase):
    def test_new_project_requires_upfront_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            folder=home/"JARVIS-NOVA-Projects"/"Project-deadbeef"
            self.assertTrue(safe_new_project_folder(folder,home=home))
            with self.assertRaises(PermissionError):
                save_approved_one_shot(prepared(),folder,home=home)
            self.assertFalse(folder.exists())
            written=save_approved_one_shot(
                prepared(),folder,home=home,authorized=True)
            self.assertEqual(len(written),3)
            self.assertIn("a+b",(folder/"app.py").read_text())
            with self.assertRaises(WorkspaceError):
                save_approved_one_shot(
                    prepared(),folder,home=home,authorized=True)

    def test_no_silent_write_for_failed_or_unverified_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            folder=home/"JARVIS-NOVA-Projects"/"Project-12345678"
            cases=[
                AutopilotResult(prepared().plan,[Attempt(1,"failed","Docker: errors")],False),
                AutopilotResult(prepared().plan,[Attempt(1,"passed","AST only")],True),
                AutopilotResult(prepared().plan,[Attempt(1,"skipped","Docker absent")],False),
            ]
            for result in cases:
                with self.subTest(status=result.attempts[-1].status):
                    with self.assertRaises(WorkspaceError):
                        save_approved_one_shot(
                            result,folder,authorized=True,home=home)
            self.assertFalse(folder.exists())

    def test_no_external_directory_even_with_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            for folder in (
                home/"Other"/"Project-deadbeef",
                home/"JARVIS-NOVA-Projects"/"anothername",
                home/"Project-deadbeef",
            ):
                with self.subTest(path=str(folder)):
                    self.assertFalse(safe_new_project_folder(folder,home=home))
                    with self.assertRaises(WorkspaceError):
                        save_approved_one_shot(
                            prepared(),folder,authorized=True,home=home)
                    self.assertFalse(folder.exists())


if __name__=="__main__":
    unittest.main()
