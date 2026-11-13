# -*- coding: utf-8 -*-
"""Cross-subsystem safety: cancelled model streams, Tk dispatch, MP4 checkpoint."""
from dataclasses import asdict, replace
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase, mock
import unittest
from night_supervisor import NightSupervisor
from quick_video_brief import quick_brief
from topic_video_engine import TopicVideoError, _draw_card

def story(job, cb):
    brief=replace(quick_brief("Minecraft"),generator="локальная Gemma3:4b")
    return {"brief":asdict(brief),"model":"gemma3:4b"}

class CrossModuleReliability(TestCase):
    def test_model_stream_close_is_not_an_unhandled_thread_exception(self):
        from ollama_pull_client import _read_frames
        class Closed:
            def readline(self,size):
                raise AttributeError("'NoneType' object has no attribute 'close'")
        q=Queue()
        _read_frames(Closed(),q,Event())
        self.assertEqual(q.get_nowait()[0],"error")
        closing=Event()
        closing.set()
        quiet=Queue()
        _read_frames(Closed(),quiet,closing)
        self.assertTrue(quiet.empty())

    def test_specialist_window_worker_does_not_call_tk(self):
        from task_ai_hub import TaskAIHub
        win=mock.Mock()
        win._ui_events=Queue()
        seen=[]
        TaskAIHub._on_ui(win,lambda:seen.append(True))
        win.after.assert_not_called()
        win.winfo_exists.assert_not_called()
        TaskAIHub._drain_ui(win)
        self.assertEqual(seen,[True])
        win.after.assert_called_once_with(120,win._drain_ui)

    def test_mp4_pause_during_render_preserves_checkpoint(self):
        with TemporaryDirectory() as tmp:
            s=NightSupervisor(Path(tmp)/"jobs",executor=story)
            job=s.enqueue("topic_video","Minecraft",approved=True,allow_new_files=True)
            cancel=Event()
            def abort(brief,destination,*,cancel=None):
                self.assertIsNotNone(cancel)
                cancel.set()
                raise TopicVideoError("render interrupted")
            with mock.patch("topic_video_engine.render_topic_video",side_effect=abort):
                self.assertTrue(s.run_next(cancel=cancel))
            self.assertEqual(s.list_jobs()[0].status,"paused")
            self.assertEqual(s.list_jobs()[0].step,"verified")
            self.assertFalse((s.root/"outputs"/job).exists())
            s.resume(job,approved=True)
            def finish(brief,destination,*,cancel=None):
                (destination/"JARVIS_NOVA_FROM_TOPIC.mp4").write_bytes(b"video"*300)
            with mock.patch("topic_video_engine.render_topic_video",side_effect=finish):
                self.assertTrue(s.run_next())
            self.assertEqual(s.list_jobs()[0].status,"completed")

    def test_real_scene_art_changes_with_scenario(self):
        brief=replace(quick_brief("Minecraft"),generator="локальная Gemma3:4b")
        first=brief.shots[0]
        alternate=replace(first,film="Космический корабль рядом с планетой")
        with TemporaryDirectory() as tmp:
            a,b=Path(tmp)/"a.png",Path(tmp)/"b.png"
            _draw_card(brief,first,1,a,(180,320))
            _draw_card(brief,alternate,1,b,(180,320))
            self.assertNotEqual(a.read_bytes(),b.read_bytes())

if __name__=="__main__":
    unittest.main()
