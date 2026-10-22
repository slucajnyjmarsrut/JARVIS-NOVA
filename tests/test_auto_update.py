# -*- coding: utf-8 -*-
"""Security and unattended-update integration tests; zero real download/install."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

from auto_update import (
    APP_VERSION, API_URL, Release, UpdateError, _exact_repo_url,
    _trusted_asset_destination, check_and_download, download_release,
    latest_release, parse_release, stage_helper, version_tuple,
)
from updater_worker import apply_update


def fake_asset(version="0.5.19",blob=None,*,digest=None,url=None):
    blob=blob or (b"MZ"+b"x"*120_000)
    digest=digest or hashlib.sha256(blob).hexdigest()
    name=f"JARVIS-NOVA-{version}-OFFLINE-SETUP.exe"
    url=url or ("https://github.com/slucajnyjmarsrut/JARVIS-NOVA/"
                f"releases/download/v{version}/{name}")
    return {"name":name,"browser_download_url":url,"digest":"sha256:"+digest,
            "size":len(blob),"state":"uploaded"}


def release_data(version="0.5.19",**kw):
    return {"draft":False,"prerelease":False,"tag_name":"v"+version,
            "assets":[fake_asset(version,**kw)]}


class FakeOpener:
    def __init__(self,blob):
        self.blob=blob
        self.requests=[]
    def open(self,req,timeout=None):
        self.requests.append((req.full_url,timeout))
        return io.BytesIO(self.blob)


class UpdaterTests(unittest.TestCase):
    def test_stable_version_comparison_and_no_release(self):
        self.assertEqual(version_tuple("v0.5.19"),(0,5,19))
        self.assertIsNone(parse_release(release_data("0.5.18")))
        self.assertIsNone(parse_release(release_data("0.5.17")))
        for tag in ("0.5.19-dev","v0.5.20-rc1","v0.5.19/evil","999"):
            with self.subTest(tag=tag),self.assertRaises(UpdateError):
                version_tuple(tag)
        response=json.dumps(release_data()).encode()
        candidate=latest_release(requester=lambda:response)
        self.assertEqual(candidate.version,"0.5.19")
        self.assertEqual(candidate.sha256,fake_asset()["digest"][7:])

    def test_never_install_prerelease_draft_or_foreign_release_url(self):
        for flag in ("draft","prerelease"):
            data=release_data()
            data[flag]=True
            with self.assertRaises(UpdateError):
                parse_release(data)
        for bad in (
            "https://evil.example/download.exe",
            "http://github.com/slucajnyjmarsrut/JARVIS-NOVA/releases/download/...",
            "https://github.com.evil.org/slucajnyjmarsrut/JARVIS-NOVA/releases/download/v0.5.19/a",
            "https://github.com:0/slucajnyjmarsrut/JARVIS-NOVA/releases/download/v0.5.19/a",
            "https://github.com:bad/slucajnyjmarsrut/JARVIS-NOVA/releases/download/v0.5.19/a",
            "https://github.com/other/JARVIS-NOVA/releases/download/v0.5.19/a",
            "https://github.com@evil.org/slucajnyjmarsrut/JARVIS-NOVA/releases/download/v0.5.19/a",
        ):
            self.assertFalse(_exact_repo_url(bad))
            with self.assertRaises(UpdateError):
                parse_release(release_data(url=bad))
        self.assertFalse(_trusted_asset_destination("https://attacker.example/assets"))
        self.assertTrue(_trusted_asset_destination("https://release-assets.githubusercontent.com/foo?x=1"))

    def test_require_sha256_size_uploaded_and_exact_release_asset(self):
        baseline=release_data()
        for mutate in ("missing_digest","bad_hash","missing_size","size_bool",
                       "not_uploaded","wrong_name","duplicate","wrong_path"):
            data=json.loads(json.dumps(baseline))
            asset=data["assets"][0]
            if mutate=="missing_digest":asset.pop("digest")
            elif mutate=="bad_hash":asset["digest"]="sha256:nothash"
            elif mutate=="missing_size":asset.pop("size")
            elif mutate=="size_bool":asset["size"]=True
            elif mutate=="not_uploaded":asset["state"]="new"
            elif mutate=="wrong_name":asset["name"]="JARVIS-EVIL-0.5.19.exe"
            elif mutate=="duplicate":data["assets"].append(dict(asset))
            elif mutate=="wrong_path":
                asset["browser_download_url"]=asset["browser_download_url"].replace(
                    "/download/v0.5.19/","/download/v0.5.18/")
            with self.subTest(mutate=mutate),self.assertRaises(UpdateError):
                parse_release(data)

    def test_missing_official_release_is_not_a_failure(self):
        error=urllib.error.HTTPError(API_URL,404,"Not found",{},None)
        def absent():raise error
        self.assertIsNone(latest_release(requester=absent))
        def bigger():return b"*"*700_001
        with self.assertRaises(UpdateError):
            latest_release(requester=bigger)

    def test_full_download_sha256_and_offline_cache_reuse(self):
        blob=b"MZ"+b"x"*120_000
        r=parse_release(release_data(blob=blob))
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/"Updates"
            downloader=FakeOpener(blob)
            path=download_release(r,folder,opener=downloader)
            self.assertEqual(path.read_bytes(),blob)
            self.assertEqual(len(downloader.requests),1)
            reused=download_release(r,folder,opener=FakeOpener(b"evil"))
            self.assertEqual(reused,path)
            self.assertEqual(sorted(folder.iterdir()),[path])
            path.write_bytes(b"MZ"+b"tampered")
            with self.assertRaises(UpdateError):
                download_release(r,folder,opener=FakeOpener(blob))
            self.assertEqual(path.read_bytes(),b"MZ"+b"tampered")

    def test_bad_downloads_are_cleaned_before_execution(self):
        blob=b"MZ"+b"x"*120_000
        r=parse_release(release_data(blob=blob))
        for bad in (b"MZ"+b"y"*120_000,b"MZtiny",blob+b"extra"):
            with self.subTest(len_bad=len(bad)),tempfile.TemporaryDirectory() as td:
                folder=Path(td)/"Updates"
                with self.assertRaises(UpdateError):
                    download_release(r,folder,opener=FakeOpener(bad))
                self.assertFalse(list(folder.glob("*")))
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/"Updates"
            stop=__import__("threading").Event()
            stop.set()
            with self.assertRaises(UpdateError):
                download_release(r,folder,opener=FakeOpener(blob),cancel=stop)
            self.assertFalse(folder.exists())

    def test_detached_worker_staged_from_installed_file_not_web(self):
        blob=b"MZ"+b"x"*120_000
        r=parse_release(release_data(blob=blob))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            app=root/"Installed"/"JarvisNova.exe";app.parent.mkdir()
            app.write_bytes(b"MZ"+"x".encode()*5000)
            worker=app.parent/"JarvisNovaUpdater.exe"
            worker.write_bytes(b"MZ"+"WORKER".encode()*50)
            cache=root/"Updates"
            candidate=download_release(r,cache,opener=FakeOpener(blob))
            spawned=[]
            def capture(args,**kwargs):
                spawned.append((args,kwargs))
                self.assertEqual(Path(args[0]).read_bytes(),worker.read_bytes())
                self.assertIn("--apply",args)
                self.assertNotIn("powershell",str(args).lower())
            stage_helper(r,candidate,app,cache,launcher=capture)
            self.assertEqual(len(spawned),1)

    def test_worker_checks_same_release_and_runs_silent_installer_only_after_exit(self):
        blob=b"MZ"+b"x"*120_000
        rel=parse_release(release_data(blob=blob))
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/"Updates"
            installed=Path(td)/"Installed";installed.mkdir()
            app=installed/"JarvisNova.exe";app.write_bytes(b"MZ"+"x".encode()*100)
            candidate=download_release(rel,folder,opener=FakeOpener(blob))
            order=[]
            def wait(pid):
                self.assertEqual(pid,32142)
                order.append("wait")
            def install(args):
                self.assertEqual(order,["wait"])
                self.assertEqual(Path(args[0]).resolve(),candidate.resolve())
                self.assertIn("/VERYSILENT",args)
                self.assertIn("/NORESTART",args)
                self.assertEqual(Path(args[-1][5:]).resolve(),installed.resolve())
                order.append("install")
                (installed/"JARVIS_NOVA_VERSION.txt").write_text(rel.version)
                return 0
            def relaunch(exe):
                self.assertEqual(order,["wait","install"])
                self.assertEqual(exe.resolve(),app.resolve())
                order.append("launch")
            self.assertTrue(apply_update(candidate,app,rel.version,rel.sha256,32142,
                release_lookup=lambda:rel,wait=wait,installer_run=install,
                relaunch=relaunch,folder=folder))
            self.assertEqual(order,["wait","install","launch"])
            self.assertEqual(json.loads((folder/"update-status.json").read_text())["status"],"installed")

    def test_worker_fails_closed_for_version_change_bad_hash_or_exit_timeout(self):
        blob=b"MZ"+b"x"*120_000
        rel=parse_release(release_data(blob=blob))
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/"Updates"
            installed=Path(td)/"Installed";installed.mkdir()
            app=installed/"JarvisNova.exe";app.write_bytes(b"MZxxxx")
            candidate=download_release(rel,folder,opener=FakeOpener(blob))
            for kwargs in (
                {"release_lookup":lambda:None,"wait":lambda pid:None},
                {"release_lookup":lambda:rel,"wait":lambda pid:(_ for _ in ()).throw(UpdateError("busy"))},
            ):
                with self.assertRaises(UpdateError):
                    apply_update(candidate,app,rel.version,rel.sha256,10,
                                 installer_run=lambda a:self.fail("unverified install"),
                                 folder=folder,**kwargs)
            candidate.write_bytes(b"MZtampered")
            with self.assertRaises(UpdateError):
                apply_update(candidate,app,rel.version,rel.sha256,10,
                             release_lookup=lambda:rel,
                             installer_run=lambda a:self.fail("unverified install"),
                             folder=folder)

    def test_worker_restarts_old_app_when_release_changes_after_exit(self):
        blob=b"MZ"+b"x"*120_000
        rel=parse_release(release_data(blob=blob))
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/"Updates"
            installed=Path(td)/"Installed";installed.mkdir()
            app=installed/"JarvisNova.exe";app.write_bytes(b"MZoriginal")
            candidate=download_release(rel,folder,opener=FakeOpener(blob))
            calls=[]
            def wait(pid):
                calls.append("old-app-exited")
            def look():
                calls.append("recheck-release")
                raise TimeoutError("lost connection")
            def start(exe):
                calls.append("old-app-restarted")
                self.assertEqual(exe.resolve(),app.resolve())
            with self.assertRaises(TimeoutError):
                apply_update(candidate,app,rel.version,rel.sha256,100,
                    release_lookup=look,wait=wait,
                    installer_run=lambda args:self.fail("no installer without verification"),
                    relaunch=start,folder=folder)
            self.assertEqual(calls,["old-app-exited","recheck-release","old-app-restarted"])
            self.assertEqual(json.loads((folder/"update-status.json").read_text())["status"],"failed")

    def test_worker_restarts_previous_app_if_install_fails(self):
        blob=b"MZ"+b"x"*120_000
        rel=parse_release(release_data(blob=blob))
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/"Updates"
            installed=Path(td)/"Installed";installed.mkdir()
            app=installed/"JarvisNova.exe";app.write_bytes(b"MZlegacy")
            candidate=download_release(rel,folder,opener=FakeOpener(blob))
            restarted=[]
            with self.assertRaises(UpdateError):
                apply_update(candidate,app,rel.version,rel.sha256,10,
                             release_lookup=lambda:rel,wait=lambda pid:None,
                             installer_run=lambda argv:7,relaunch=restarted.append,folder=folder)
            self.assertEqual(len(restarted),1)
            self.assertEqual(restarted[0].resolve(),app.resolve())
            self.assertEqual(json.loads((folder/"update-status.json").read_text())["status"],"failed")

    def test_dev_python_run_never_checks_for_updates(self):
        from auto_update import installed_application
        self.assertIsNone(installed_application())
        with tempfile.TemporaryDirectory() as td:
            fake=Path(td)/"JarvisNova.exe";fake.write_bytes(b"MZtest")
            self.assertIsNone(installed_application(str(fake),frozen=True))
            (Path(td)/"JarvisNovaUpdater.exe").write_bytes(b"MZworker")
            self.assertEqual(installed_application(str(fake),frozen=True),fake)


if __name__=="__main__":
    unittest.main()
