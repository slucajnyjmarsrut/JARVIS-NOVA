# -*- coding: utf-8 -*-
"""One-confirmation chat workflow, no silent or repeated file export."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock
import queue
import tempfile
import threading

from video_timeline_ui import TimelineWindow
from video_timeline import TimelineCut, TimelineError


def dummy_window(token=None, *, cancelled=False):
    w=mock.Mock()
    w.winfo_exists.return_value=True
    w._events=queue.Queue()
    w._auto_export_token=token
    w._cancel=threading.Event()
    w._busy=False
    w._busy_since=None
    if cancelled:
        w._cancel.set()
    return w


class AutoLongformTests(TestCase):
    def test_explicit_one_time_permission_precedes_any_worker(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"two_hour.mp4"
            p.write_bytes(b"x"*3200)
            w=dummy_window()
            for allowed in (False,True):
                with self.subTest(allowed=allowed), \
                     mock.patch("video_timeline_ui.filedialog.askopenfilenames",
                                return_value=(str(p),)), \
                     mock.patch("video_timeline_ui.messagebox.askyesno",
                                return_value=allowed) as ask, \
                     mock.patch("video_timeline_ui.threading.Thread") as thread:
                    TimelineWindow.prepare_longform(w,auto_export=True)
                    ask.assert_called_once()
                    self.assertEqual(w._auto_export_token is not None,allowed)
                    thread.return_value.start.assert_called_once()

    def test_approved_completed_draft_queues_single_automatic_export(self):
        token=object()
        w=dummy_window(token)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"source.mp4"
            p.write_bytes(b"x"*3200)
            cuts=(TimelineCut(p,source_start=10,duration=900),)
            w._events.put(("longform",(cuts,Path(td)/"new.mp4",
                                      SimpleNamespace(usable=3,examined=3,audio_usable=2,audio_examined=3),token)))
            TimelineWindow._pump(w)
            w.aspect.set.assert_called_once_with("YouTube / Gaming 16:9")
            w.after_idle.assert_called_once()
            callback=w.after_idle.call_args.args[0]
            callback()
            w.export.assert_called_once_with(_approved_token=token)

    def test_no_approval_or_cancellation_never_autoexports(self):
        for cancelled,active in ((True,True),(False,False)):
            token=object()
            w=dummy_window(token if active else None,cancelled=cancelled)
            with tempfile.TemporaryDirectory() as td:
                p=Path(td)/"source.mp4"
                p.write_bytes(b"x"*3200)
                w._events.put(("longform",(
                    (TimelineCut(p,duration=900),),
                    Path(td)/"new.mp4",
                    SimpleNamespace(usable=0,examined=1,audio_usable=0,audio_examined=0),token)))
                TimelineWindow._pump(w)
                w.after_idle.assert_not_called()

    def test_expired_consent_cannot_be_reused_after_validation_failure(self):
        token=object()
        w=dummy_window(token)
        w._project.side_effect=TimelineError("invalid output")
        with mock.patch("video_timeline_ui.messagebox.showerror") as error:
            TimelineWindow.export(w,_approved_token=token)
        self.assertIsNone(w._auto_export_token)
        error.assert_called_once()
        w._project.assert_called_once_with(export=True)

    def test_stop_and_close_clear_pending_authorization(self):
        w=dummy_window(object())
        TimelineWindow.cancel(w)
        self.assertIsNone(w._auto_export_token)
        self.assertFalse(w._cancel.is_set())
        w._auto_export_token=object()
        TimelineWindow.close(w)
        self.assertIsNone(w._auto_export_token)
        w.destroy.assert_called_once()


if __name__=="__main__":
    import unittest
    unittest.main()
