# -*- coding: utf-8 -*-
"""Verify publication preparation never leaks credentials or uploads video."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlsplit

from creator_publish import (
    PORTALS, PublishDraft, PublishingError, clean_draft, prepared_caption,
    prepare_publish_package, open_upload_portal,
)


class PublishPreparationTests(unittest.TestCase):
    def fixture(self,root):
        video=Path(root)/"My Video.mp4"
        video.write_bytes(b"video-data"*150)
        return PublishDraft("youtube",video,"My first video",
                            "A short explanation","#JARVIS #edits")

    def test_official_portals_allowlisted_exactly_three_sites(self):
        self.assertEqual(set(PORTALS),{"youtube","tiktok","instagram"})
        expected={
            "youtube":"studio.youtube.com",
            "tiktok":"www.tiktok.com",
            "instagram":"www.instagram.com",
        }
        for key,(_,url) in PORTALS.items():
            with self.subTest(platform=key):
                p=urlsplit(url)
                self.assertEqual(p.scheme,"https")
                self.assertEqual(p.hostname,expected[key])
                self.assertIsNone(p.username)

    def test_opening_requires_user_approval_and_cannot_redirect_to_phishing(self):
        for key,(_,url) in PORTALS.items():
            browser=mock.Mock(return_value=True)
            with self.assertRaises(PermissionError):
                open_upload_portal(key,browser=browser)
            browser.assert_not_called()
            self.assertTrue(open_upload_portal(
                key,confirmed=True,browser=browser))
            browser.assert_called_once_with(url)
        browser=mock.Mock()
        with self.assertRaises(PublishingError):
            open_upload_portal("https://other.site",confirmed=True,browser=browser)
        browser.assert_not_called()

    def test_draft_is_non_destructive_and_explicitly_unpublished(self):
        with tempfile.TemporaryDirectory() as root:
            draft=self.fixture(root)
            original=Path(draft.video).read_bytes()
            directory=Path(root)
            with self.assertRaises(PermissionError):
                prepare_publish_package(draft,directory)
            file=prepare_publish_package(draft,directory,confirmed=True)
            data=json.loads(file.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"],"jarvis_publish_draft_v1")
            self.assertEqual(data["platform"],"youtube")
            self.assertEqual(data["video_sha256"],hashlib.sha256(original).hexdigest())
            self.assertFalse(data["uploaded"])
            self.assertFalse(data["published"])
            self.assertEqual(Path(draft.video).read_bytes(),original)
            self.assertIn("#JARVIS",prepared_caption(draft))
            with self.assertRaises(PublishingError):
                prepare_publish_package(draft,directory,confirmed=True)
            self.assertEqual(Path(draft.video).read_bytes(),original)

    def test_rejects_invalid_tags_long_titles_and_missing_video(self):
        with tempfile.TemporaryDirectory() as root:
            draft=self.fixture(root)
            for broken in (
                replace(draft,platform="other"),
                replace(draft,title="x"*101),
                replace(draft,title=""),
                replace(draft,hashtags="notag"),
                replace(draft,hashtags="#bad;cmd"),
                replace(draft,description="x"*5000),
                replace(draft,video=Path(root)/"missing.mp4"),
            ):
                with self.subTest(broken=broken), self.assertRaises(PublishingError):
                    clean_draft(broken)
            wrong=Path(root)/"private.txt"
            wrong.write_text("private",encoding="utf-8")
            with self.assertRaises(PublishingError):
                clean_draft(replace(draft,video=wrong))

    def test_no_online_actions_in_local_draft_function(self):
        with tempfile.TemporaryDirectory() as root:
            draft=self.fixture(root)
            with mock.patch("creator_publish.webbrowser.open_new_tab") as browser:
                prepare_publish_package(draft,Path(root),confirmed=True)
                browser.assert_not_called()


if __name__=="__main__":
    unittest.main()
