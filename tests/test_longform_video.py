# -*- coding: utf-8 -*-
"""Two-hour source footage to a real 15-minute editable local timeline."""
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest

from long_video_limits import (
    MAX_SOURCE_SECONDS, MAX_OUTPUT_SECONDS, encode_timeout)
from video_timeline import (
    TimelineProject, TimelineCut, MAX_CUTS, MAX_TOTAL,
    draft_longform_cuts, validate_timeline, estimate_seconds)
from multitrack_composer import MultitrackProject, VisualLayer, validate_project
from pro_montage import ProOptions, finish_video
from popular_edits import verify_edit_output_media


class LongVideoTests(unittest.TestCase):
    def test_two_hour_source_drafts_fifteen_minutes_without_loading_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            source=folder/"two_hour.mp4"
            source.write_bytes(b"x"*3000)
            cuts=draft_longform_cuts(((source,2*3600.),),target_seconds=900.)
            self.assertGreater(len(cuts),10)
            self.assertLessEqual(len(cuts),MAX_CUTS)
            self.assertAlmostEqual(sum(c.duration for c in cuts),900.,delta=.01)
            self.assertTrue(all(0<=c.source_start<=7200-c.duration for c in cuts))
            self.assertTrue(all(c.duration>15. for c in cuts))
            project=TimelineProject(
                cuts=cuts,output=folder/"fifteen_minutes.mp4",
                transition_seconds=0)
            validate_timeline(project)
            self.assertAlmostEqual(estimate_seconds(project),900.,delta=.03)

    def test_multiple_long_sources_are_spread_across_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            one=folder/"one.mp4"
            two=folder/"two.mp4"
            one.write_bytes(b"x"*3000)
            two.write_bytes(b"x"*3000)
            cuts=draft_longform_cuts(
                ((one,7200.),(two,7200.)),target_seconds=900.)
            self.assertEqual({cut.path for cut in cuts},{one.resolve(),two.resolve()})
            self.assertAlmostEqual(sum(c.duration for c in cuts),900.,delta=.05)
            for cut in cuts:
                self.assertGreaterEqual(cut.source_start,0)
                self.assertLessEqual(cut.source_start+cut.duration,7200.001)

    def test_only_plans_possible_lengths_and_rejects_unsafe_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source.mp4"
            source.write_bytes(b"x"*3000)
            with self.assertRaisesRegex(Exception,"меньше"):
                draft_longform_cuts(((source,300.),),target_seconds=900.)
            with self.assertRaisesRegex(Exception,"длительност"):
                draft_longform_cuts(((source,float("inf")),),target_seconds=900.)
            with self.assertRaises(ValueError):
                encode_timeout(float("inf"))
            self.assertGreater(encode_timeout(900),900)
            self.assertGreaterEqual(MAX_SOURCE_SECONDS,2*3600)
            self.assertGreaterEqual(MAX_OUTPUT_SECONDS,900)

    def test_long_finisher_allows_fifteen_minutes_with_explicit_longform_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"seg.mp4"
            source.write_bytes(b"x"*3000)
            seen=[]
            result=finish_video(
                [source]*15,[60.]*15,root/"out.mp4","ffmpeg",
                options=ProOptions(transition=0),
                executor=lambda cmd,**kw:seen.append((cmd,kw)),
                max_clips=MAX_CUTS,max_duration=MAX_TOTAL)
            self.assertEqual(result["expected_seconds"],900.)
            self.assertGreater(seen[0][1]["timeout"],900)
            self.assertIn("-t",seen[0][0])

    def test_long_mp4_verifier_preserves_short_style_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/"rendered.mp4"
            video.write_bytes(b"x"*3000)
            info={"format":{"duration":"900.02"},"streams":[
                {"codec_type":"video","codec_name":"h264",
                 "width":1280,"height":720},
                {"codec_type":"audio","codec_name":"aac"}]}
            runner=lambda *a,**kw:json.dumps(info).encode()
            with self.assertRaises(Exception):
                verify_edit_output_media(
                    video,"ffprobe",size=(1280,720),expected_seconds=900,
                    executor=runner)
            record=verify_edit_output_media(
                video,"ffprobe",size=(1280,720),expected_seconds=900,
                executor=runner,max_duration=MAX_TOTAL)
            self.assertTrue(record["quality_checked"])

    def test_multitrack_accepts_long_footage_no_network_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            base=folder/"long.mp4"
            layer=folder/"logo.png"
            base.write_bytes(b"x"*3000)
            layer.write_bytes(b"x"*300)
            project=MultitrackProject(
                base,folder/"out.mp4",
                layers=(VisualLayer(layer,start=850.,duration=50.),))
            validate_project(project)
            self.assertFalse(project.output_video.exists())


if __name__=="__main__":
    unittest.main()
