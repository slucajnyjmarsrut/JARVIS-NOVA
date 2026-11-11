# -*- coding: utf-8 -*-
"""Opt-in playback must never open websites or unwanted local files."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from video_preview import PreviewError, open_local_mp4


class LocalVideoPreviewTests(unittest.TestCase):
    def test_user_click_opens_only_verified_local_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            movie=base/"finished.mp4"
            movie.write_bytes(b"verified-output"*500)
            launched=Mock()
            with self.assertRaises(PermissionError):
                open_local_mp4(movie,opener=launched)
            launched.assert_not_called()
            opened=open_local_mp4(movie,confirmed=True,opener=launched)
            self.assertTrue(opened.samefile(movie))
            launched.assert_called_once_with(str(movie.resolve()))

    def test_invalid_path_and_existing_nonvideo_cannot_launch_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            short=folder/"short.mp4"
            short.write_bytes(b"tiny")
            secret=folder/"creds.txt"
            secret.write_bytes(b"do-not-open"*500)
            good=folder/"valid.mp4"
            good.write_bytes(b"movie"*500)
            no_path=folder/"missing.mp4"
            runner=Mock()
            for path in (short,secret,no_path,folder):
                with self.subTest(path=path),self.assertRaises(PreviewError):
                    open_local_mp4(path,confirmed=True,opener=runner)
            runner.assert_not_called()
            # A link cannot bypass extension, canonical location or type checks.
            shortcut=folder/"alias.mp4"
            try:
                shortcut.symlink_to(good)
            except (NotImplementedError,OSError):
                pass
            else:
                with self.assertRaises(PreviewError):
                    open_local_mp4(shortcut,confirmed=True,opener=runner)
                runner.assert_not_called()


if __name__=="__main__":
    unittest.main()
