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

    def test_popular_edits_simple_presets_preserve_editable_source_cuts(self):
        with tempfile.TemporaryDirectory() as temp:
            movie,original=project_fixture(temp)
            meta={
                "output":str(movie),"duration":2.78,
                "source_directory":original["source_directory"],
                "style":"shorts",
                "segments":[
                    {"source":"01.mp4","start":.25,"duration":1.5,"speed":1.0},
                    {"source":"02.mp4","start":2.0,"duration":1.5,"speed":1.0},
                ],
                "professional":{"transition":"fade","transition_seconds":.12},
            }
            movie.with_name(movie.stem+"_EDL.json").write_text(
                json.dumps(meta),encoding="utf-8")
            timeline,count=build_filmcraft_timeline(movie)
            self.assertEqual(count,2)
            clips=timeline["tracks"]["children"][0]["children"]
            self.assertEqual(
                [x["OTIO_SCHEMA"] for x in clips],
                ["Clip.2","Transition.1","Clip.2"])
            self.assertTrue(
                clips[0]["media_references"]["DEFAULT_MEDIA"]["target_url"]
                .endswith("01.mp4"))

            # Do NOT pretend that a velocity curve or wipe is represented
            # by a simple FilmCraft source-cut timeline.
            meta["segments"][1]["speed"]=1.8
            _,count=build_filmcraft_timeline(movie,meta)
            self.assertEqual(count,0)
            meta["segments"][1]["speed"]=1.
            meta["professional"]["transition"]="wipeleft"
            _,count=build_filmcraft_timeline(movie,meta)
            self.assertEqual(count,0)
            meta["professional"]["transition"]="dissolve"
            meta["segments"][0]["source"]="../private.mp4"
            _,count=build_filmcraft_timeline(movie,meta)
            self.assertEqual(count,0)

    def test_timeline_edl_imports_editable_cuts_but_respects_subtitles_velocity(self):
        with tempfile.TemporaryDirectory() as root:
            movie,fixture=project_fixture(root)
            folder=Path(fixture["source_directory"])
            metadata={
                "schema":"jarvis_timeline_v1",
                "output":str(movie),"duration":2.85,
                "subtitles":None,
                "cuts":[
                    {"path":str(folder/"01.mp4"),"source_start":.25,
                     "duration":1.5,"speed":1.0,"caption":"Клип 1"},
                    {"path":str(folder/"02.mp4"),"source_start":.2,
                     "duration":1.5,"speed":1.0,"caption":"Клип 2"},
                ],
                "render_info":{
                    "transition":"dissolve","transition_seconds":.15},
            }
            sidecar=movie.with_name(movie.stem+"_TIMELINE.json")
            sidecar.write_text(json.dumps(metadata),encoding="utf-8")
            timeline,count=build_filmcraft_timeline(movie)
            self.assertEqual(count,2)
            children=timeline["tracks"]["children"][0]["children"]
            self.assertEqual(
                [clip["OTIO_SCHEMA"] for clip in children],
                ["Clip.2","Transition.1","Clip.2"])
            self.assertEqual(len(timeline["tracks"]["markers"]),2)
            metadata["subtitles"]="subtitles.srt"
            _,count=build_filmcraft_timeline(movie,metadata)
            self.assertEqual(count,0)
            metadata["subtitles"]=None
            metadata["cuts"][1]["speed"]=1.5
            _,count=build_filmcraft_timeline(movie,metadata)
            self.assertEqual(count,0)
            metadata["cuts"][1]["speed"]=1.
            metadata["render_info"]["transition"]="wipeleft"
            _,count=build_filmcraft_timeline(movie,metadata)
            self.assertEqual(count,0)
            metadata["render_info"]["transition"]="fade"
            metadata["cuts"][0]["path"]=str(folder/"../private.mp4")
            _,count=build_filmcraft_timeline(movie,metadata)
            self.assertEqual(count,0)

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
            self.assertEqual(Path(recorded[0][-1]).resolve(),movie.resolve())
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
            self.assertEqual(Path(args[0][-1]).resolve(),movie.resolve())
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

    def test_filmcraft_download_denial_never_starts_network_or_worker(self):
        """An 'open editor' action cannot silently install a new executable."""
        from viral_studio_ui import ViralStudioWindow
        class FakeStatus:
            def __init__(self): self.value=""
            def set(self,text):self.value=text
        status=FakeStatus()
        dummy=SimpleNamespace(running=False,rendered_video=None,
                              filmcraft_exe=None,status=status)
        with patch("filmcraft_bridge.find_filmcraft",
                   side_effect=FilmCraftError("not installed")), \
             patch("viral_studio_ui.messagebox.askyesno",
                   return_value=False) as confirm, \
             patch.object(ViralStudioWindow,"_spawn") as spawn, \
             patch("filmcraft_installer.install_filmcraft") as download:
            ViralStudioWindow.open_filmcraft(dummy)
            confirm.assert_called_once()
            spawn.assert_not_called()
            download.assert_not_called()
            self.assertIn("отменена",status.value)

    def test_gui_and_production_menu_expose_button(self):
        # The lightweight CI test must not instantiate Tk, load models,
        # import old microphone modules or require an interactive display.
        root=Path(__file__).resolve().parents[1]
        gui=(root/"viral_studio_ui.py").read_text(encoding="utf-8")
        main=(root/"text_only_main.py").read_text(encoding="utf-8")
        self.assertIn("command=self.open_filmcraft",gui)
        self.assertIn("open_in_filmcraft",gui)
        palette=(root/"nova_command_palette.py").read_text(encoding="utf-8")
        self.assertIn("nova_command_palette import show_palette",main)
        self.assertIn("FilmCraft · открыть редактор",palette)


if __name__ == "__main__":
    unittest.main()
