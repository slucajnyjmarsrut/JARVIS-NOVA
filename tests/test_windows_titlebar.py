# -*- coding: utf-8 -*-
"""Regression: dark native Windows captions are safe on 64-bit Tk windows."""
import ctypes
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from windows_titlebar import (
    _colorref, apply_dark_titlebar, install_dark_titlebar,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeWindow:
    def winfo_exists(self):
        return True

    def winfo_id(self):
        return 0x123456789ABCDEF

    def bind(self, name, callback, add=None):
        self.binding = (name, callback, add)

    def after(self, delay, callback):
        self.scheduled = getattr(self, "scheduled", []) + [(delay, callback)]

    def after_idle(self, callback):
        self.idle_callback = callback


class TitlebarTests(unittest.TestCase):
    def test_colorref_has_win32_byte_order(self):
        self.assertEqual(_colorref("#112233"), 0x332211)
        self.assertEqual(_colorref("#081421"), 0x211408)
        with self.assertRaises(ValueError):
            _colorref("#ABC")

    def test_no_win32_calls_on_other_platforms(self):
        window = FakeWindow()
        with patch.object(sys, "platform", "linux"):
            self.assertFalse(apply_dark_titlebar(window))
            install_dark_titlebar(window)
        self.assertFalse(hasattr(window, "binding"))

    def test_uses_full_width_native_hwnd_and_refreshes_frame(self):
        window = FakeWindow()
        root_handle = 0x123456789ABCDE0
        ancestor = Mock(return_value=root_handle)
        dwm = Mock(return_value=0)
        pos = Mock(return_value=1)
        winapi = SimpleNamespace(
            user32=SimpleNamespace(GetAncestor=ancestor, SetWindowPos=pos),
            dwmapi=SimpleNamespace(DwmSetWindowAttribute=dwm),
        )
        with patch.object(sys, "platform", "win32"), \
                patch.object(ctypes, "windll", winapi, create=True):
            self.assertTrue(apply_dark_titlebar(
                window, background="#081421", foreground="#EAF5FC"))
        self.assertEqual(ancestor.call_args.args, (window.winfo_id(), 2))
        self.assertEqual(ancestor.restype, ctypes.wintypes.HWND)
        calls = dwm.call_args_list
        self.assertEqual([call.args[1] for call in calls], [20, 35, 36])
        self.assertTrue(all(call.args[0] == root_handle for call in calls))
        self.assertEqual(pos.call_args.args, (root_handle, None, 0, 0, 0, 0, 0x37))

    def test_legacy_dark_mode_falls_back_to_19(self):
        window = FakeWindow()
        ancestor = Mock(return_value=window.winfo_id())
        dwm = Mock(side_effect=lambda hwnd, attr, pointer, size: -1 if attr == 20 else 0)
        winapi = SimpleNamespace(
            user32=SimpleNamespace(GetAncestor=ancestor, SetWindowPos=Mock()),
            dwmapi=SimpleNamespace(DwmSetWindowAttribute=dwm),
        )
        with patch.object(sys, "platform", "win32"), \
                patch.object(ctypes, "windll", winapi, create=True):
            self.assertTrue(apply_dark_titlebar(window))
        self.assertEqual([call.args[1] for call in dwm.call_args_list],
                         [20, 19, 35, 36])

    def test_install_retries_after_window_is_mapped(self):
        window = FakeWindow()
        with patch.object(sys, "platform", "win32"):
            install_dark_titlebar(window)
            install_dark_titlebar(window)
        self.assertEqual(window.binding[0], "<Map>")
        self.assertEqual(window.binding[2], "+")
        self.assertEqual([delay for delay, _ in window.scheduled], [100, 700])
        window.binding[1](SimpleNamespace(widget=window))
        self.assertTrue(callable(window.idle_callback))

    def test_both_windows_request_native_dark_caption(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        studio = (ROOT / "viral_studio_ui.py").read_text(encoding="utf-8")
        self.assertIn("install_dark_titlebar(self, background=\"#070D17\")", main)
        self.assertIn("install_dark_titlebar(self, background=BG)", studio)


if __name__ == "__main__":
    unittest.main()
