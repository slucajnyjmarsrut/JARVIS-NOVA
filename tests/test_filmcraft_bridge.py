# -*- coding: utf-8 -*-
"""JARVIS→FilmCraft manual-edit handoff. No network or real editor required."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from filmcraft_bridge import (
    FilmCraftError, build_filmcraft_timeline, find_filmcraft,
    open_in_filmcraft, FILMCRAFT_DOWNLOAD,
)


def project_fixture(home, *, originals=True):
    home = Path(home)
    video = home / "JARVIS_NOVA_VERTICAL.mp4"
    video.write_bytes(b"test-mp4" * 350)
    raw = home / "source"
    raw.mkdir()
    if originals:
        for name in ("01.mp4", "02.mp4"):
            (raw / name).write_bytes(b"original-video" * 400)
    meta = {
        "output": str(video), "duration": 2.78,
        "source_directory": str(raw),
        "segments": [
            {"file": "01.mp4", "start": .25, "seconds": 1.5,
             "on_screen": "Первый титр"},
            {"file": "02.mp4", "start": 2.0, "seconds": 1.5,
             "on_screen": "Второй титр"},
        ],
        "professional": {"transition_seconds": .22, "music_used": True}
    }
    return video, meta


class FilmCraftBridgeTests(unittest.TestCase):
    def test_validates_windows_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "FilmCraft.exe"
            app.write_bytes(b"exe")
            self.assertEqual(find_filmcraft(app), app.resolve())
            with self.assertRaises(FilmCraftError):
                find_filmcraft(Path(temp) / "unknown.exe")
        self.assertIn("getfilmcraft.org", FILMCRAFT_DOWNLOAD)

    def test_editable_otio_preserves_sources_and_cuts(self):
        with tempfile.TemporaryDirectory() as temp:
            video, meta = project_fixture(temp)
            timeline, originals = build_filmcraft_timeline(video, meta)
            self.assertEqual(originals, 2)
            self.assertEqual(timeline["OTIO_SCHEMA"], "Timeline.1")
            tracks = timeline["tracks"]["children"]
            self.assertEqual(tracks[0]["kind"], "Video")
            self.assertEqual(tracks[1]["kind"], "Audio")
            v1 = tracks[0]["children"]
            self.assertEqual([x["OTIO_SCHEMA"] for x in v1],
                             ["Clip.2", "Transition.1", "Clip.2"])
            self.assertAlmostEqual(
                v1[0]["source_range"]["start_time"]["value"], 7.5)
            self.assertTrue(v1[2]["media_references"]["DEFAULT_MEDIA"]
                            ["target_url"].endswith("02.mp4"))
            self.assertEqual(tracks[1]["children"][0]
                             ["media_references"]["DEFAULT_MEDIA"]["target_url"],
                             video.resolve().as_uri())
            self.assertEqual(len(timeline["tracks"]["markers"]), 2)
            self.assertEqual(timeline["tracks"]["markers"][1]["comment"],
                             "Второй титр")

    def test_missing_clips_reverts_to_rendered_mp4(self):
        with tempfile.TemporaryDirectory() as temp:
            video, meta = project_fixture(temp, originals=False)
            timeline, original_count = build_filmcraft_timeline(video, meta)
            self.assertEqual(original_count, 0)
            self.assertEqual(len(timeline["tracks"]["children"][0]["children"]), 1)
            path = timeline["tracks"]["children"][0]["children"][0]
            self.assertIn(video.name, path["media_references"]
                          ["DEFAULT_MEDIA"]["target_url"])

    def test_edl_rejects_traversal_and_never_uses_foreign_clips(self):
        with tempfile.TemporaryDirectory() as temp:
            movie, meta = project_fixture(temp)
            for name in ("../outside.mp4", r"..\outside.mp4", "/private/a.mp4"):
                bad = dict(meta, segments=[dict(meta["segments"][0], file=name)])
                timeline, originals = build_filmcraft_timeline(movie, bad)
                self.assertEqual(originals, 0)
                self.assertEqual(len(timeline["tracks"]["children"][0]["children"]), 1)

    def test_saves_native_project_and_launches_without_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            exe = home / "filmcraft.exe"
            exe.write_bytes(b"executable")
            cli = home / "filmcraft-cli.exe"
            cli.write_bytes(b"cli")
            movie, meta = project_fixture(temp)
            called, starts = [], []
            def runner(args, **kwargs):
                called.append((args, kwargs))
                self.assertEqual(args[0], str(cli.resolve()))
                self.assertEqual(args[1], "--save-as")
                self.assertEqual(args[3], "import")
                self.assertTrue(Path(args[4]).exists())
                self.assertFalse(kwargs["shell"])
                Path(args[2]).write_text(json.dumps({
                    "format": "filmcraft.project", "project": {"name": "Test"}}),
                    encoding="utf-8")
                return SimpleNamespace(returncode=0)
            def launch(args, **kwargs):
                starts.append((args, kwargs))
                return SimpleNamespace(pid=42)
            result = open_in_filmcraft(exe, movie, metadata=meta,
                                       runner=runner, launcher=launch)
            self.assertEqual(result.mode, "project")
            self.assertEqual(result.source_count, 2)
            self.assertTrue(result.project.is_file())
            self.assertTrue(result.timeline.is_file())
            self.assertEqual(starts[0][0], [str(exe.resolve()),str(result.project)])
            self.assertFalse(starts[0][1]["shell"])
            self.assertFalse(called[0][1]["shell"])
            contents = result.project.read_bytes()
            second = open_in_filmcraft(exe, movie, metadata=meta,
                                        runner=runner, launcher=launch)
            self.assertNotEqual(result.project, second.project)
            self.assertEqual(result.project.read_bytes(), contents)

    def test_cli_failure_keeps_otio_and_opens_mp4(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / "filmcraft.exe").write_bytes(b"bin")
            (home / "filmcraft-cli.exe").write_bytes(b"bin")
            movie, meta = project_fixture(home)
            recorded = []
            result = open_in_filmcraft(
                home / "filmcraft.exe", movie, metadata=meta,
                runner=lambda *a, **kw: SimpleNamespace(returncode=1),
                launcher=lambda args,**kwargs: recorded.append(args))
            self.assertEqual(result.mode, "video")
            self.assertIsNone(result.project)
            self.assertTrue(result.timeline.is_file())
            self.assertEqual(recorded[0][-1], str(movie))
            self.assertEqual(list(home.glob("*.fcproj")), [])

    def test_without_cli_opens_rendered_file(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)
            (home / "filmcraft.exe").write_bytes(b"exe")
            movie, meta = project_fixture(temp)
            args=[]
            result=open_in_filmcraft(home / "filmcraft.exe", movie,
                metadata=meta, launcher=lambda a,**kw:args.append(a))
            self.assertEqual(result.mode,"video")
            self.assertEqual(args[0][-1],str(movie))
            self.assertTrue(result.timeline.is_file())

    def test_empty_editor_opens_without_media(self):
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/"filmcraft.exe"
            exe.write_bytes(b"exe")
            opens=[]
            result=open_in_filmcraft(exe,launcher=lambda args,**kw:opens.append(args))
            self.assertEqual(result.mode,"empty")
            self.assertEqual(opens,[[str(exe.resolve())]])

    def test_refuses_invalid_mp4_or_renamed_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)
            exe=home/"filmcraft.exe"
            exe.write_bytes(b"exe")
            with self.assertRaises(FilmCraftError):
                open_in_filmcraft(exe,home/"missing.mp4",launcher=lambda *a,**kw:None)
            with self.assertRaises(FilmCraftError):
                open_in_filmcraft(home/"random.exe")

    def test_gui_and_production_menu_expose_button(self):
        # The lightweight CI test must not instantiate Tk, load models,
        # import old microphone modules or require an interactive display.
        root=Path(__file__).resolve().parents[1]
        gui=(root/"viral_studio_ui.py").read_text(encoding="utf-8")
        main=(root/"text_only_main.py").read_text(encoding="utf-8")
        self.assertIn("command=self.open_filmcraft",gui)
        self.assertIn("from filmcraft_bridge import open_in_filmcraft",gui)
        self.assertIn("FilmCraft — открыть редактор",main)


if __name__ == "__main__":
    unittest.main()
