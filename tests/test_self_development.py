# -*- coding: utf-8 -*-
"""Bounded self-fixes require correct Git origin, jarvis HEAD and user approval."""
import json
from pathlib import Path
import tempfile
import unittest

from self_development import (
    EDITABLE, is_self_fix_command, suggest_target, validate_checkout,
    prepare_self_fix, apply_self_fix,
)
from code_workspace import WorkspaceError


OLD = "def status():\n    return 'old'\n"
NEW = "def status():\n    return 'fixed'\n"


def model_output(*, path="text_only_ui.py", content=NEW, language="python"):
    return json.dumps({
        "language": language,
        "files": [{"path": path, "content": content}],
    })


class SelfDevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.checkout = Path(self.tmp.name) / "JARVIS-NOVA"
        git = self.checkout / ".git"
        git.mkdir(parents=True)
        (git / "HEAD").write_text("ref: refs/heads/jarvis\n", encoding="utf-8")
        (git / "config").write_text(
            '[core]\n\tbare = false\n'
            '[remote "origin"]\n\turl = https://github.com/slucajnyjmarsrut/JARVIS-NOVA.git\n',
            encoding="utf-8")
        self.file = self.checkout / "text_only_ui.py"
        self.file.write_text(OLD, encoding="utf-8")

    def prepare(self, **kwargs):
        return prepare_self_fix(
            self.checkout, "text_only_ui.py",
            "Исправь отображение статуса интерфейса",
            generator=lambda *_: model_output(**kwargs))

    def test_screenshot_automatically_suggests_only_safe_ui_files(self):
        cases = (
            ("На скриншоте белые заголовки окон", "windows_titlebar.py"),
            ("Ошибка в видео-студии", "viral_studio_ui.py"),
            ("Не открывается меню настроек", "nova_command_palette.py"),
            ("Кнопка отправки скриншота", "screenshot_review.py"),
            ("Плохой текст в интерфейсе", "text_only_ui.py"),
        )
        for report, target in cases:
            with self.subTest(report=report):
                self.assertEqual(suggest_target(report), target)
                self.assertIn(target, EDITABLE)
        self.assertNotEqual(suggest_target("Измени auto_update.py"),"auto_update.py")

    def test_command_is_explicit_and_cannot_capture_coding_chat(self):
        for command in ("Исправь себя", "Джарвис, исправь себя!",
                        "почини себя", "исправь свой интерфейс"):
            self.assertTrue(is_self_fix_command(command),command)
        for ordinary in ("исправь мой код", "как улучшить себя", "создай мне приложение",
                         "", "сделай ролик"):
            self.assertFalse(is_self_fix_command(ordinary),ordinary)

    def test_proposal_is_disposable_until_user_confirms(self):
        proposal = self.prepare()
        self.assertEqual(self.file.read_text(encoding="utf-8"), OLD)
        self.assertIn("Синтаксис Python проверен",proposal.diagnostics)
        with self.assertRaises(PermissionError):
            apply_self_fix(proposal)
        self.assertEqual(self.file.read_text(encoding="utf-8"), OLD)
        changed = apply_self_fix(proposal, confirmed=True)
        self.assertEqual([Path(p).resolve() for p in changed],[self.file.resolve()])
        self.assertEqual(self.file.read_text(encoding="utf-8"), NEW)
        copies = list((self.checkout/".jarvis_code_backups").glob("revision-*/text_only_ui.py"))
        self.assertEqual(len(copies),1)
        self.assertEqual(copies[0].read_text(encoding="utf-8"),OLD)

    def test_other_branches_and_wrong_repository_are_blocked(self):
        head=self.checkout/".git"/"HEAD"
        for branch in ("main", "dev", "jarvis-other"):
            head.write_text(f"ref: refs/heads/{branch}\n",encoding="utf-8")
            with self.subTest(branch=branch),self.assertRaises(WorkspaceError):
                validate_checkout(self.checkout)
        head.write_text("ref: refs/heads/jarvis\n",encoding="utf-8")
        config=self.checkout/".git"/"config"
        config.write_text('[remote "origin"]\n url = https://github.com/other/name.git\n',
                          encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            validate_checkout(self.checkout)

    def test_recheck_branch_and_hash_at_apply_time(self):
        proposal=self.prepare()
        (self.checkout/".git"/"HEAD").write_text(
            "ref: refs/heads/main\n",encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            apply_self_fix(proposal,confirmed=True)
        (self.checkout/".git"/"HEAD").write_text(
            "ref: refs/heads/jarvis\n",encoding="utf-8")
        self.file.write_text("def status():\n return 'changed elsewhere'\n",encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            apply_self_fix(proposal,confirmed=True)
        self.assertIn("changed elsewhere",self.file.read_text(encoding="utf-8"))

    def test_refuse_unlisted_paths_and_multi_file_proposals(self):
        self.assertNotIn("auto_update.py",EDITABLE)
        self.assertNotIn("self_development.py",EDITABLE)
        for path in ("main.py","auto_update.py","../outside.py",".github/workflows/x.yml"):
            with self.subTest(path=path),self.assertRaises(WorkspaceError):
                prepare_self_fix(self.checkout,path,"Исправь интерфейс после обновления",
                                 generator=lambda *_:model_output())
        with self.assertRaises(WorkspaceError):
            self.prepare(path="auto_update.py")
        with self.assertRaises(WorkspaceError):
            self.prepare(language="javascript")
        with self.assertRaises(WorkspaceError):
            self.prepare(content="def broken(:\n  pass\n")

    def test_rejects_symlinked_file_if_supported(self):
        destination=self.checkout/"original.py"
        destination.write_text(OLD,encoding="utf-8")
        self.file.unlink()
        try:
            self.file.symlink_to(destination)
        except (OSError,NotImplementedError):
            self.skipTest("No file symlink privilege on this runner")
        with self.assertRaises(WorkspaceError):
            self.prepare()

    def test_preview_does_not_execute_generated_code_or_run_commands(self):
        generated = (
            "import os\n"
            "def danger():\n"
            "    os.system('echo THIS_MUST_NOT_EXECUTE')\n"
        )
        proposal=self.prepare(content=generated)
        self.assertIn("os.system",proposal.plan.files[0].content)
        self.assertEqual(self.file.read_text(encoding="utf-8"), OLD)
        # Deliberately no commit: syntax-only check is NOT a security proof.
        self.assertFalse((self.checkout/"THIS_MUST_NOT_EXECUTE").exists())


if __name__=="__main__":
    unittest.main()
