# -*- coding: utf-8 -*-
"""Threat-focused offline tests for opt-in Python unittest container gate."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from code_test_sandbox import run_python_tests


class DockerTestGateTests(unittest.TestCase):
    def project(self, directory):
        root = Path(directory)
        (root / "tests").mkdir(parents=True)
        (root / "main.py").write_text("def add(x, y): return x+y\n", encoding="utf-8")
        (root / "tests" / "test_main.py").write_text(
            "import unittest\nfrom main import add\n"
            "class Tests(unittest.TestCase):\n"
            "    def test_add(self): self.assertEqual(add(2,3),5)\n",
            encoding="utf-8")
        (root / ".env").write_text("TOKEN=PRIVATE", encoding="utf-8")
        (root / "private.key").write_text("KEY", encoding="utf-8")
        return root

    def test_explicit_consent_required_and_never_runs_host_python(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.project(directory)
            with mock.patch("code_test_sandbox.subprocess.run") as runner:
                with self.assertRaises(PermissionError):
                    run_python_tests(root)
                runner.assert_not_called()

    def test_empty_tests_are_skipped_not_misreported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"main.py").write_text("print('never run')\n",encoding="utf-8")
            result=run_python_tests(root,confirmed=True,docker_cli="docker",
                                    executor=mock.Mock())
            self.assertEqual(result.status,"skipped")
            self.assertEqual(result.tests_run,0)

    def test_never_mounts_real_source_secrets_or_allows_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.project(directory)
            commands=[]
            def fake_run(argv, **kwargs):
                commands.append(argv)
                self.assertIsInstance(argv,list)
                self.assertNotIn("shell",kwargs)
                if argv[1:3]==["image","inspect"]:
                    return subprocess.CompletedProcess(argv,0,stdout="[]",stderr="")
                self.assertEqual(argv[1],"run")
                self.assertIn("--network",argv)
                self.assertEqual(argv[argv.index("--network")+1],"none")
                self.assertIn("--read-only",argv)
                self.assertIn("--cap-drop",argv)
                self.assertIn("--memory",argv)
                self.assertIn("--pull",argv)
                self.assertEqual(argv[argv.index("--pull")+1],"never")
                self.assertNotIn("sh",argv)
                self.assertNotIn("bash",argv)
                mount = argv[argv.index("--mount")+1]
                self.assertIn("target=/workspace,readonly",mount)
                stage = Path(mount.split("source=",1)[1].split(",target=")[0])
                self.assertNotEqual(stage.resolve(),root.resolve())
                self.assertEqual(len(list(stage.rglob("*.py"))),2)
                self.assertFalse((stage/".env").exists())
                self.assertFalse((stage/"private.key").exists())
                self.assertTrue((stage/"tests"/"test_main.py").is_file())
                return subprocess.CompletedProcess(
                    argv,0,stdout="",stderr="Ran 1 test in 0.002s\n\nOK\n")
            result=run_python_tests(root,confirmed=True,docker_cli="docker",
                                    executor=fake_run)
            self.assertEqual(result.status,"passed")
            self.assertEqual(result.tests_run,1)
            self.assertEqual(result.inspected_files,2)
            self.assertEqual(len(commands),2)

    def test_zero_discovered_tests_never_claim_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.project(directory)
            def fake_run(argv,**kwargs):
                if argv[1:3]==["image","inspect"]:
                    return subprocess.CompletedProcess(argv,0,stdout="",stderr="")
                return subprocess.CompletedProcess(
                    argv,0,stdout="",stderr="Ran 0 tests in 0.000s\n\nOK")
            result=run_python_tests(root,confirmed=True,docker_cli="docker",
                                    executor=fake_run)
            self.assertEqual(result.status,"failed")
            self.assertEqual(result.tests_run,0)

    def test_nonzero_exit_and_missing_image_are_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.project(directory)
            for code, expected in ((1,"skipped"), (0,"failed")):
                def fake_run(argv,**kwargs):
                    if argv[1:3]==["image","inspect"]:
                        return subprocess.CompletedProcess(argv,code,"","no image")
                    return subprocess.CompletedProcess(
                        argv,1,stdout="",stderr="Ran 1 test in 0.1s\nFAILED")
                report=run_python_tests(
                    root,confirmed=True,docker_cli="docker",executor=fake_run)
                self.assertEqual(report.status,expected)

    def test_timeout_and_no_docker_fallback_never_execute_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.project(directory)
            def fake_run(argv,**kwargs):
                if argv[1:3]==["image","inspect"]:
                    return subprocess.CompletedProcess(argv,0,"","")
                raise subprocess.TimeoutExpired(argv,kwargs.get("timeout",10))
            report=run_python_tests(root,confirmed=True,docker_cli="docker",
                                    executor=fake_run)
            self.assertEqual(report.status,"failed")
            with mock.patch("code_test_sandbox.shutil.which",return_value=None):
                result=run_python_tests(root,confirmed=True)
                self.assertEqual(result.status,"skipped")

    def test_docker_timeout_forcibly_removes_only_own_named_container(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.project(directory)
            calls=[]
            def fake_run(argv,**kwargs):
                calls.append(argv)
                if argv[1:3]==["image","inspect"]:
                    return subprocess.CompletedProcess(argv,0,"","")
                if argv[1]=="run":
                    self.assertIn("--name",argv)
                    self.assertIn("--rm",argv)
                    raise subprocess.TimeoutExpired(argv,kwargs.get("timeout",10))
                if argv[1:3]==["rm","-f"]:
                    return subprocess.CompletedProcess(argv,0,"","")
                self.fail("Unexpected Docker action: "+str(argv))
            result=run_python_tests(root,confirmed=True,docker_cli="docker",
                                    executor=fake_run)
            self.assertEqual(result.status,"failed")
            self.assertEqual([x[1] for x in calls],["image","run","rm"])
            name=calls[1][calls[1].index("--name")+1]
            self.assertTrue(name.startswith("jarvis-nova-review-"))
            self.assertEqual(calls[2],["docker","rm","-f",name])
            self.assertIn("остановлен",result.output)

    def test_rejects_symlinked_project_and_never_imports_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            project=self.project(root/"project")
            link=root/"alias"
            try:
                link.symlink_to(project,target_is_directory=True)
            except (OSError,NotImplementedError):
                self.skipTest("Symlink creation not allowed")
            with self.assertRaises(ValueError):
                run_python_tests(link,confirmed=True,docker_cli="docker")
