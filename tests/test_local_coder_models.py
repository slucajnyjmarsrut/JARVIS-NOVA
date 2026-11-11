# -*- coding: utf-8 -*-
"""Never use unknown downloaded weights as executable models without approval."""
import unittest
from types import SimpleNamespace
from unittest import mock

from local_coder_models import (
    CODE_NAME, ENDPOINT, best_installed_coder, installed_coders, _NoRedirect)
from code_gui import CodeWindow
from code_workspace import WorkspaceError


class LocalCoderModelsTests(unittest.TestCase):
    def test_permission_blocks_local_api_access(self):
        with self.assertRaises(PermissionError):
            best_installed_coder(
                transport=lambda:self.fail("No consent, no port probe"))
        with self.assertRaises(PermissionError):
            installed_coders(
                transport=lambda:self.fail("No consent, no port probe"))

    def test_picks_best_already_installed_coder_with_resource_cap(self):
        response={"models":[
            {"name":"qwen2.5-coder:7b","size":4_000_000_000},
            {"name":"qwen3-coder:14b","size":9_000_000_000},
            {"name":"deepseek-coder:1.3b","size":800_000_000},
            {"name":"qwen3-coder:30b","size":20_000_000_000},
            {"name":"my-own-model:14b","size":7_000_000_000},
            {"name":"qwen2.5-coder:7b-instruct","size":4_800_000_000},
            {"name":"../../unsafe:7b","size":2_000_000_000},
            {"name":"qwen3-coder:14b","size":None},
            {"name":"qwen3-coder:14b","size":True},
        ]}
        choices=installed_coders(confirmed=True,transport=lambda:response)
        self.assertEqual(len(choices),4)
        self.assertEqual(choices[0].name,"qwen3-coder:14b")
        self.assertEqual(best_installed_coder(
            confirmed=True,transport=lambda:response).billions,14)
        self.assertTrue(all(x.disk_bytes>0 for x in choices))
        self.assertEqual(ENDPOINT,"http://127.0.0.1:11434")

    def test_weak_unknown_or_injected_tags_are_not_used(self):
        data={"models":[
            {"name":"qwen2.5-coder:7b; curl evil","size":4_000_000_000},
            {"name":"codellama:32b","size":10_000_000_000},
            {"name":"qwen3:8b","size":5_000_000_000},
            {"name":"qwen2.5-coder:14b","size":False},
        ]}
        self.assertIsNone(best_installed_coder(
            confirmed=True,transport=lambda:data))
        for value in ("any","broken",{"models":"bad"}):
            with self.assertRaises(ValueError):
                installed_coders(confirmed=True,transport=lambda v=value:v)
        with self.assertRaises(RuntimeError):
            _NoRedirect().redirect_request(
                None,None,302,"Moved",{},"https://example.com/leak")

    def test_uses_selected_model_in_worker_without_rescanning(self):
        win=mock.Mock()
        win._coder_opt_in=True
        win._coder_checked=False
        win._coder_choice=None
        win.master=SimpleNamespace(engine="bundled")
        selection=SimpleNamespace(name="qwen2.5-coder:7b")
        with mock.patch("local_coder_models.best_installed_coder",
                        return_value=selection) as probe, \
             mock.patch("code_gui.request_local_model",
                        return_value="project JSON") as model:
            result=CodeWindow._model_generator(win,"Make project","python")
            self.assertEqual(result,"project JSON")
            model.assert_called_once_with(
                "Make project","python",
                endpoint="http://127.0.0.1:11434",
                model="qwen2.5-coder:7b")
            CodeWindow._model_generator(win,"Repair project","python")
            probe.assert_called_once_with(confirmed=True)
            self.assertEqual(model.call_count,2)

    def test_unavailable_service_reverts_to_configured_qwen(self):
        runtime=mock.Mock()
        runtime.start.return_value="http://127.0.0.1:41111"
        runtime.config.model="qwen3-vl:2b-instruct"
        win=mock.Mock()
        win.master=SimpleNamespace(
            engine="bundled",trimodal=SimpleNamespace(runtime=runtime))
        win._coder_opt_in=True
        win._coder_checked=False
        win._coder_choice=None
        with mock.patch("local_coder_models.best_installed_coder",
                        side_effect=OSError("Offline")), \
             mock.patch("code_gui.request_local_model",
                        return_value="fallback") as make:
            result=CodeWindow._model_generator(win,"Task","python")
            self.assertEqual(result,"fallback")
            make.assert_called_once_with(
                "Task","python",endpoint="http://127.0.0.1:41111",
                model="qwen3-vl:2b-instruct")


if __name__=="__main__":
    unittest.main()
