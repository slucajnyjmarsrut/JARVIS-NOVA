# -*- coding: utf-8 -*-
"""No unattended installer runs without a pinned trusted publisher."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from publisher_trust import (
    PINNED_PUBLISHER_CERT_SHA256, PublisherTrustError,
    publisher_is_configured, require_publisher_ready,
    verify_installer_publisher,
)


class PublisherTrustTests(unittest.TestCase):
    def test_default_build_does_not_trust_any_unsigned_releases(self):
        self.assertEqual(PINNED_PUBLISHER_CERT_SHA256, "")
        self.assertFalse(publisher_is_configured())
        with self.assertRaises(PublisherTrustError):
            require_publisher_ready()

    def test_unconfigured_signer_blocks_download_before_network_or_fs(self):
        from auto_update import check_and_download
        network = mock.Mock(side_effect=AssertionError("must not query GitHub"))
        with self.assertRaises(PublisherTrustError):
            check_and_download(requester=network)
        network.assert_not_called()

    def test_exact_certificate_sha256_is_mandatory(self):
        certificate = b"\x30\x82" + b"CERT" * 100
        expected = hashlib.sha256(certificate).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / "candidate-0.5.19.exe"
            installer.write_bytes(b"MZ" + b"\x00" * 100)
            with mock.patch("publisher_trust.PINNED_PUBLISHER_CERT_SHA256",
                            expected):
                self.assertTrue(publisher_is_configured())
                verifier = mock.Mock(return_value=certificate)
                verify_installer_publisher(installer, signature_reader=verifier)
                verifier.assert_called_once_with(installer)
                with self.assertRaisesRegex(PublisherTrustError, "чужим"):
                    verify_installer_publisher(
                        installer, signature_reader=lambda _:b"X" * 100)
                with self.assertRaises(PublisherTrustError):
                    verify_installer_publisher(
                        installer, signature_reader=lambda _:b"")

    def test_trust_anchor_cannot_be_supplied_by_environment(self):
        certificate=b"publisher-der" * 20
        forged=hashlib.sha256(certificate).hexdigest()
        with mock.patch.dict("os.environ",
                             {"JARVIS_NOVA_SIGNER_SHA256":forged}):
            self.assertFalse(publisher_is_configured())
            with self.assertRaises(PublisherTrustError):
                require_publisher_ready()

    def test_untrusted_helper_cannot_stage_an_update(self):
        from auto_update import Release, stage_helper
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            appdir=root/"app"
            appdir.mkdir()
            app=appdir/"JarvisNova.exe"
            app.write_bytes(b"MZold")
            (appdir/"JarvisNovaUpdater.exe").write_bytes(b"MZworker")
            installer=root/"candidate-0.5.19.exe"
            installer.write_bytes(b"MZ" + b"\x00"*130_000)
            release=Release(
                "0.5.19", "JARVIS-NOVA-0.5.19-OFFLINE-SETUP.exe",
                "https://github.com/slucajnyjmarsrut/JARVIS-NOVA/releases/download/v0.5.19/JARVIS-NOVA-0.5.19-OFFLINE-SETUP.exe",
                hashlib.sha256(installer.read_bytes()).hexdigest(),
                installer.stat().st_size,
            )
            launcher=mock.Mock(side_effect=AssertionError("never launch"))
            with self.assertRaises(PublisherTrustError):
                stage_helper(release,installer,app,root/"cache",launcher=launcher)
            launcher.assert_not_called()
            self.assertFalse((root/"cache").exists())
            self.assertTrue(app.is_file())

    def test_worker_does_not_execute_unsigned_release_or_discard_old_app(self):
        from auto_update import Release
        from updater_worker import apply_update
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/"updates"
            folder.mkdir()
            appdir=root/"app"
            appdir.mkdir()
            app=appdir/"JarvisNova.exe"
            app.write_bytes(b"MZold")
            installer=folder/"candidate-0.5.19.exe"
            blob=b"MZ"+b"\0"*130_000
            installer.write_bytes(blob)
            release=Release(
                "0.5.19", "JARVIS-NOVA-0.5.19-OFFLINE-SETUP.exe",
                "https://github.com/slucajnyjmarsrut/JARVIS-NOVA/releases/download/v0.5.19/JARVIS-NOVA-0.5.19-OFFLINE-SETUP.exe",
                hashlib.sha256(blob).hexdigest(),len(blob))
            runner=mock.Mock(side_effect=AssertionError("installer must not run"))
            restart=mock.Mock()
            with self.assertRaises(PublisherTrustError):
                apply_update(
                    installer,app,release.version,release.sha256,312,
                    release_lookup=lambda:release,wait=lambda pid:None,
                    installer_run=runner,relaunch=restart,folder=folder)
            runner.assert_not_called()
            restart.assert_called_once_with(app)
            self.assertEqual(app.read_bytes(),b"MZold")
            self.assertEqual(installer.read_bytes(),blob)

    @unittest.skipUnless(sys.platform == "win32", "Windows Authenticode only")
    def test_windows_rejects_fake_exe_even_if_attacker_knows_fingerprint(self):
        from publisher_trust import _read_windows_authenticode_signer
        with tempfile.TemporaryDirectory() as directory:
            fake=Path(directory)/"Unsigned.exe"
            fake.write_bytes(b"MZ" + b"x" * 1000)
            with self.assertRaises(PublisherTrustError):
                _read_windows_authenticode_signer(fake)


if __name__ == "__main__":
    unittest.main()
