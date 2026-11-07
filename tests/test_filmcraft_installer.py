# -*- coding: utf-8 -*-
"""One-click FilmCraft portable installer: offline, hermetic security tests."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request
import zipfile

import filmcraft_installer as install
from filmcraft_bridge import find_filmcraft


def fake_archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("FilmCraft/filmcraft.exe", b"MZ" + b"\0" * 120)
        z.writestr("FilmCraft/filmcraft-cli.exe", b"MZ" + b"\0" * 120)
        z.writestr("FilmCraft/assets/icon.png", b"\x89PNG\x00" * 30)
    return output.getvalue()


class FakeResponse(io.BytesIO):
    def __init__(self, payload, url=None):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}
        self.url = url or install.FILMCRAFT_URL

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, payload, url=None):
        self.payload = payload
        self.url = url
        self.downloads = 0

    def open(self, request, *, timeout):
        assert timeout > 0
        assert isinstance(request, urllib.request.Request)
        self.downloads += 1
        return FakeResponse(self.payload, self.url)


class FilmCraftInstallerTests(unittest.TestCase):
    def test_pinned_official_release_metadata(self):
        self.assertEqual(install.FILMCRAFT_VERSION, "v0.18.0")
        self.assertEqual(len(install.FILMCRAFT_SHA256), 64)
        self.assertIn("https://github.com/storytold/filmcraft/releases/download/",
                      install.FILMCRAFT_URL)
        self.assertGreater(install.FILMCRAFT_ARCHIVE_BYTES, 100_000_000)

    def test_first_click_downloads_once_second_click_reuses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "FilmCraftApps"
            payload = fake_archive()
            opener = FakeOpener(payload)
            events = []
            with mock.patch.object(install, "FILMCRAFT_ARCHIVE_BYTES", len(payload)), \
                 mock.patch.object(install, "FILMCRAFT_SHA256",
                                   hashlib.sha256(payload).hexdigest()):
                first = install.install_filmcraft(
                    root=root, opener=opener,
                    progress=lambda stage,current,total: events.append(
                        (stage,current,total)))
                self.assertTrue(first.exists())
                self.assertEqual(first.name, "filmcraft.exe")
                self.assertEqual(first.with_name("filmcraft-cli.exe").exists(), True)
                self.assertEqual(first, install.installed_executable(root))
                second = install.install_filmcraft(root=root, opener=opener)
                self.assertEqual(first, second)
                self.assertEqual(opener.downloads, 1)
                self.assertTrue((root / install.FILMCRAFT_VERSION /
                                ".jarvis_filmcraft_sha256").exists())
                self.assertFalse(list(root.glob(".filmcraft-install-*")))
                self.assertIn("download", [x[0] for x in events])
                self.assertIn("unpack", [x[0] for x in events])
                self.assertIn("ready", [x[0] for x in events])

    def test_filmcraft_discovery_finds_auto_installed_app(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / install.FILMCRAFT_VERSION / "sub"
            folder.mkdir(parents=True)
            exe = folder / "filmcraft.exe"
            exe.write_bytes(b"exe")
            exe.with_name("filmcraft-cli.exe").write_bytes(b"cli")
            (folder.parent / ".jarvis_filmcraft_sha256").write_text(
                install.FILMCRAFT_SHA256, encoding="ascii")
            with mock.patch.object(install, "default_install_root",
                                   return_value=root):
                self.assertEqual(find_filmcraft(), exe.resolve())

    def test_tampered_archive_fails_and_leaves_no_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Apps"
            payload = fake_archive()
            with mock.patch.object(install, "FILMCRAFT_ARCHIVE_BYTES", len(payload)):
                with self.assertRaisesRegex(
                    install.FilmCraftInstallError, "SHA-256"):
                    install.install_filmcraft(
                        root=root, opener=FakeOpener(payload))
            self.assertIsNone(install.installed_executable(root))
            self.assertFalse(list(root.iterdir()))

    def test_truncated_archive_fails_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Apps"
            with self.assertRaises(install.FilmCraftInstallError):
                install.install_filmcraft(
                    root=root, opener=FakeOpener(fake_archive()[:20]))
            self.assertFalse(list(root.iterdir()))

    def test_cancellation_prevents_external_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            cancel = threading.Event()
            cancel.set()
            opener = FakeOpener(fake_archive())
            with self.assertRaisesRegex(install.FilmCraftInstallError,
                                        "отменено"):
                install.install_filmcraft(root=Path(temp)/"Apps",
                                         cancel=cancel, opener=opener)
            self.assertEqual(opener.downloads, 0)

    def test_preexisting_folder_not_deleted_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / install.FILMCRAFT_VERSION
            folder.mkdir()
            marker = folder / "important_user_project.fcproj"
            marker.write_text("Do not delete")
            with self.assertRaisesRegex(
                install.FilmCraftInstallError, "уже существует"):
                install.install_filmcraft(root=root, opener=FakeOpener(fake_archive()))
            self.assertEqual(marker.read_text(), "Do not delete")

    def test_zip_traversal_is_rejected(self):
        names = ("../evil.txt", "/windows/system32/evil.txt",
                 "nested\\evil.exe", "C:/Windows/evil.txt",
                 "FilmCraft/../evil.txt", "NUL.txt", "hidden/file. ")
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                archived = folder / "attack.zip"
                with zipfile.ZipFile(archived, "w") as z:
                    z.writestr(name, "attack")
                with self.assertRaises(install.FilmCraftInstallError):
                    install._unpack(archived, folder / "safe")
                self.assertFalse((folder / "evil.txt").exists())

    def test_zip_symlinks_and_duplicate_case_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archived = Path(tmp) / "bad.zip"
            symlink = zipfile.ZipInfo("FilmCraft/link")
            symlink.create_system = 3
            symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archived, "w") as z:
                z.writestr(symlink, "../../outside")
            with self.assertRaises(install.FilmCraftInstallError):
                install._unpack(archived, Path(tmp) / "unpack")
        with tempfile.TemporaryDirectory() as tmp:
            archived = Path(tmp) / "duplicate.zip"
            with zipfile.ZipFile(archived, "w") as z:
                z.writestr("FilmCraft/HELP.TXT", "1")
                z.writestr("filmcraft/help.txt", "2")
            with self.assertRaises(install.FilmCraftInstallError):
                install._unpack(archived, Path(tmp) / "unpack")

    def test_redirects_only_to_trusted_https_hosts(self):
        handler=install._RestrictedRedirects()
        request=urllib.request.Request(install.FILMCRAFT_URL)
        for url in ("http://github.com/path",
                    "https://malware.example/filmcraft.zip",
                    "https://username:password@github.com/file.zip",
                    "file:///tmp/filmcraft.zip"):
            with self.subTest(url=url), self.assertRaises(
                install.FilmCraftInstallError):
                handler.redirect_request(request,None,302,"",{},url)

    def test_gui_launch_click_downloads_without_open_file_dialog(self):
        root = Path(__file__).resolve().parents[1]
        ui = (root/"viral_studio_ui.py").read_text(encoding="utf-8")
        method = ui.split("    def open_filmcraft(self):", 1)[1].split(
            "    def _choose_music(self):", 1)[0]
        self.assertIn("install_filmcraft(", method)
        self.assertIn("open_in_filmcraft(", method)
        self.assertNotIn("askopenfilename(", method)
        self.assertIn("self._spawn(worker)", method)


if __name__ == "__main__":
    unittest.main()
