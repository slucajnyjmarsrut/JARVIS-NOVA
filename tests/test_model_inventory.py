# -*- coding: utf-8 -*-
"""Across-drive local model discovery, privacy and audited Qwen reuse."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from local_model_inventory import (
    MIN_WEIGHTS, fixed_local_drives, scan_local_models,
    summarize_inventory,
)
from model_storage import (
    active_model_store, preferred_model_store,
    remember_existing_model_store,
)


def fake_ollama_store(root):
    store=root/"models"/"ollama"
    content=b"small test-only model blob"
    digest=hashlib.sha256(content).hexdigest()
    manifest=(store/"manifests"/"registry.ollama.ai"/
              "library"/"qwen3-vl"/"2b-instruct")
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps({
        "config":{"digest":"sha256:"+digest,"size":len(content)},
        "layers":[]}),encoding="utf-8")
    blobs=store/"blobs"
    blobs.mkdir(parents=True,exist_ok=True)
    (blobs/("sha256-"+digest)).write_bytes(content)
    return store


class ModelInventoryTests(unittest.TestCase):
    def test_never_scans_without_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("local_model_inventory.os.scandir",
                            side_effect=AssertionError("Unauthorized scan")):
                with self.assertRaises(PermissionError):
                    scan_local_models(roots=(Path(tmp),))

    def test_scans_two_drives_and_recognizes_ollama_and_gguf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=root/"C"; first.mkdir()
            second=root/"D"; second.mkdir()
            first_model=first/"Downloads"/"other-model.gguf"
            first_model.parent.mkdir()
            with first_model.open("wb") as f:
                f.truncate(MIN_WEIGHTS+100)
            (first_model.parent/"bank-credentials.txt").write_text(
                "PRIVATE TEXT MUST NEVER APPEAR")
            (second/"Models").mkdir()
            other=second/"Models"/"diffusion.safetensors"
            with other.open("wb") as f:
                f.truncate(MIN_WEIGHTS+120)
            installed=fake_ollama_store(second/"Programs"/"External")
            report=scan_local_models(
                confirmed=True,roots=(first,second))
            self.assertEqual(len(report.drives),2)
            self.assertFalse(report.incomplete)
            self.assertFalse(report.cancelled)
            self.assertTrue(any(m.jarvis_compatible and
                                m.location==installed for m in report.models))
            self.assertTrue(any(m.kind=="gguf" for m in report.models))
            self.assertTrue(any(m.kind=="safetensors" for m in report.models))
            self.assertNotIn("bank-credentials",summarize_inventory(report))
            self.assertNotIn("PRIVATE TEXT",summarize_inventory(report))

    def test_default_scan_includes_every_available_fixed_drive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            c=root/"C";d=root/"D"
            c.mkdir();d.mkdir()
            for folder in (c,d):
                with (folder/"model.gguf").open("wb") as f:
                    f.truncate(MIN_WEIGHTS+10)
            with mock.patch("local_model_inventory.fixed_local_drives",
                            return_value=(c,d)):
                result=scan_local_models(confirmed=True)
            self.assertEqual(len(result.models),2)
            self.assertEqual(result.drives,(c,d))

    def test_bounded_scan_and_cancellation_never_runs_an_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            for n in range(20):
                (d/f"sub{n:02d}").mkdir()
            with mock.patch("local_model_inventory.subprocess",create=True,
                            side_effect=AssertionError("No programs may run")):
                report=scan_local_models(
                    confirmed=True,roots=(d,),max_dirs=2)
            self.assertTrue(report.incomplete)
            self.assertLessEqual(report.checked_dirs,2)
            canceled=threading.Event()
            canceled.set()
            result=scan_local_models(
                confirmed=True,roots=(d,),cancel=canceled)
            self.assertTrue(result.cancelled)
            self.assertEqual(result.checked_dirs,0)

    def test_compatibility_only_for_audited_qwen_not_unknown_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            broken=base/"unknown"/"models"/"ollama"
            file=(broken/"manifests"/"registry.ollama.ai"/
                  "library"/"qwen3-vl"/"2b-instruct")
            file.parent.mkdir(parents=True)
            file.write_text('{"config":{"digest":"sha256:bad"},"layers":[]}')
            record=scan_local_models(confirmed=True,roots=(base,))
            self.assertEqual(len(record.models),1)
            self.assertFalse(record.models[0].jarvis_compatible)

    def test_adoption_requires_approval_and_reuses_original_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            assets=root/"app"/"assets"
            assets.mkdir(parents=True)
            user=root/"appdata"
            store=fake_ollama_store(root/"D")
            with self.assertRaises(PermissionError):
                remember_existing_model_store(store,localappdata=str(user))
            adopted=remember_existing_model_store(
                store,confirmed=True,localappdata=str(user))
            self.assertEqual(adopted,store.resolve())
            self.assertEqual(
                preferred_model_store(localappdata=str(user)),store.resolve())
            with mock.patch.dict("os.environ",{"LOCALAPPDATA":str(user)}):
                self.assertEqual(active_model_store(assets),store.resolve())
            self.assertFalse((assets/"models"/"ollama").exists())
            self.assertTrue((store/"blobs").exists())

    def test_corrupt_external_blob_is_never_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            store=fake_ollama_store(root)
            (next((store/"blobs").iterdir())).write_bytes(
                b"changed but same size file"[:26])
            # Even a mismatching digest with unchanged length must be rejected.
            with self.assertRaises(Exception):
                remember_existing_model_store(
                    store,confirmed=True,localappdata=str(root/"user"))
            self.assertFalse(
                (root/"user"/"JarvisNova"/"Models"/"preferred-store.json").exists())


if __name__=="__main__":
    unittest.main()
