# -*- coding: utf-8 -*-
"""Prove production suites use process isolation rather than shared Tcl state."""
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from scripts.run_text_only_tests import run_suites, ROOT

class SuiteIsolationTests(unittest.TestCase):
    def test_each_module_gets_its_own_process(self):
        suites=("test_text_only_mode.py","test_night_supervisor.py")
        calls=[]
        def runner(argv, **kw):
            calls.append((argv,kw))
            return SimpleNamespace(returncode=0)
        self.assertEqual(run_suites(runner=runner,suites=suites),())
        self.assertEqual(len(calls),2)
        for (argv,kw),name in zip(calls,suites):
            self.assertEqual(argv[-2:], [name, "-v"])
            self.assertEqual(argv[2:5],["-m","unittest","discover"])
            self.assertEqual(kw["cwd"],str(ROOT))
            self.assertFalse(kw["shell"])
            self.assertEqual(kw["timeout"],300)

    def test_failed_module_does_not_hide_other_results(self):
        runner=Mock(side_effect=[SimpleNamespace(returncode=5),
                                 SimpleNamespace(returncode=0)])
        suites=("test_night_supervisor.py","test_text_only_mode.py")
        self.assertEqual(run_suites(runner=runner,suites=suites),
                         ("test_night_supervisor.py",))
        self.assertEqual(runner.call_count,2)

    def test_timeout_is_failure(self):
        runner=Mock(side_effect=subprocess.TimeoutExpired(["python"],300))
        self.assertEqual(run_suites(runner=runner,
                                   suites=("test_night_supervisor.py",)),
                         ("test_night_supervisor.py",))

    def test_unlisted_test_never_executes(self):
        runner=Mock()
        with self.assertRaises(SystemExit):
            run_suites(runner=runner,suites=("../arbitrary.py",))
        runner.assert_not_called()

if __name__=="__main__":
    unittest.main()
