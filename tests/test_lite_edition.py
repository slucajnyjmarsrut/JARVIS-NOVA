# -*- coding: utf-8 -*-
"""JARVIS Lite: no bundled 1.9GB weights, safe separate model installation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from bundled_vision_runtime import (
    BundledRuntimeConfig,BundledRuntimeError,validate_offline_model_store,
)
from model_storage import (
    MODEL_NAME,active_model_store,installed_edition,
    local_model_available,user_model_store,
)
from optional_model_downloader import download_qwen


class LiteStorageTests(unittest.TestCase):
    @staticmethod
    def fake_store(path):
        model_bytes=b"unit-test sha256 data"
        digest=hashlib.sha256(model_bytes).hexdigest()
        manifest=path/"manifests/registry.ollama.ai/library/qwen3-vl/2b-instruct"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"config":{
            "digest":"sha256:"+digest,"size":len(model_bytes)},"layers":[]}))
        blobs=path/"blobs"
        blobs.mkdir()
        (blobs/("sha256-"+digest)).write_bytes(model_bytes)
        return blobs/("sha256-"+digest)

    def test_offline_keeps_embedded_weights_lite_uses_user_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            assets=root/"assets"
            assets.mkdir()
            user=root/"userdata"/"Models"/"ollama"
            (assets/"EDITION.txt").write_text("lite",encoding="utf-8")
            self.assertEqual(installed_edition(assets),"lite")
            self.assertEqual(active_model_store(assets,user_store=user),user)
            self.assertFalse(local_model_available(assets,user_store=user))
            blob=self.fake_store(user)
            self.assertTrue(local_model_available(assets,user_store=user))
            validate_offline_model_store(assets,model_store=user,verify_hashes=True)
            blob.write_bytes(b"tampered model data")
            with self.assertRaises(BundledRuntimeError):
                validate_offline_model_store(assets,model_store=user,verify_hashes=True)
            blob.write_bytes(b"unit-test sha256 data")
            bundled=assets/"models"/"ollama"
            self.fake_store(bundled)
            self.assertEqual(active_model_store(assets,user_store=user),bundled)
            (assets/"EDITION.txt").write_text("offline",encoding="utf-8")
            self.assertEqual(installed_edition(assets),"offline")
            self.assertEqual(BundledRuntimeConfig(assets).model_store,None)

    def test_user_store_is_separate_from_program_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Path(tmp)/"program"/"assets"
            app.mkdir(parents=True)
            path=user_model_store(localappdata=str(Path(tmp)/"user"))
            self.assertNotEqual(path,app/"models"/"ollama")
            self.assertIn("JarvisNova",str(path))
            self.assertEqual(MODEL_NAME,"qwen3-vl:2b-instruct")

    def test_model_download_needs_explicit_user_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets=Path(tmp)
            with self.assertRaises(PermissionError):
                download_qwen(assets,confirm=False)
            with self.assertRaises(PermissionError):
                download_qwen(assets)
            if __import__("os").name!="nt":
                with self.assertRaisesRegex(Exception,"Windows"):
                    download_qwen(assets,confirm=True)

    def test_package_never_embeds_weights_in_lite(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/"jarvis_nova.spec").read_text(encoding="utf-8")
        self.assertIn("JARVIS_NOVA_EDITION",source)
        self.assertIn("if not lite",source)
        self.assertIn("EDITION.txt",source)
        self.assertIn("'assets/models/ollama'",source)
        installer=(root/"installer/JarvisNovaLite.iss").read_text(encoding="utf-8")
        self.assertIn("dist\\lite\\JarvisNova",installer)
        self.assertIn("LITE-SETUP",installer)


    def test_lite_stable_release_never_switches_to_full_installer(self):
        from auto_update import parse_release, latest_release, UpdateError
        import hashlib
        blob=b"MZ"+b"x"*110_000
        name="JARVIS-NOVA-0.5.19-LITE-SETUP.exe"
        data={
            "tag_name":"v0.5.19","draft":False,"prerelease":False,
            "assets":[{"name":name,"size":len(blob),
                "digest":"sha256:"+hashlib.sha256(blob).hexdigest(),
                "state":"uploaded","browser_download_url":
                "https://github.com/slucajnyjmarsrut/JARVIS-NOVA/releases/download/v0.5.19/"+name}],
        }
        obj=parse_release(data,edition="lite")
        self.assertEqual(obj.edition,"lite")
        self.assertEqual(obj.installer_name,name)
        with self.assertRaises(UpdateError):
            parse_release(data,edition="offline")
        with self.assertRaises(UpdateError):
            parse_release(data,edition="unknown")
        latest=latest_release(requester=lambda:json.dumps(data).encode(),
                              edition="lite")
        self.assertEqual(latest.edition,"lite")

    def test_update_defers_while_optional_qwen_is_downloading(self):
        from types import SimpleNamespace
        from update_idle_guard import editing_window_open
        app=SimpleNamespace(_model_download_busy=True)
        self.assertTrue(editing_window_open(app))
        app._model_download_busy=False
        self.assertFalse(editing_window_open(app))

    def test_download_prompt_is_not_overridden_by_legacy_model_check(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        source=(root/"text_only_main.py").read_text(encoding="utf-8")
        module=ast.parse(source)
        controller=next(x for x in module.body
                        if isinstance(x,ast.ClassDef) and x.name=="TextJarvis")
        methods=[x.name for x in controller.body
                 if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))]
        self.assertEqual(methods.count("check_models"),1)
        check=next(x for x in controller.body
                   if isinstance(x,ast.FunctionDef) and x.name=="check_models")
        called=ast.get_source_segment(source,check)
        self.assertIn("messagebox.askyesno",called)
        self.assertIn("self.download_local_model()",called)
        self.assertIn("model_store=self.runtime.config.model_store",called)

    def test_compact_edition_has_ui_button_and_no_silent_pull(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"text_only_main.py").read_text(encoding="utf-8")
        self.assertIn("messagebox.askyesno",ui)
        self.assertIn("confirm=True",ui)
        self.assertIn("download_local_model",ui)
        self.assertIn("self._model_download_cancel.set()",ui)
        runtime=(root/"bundled_vision_runtime.py").read_text(encoding="utf-8")
        self.assertIn("'OLLAMA_NO_CLOUD': '1'",runtime)
        launcher=(root/"bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("installed_edition(root)",launcher)


if __name__=="__main__":
    unittest.main()
