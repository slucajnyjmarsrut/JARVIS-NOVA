# -*- coding: utf-8 -*-
"""Creator account enrollment opens only official sites on explicit approval."""
import inspect
import unittest
from unittest import mock
from urllib.parse import urlsplit

from creator_accounts import (
    SITES, creator_site, CreatorSignupError,
    open_creator_registration, open_creator_help, suggest_creator_handles,
    is_creator_signup_request,
)


class CreatorAccountTests(unittest.TestCase):
    def test_signup_command_only_opens_manual_registration(self):
        for question in ("создай аккаунт в ютубе", "зарегистрируй меня в TikTok",
                         "создать аккаунт Instagram", "создай канал на YouTube"):
            self.assertTrue(is_creator_signup_request(question),question)
        for unrelated in ("придумай название для ютуба", "опубликуй на тикток",
                          "отправь пароли в инстаграм", "создай эдит"):
            self.assertFalse(is_creator_signup_request(unrelated),unrelated)

    def test_all_three_platforms_have_fixed_https_official_hosts(self):
        self.assertEqual({site.key for site in SITES},
                         {"youtube", "tiktok", "instagram"})
        expected = {
            "youtube": "www.youtube.com",
            "tiktok": "www.tiktok.com",
            "instagram": "www.instagram.com",
        }
        for site in SITES:
            with self.subTest(site=site.key):
                parsed = urlsplit(site.signup_url)
                self.assertEqual(parsed.scheme, "https")
                self.assertEqual(parsed.hostname, expected[site.key])
                self.assertIsNone(parsed.username)
                self.assertIsNone(parsed.password)
                self.assertTrue(site.guide)
                self.assertEqual(urlsplit(site.help_url).scheme, "https")

    def test_account_creation_requires_explicit_opening_and_is_user_led(self):
        for site in SITES:
            browser=mock.Mock(return_value=True)
            with self.assertRaises(PermissionError):
                open_creator_registration(site.key, browser=browser)
            browser.assert_not_called()
            self.assertTrue(open_creator_registration(
                site.key, confirmed=True, browser=browser))
            browser.assert_called_once_with(site.signup_url)

    def test_invalid_service_cannot_inject_phishing_site(self):
        browser=mock.Mock()
        for value in ("http://evil.example", "../accounts", "tiktok.com.evil",
                      "", "google", "youtube://auth"):
            with self.subTest(value=value), self.assertRaises(CreatorSignupError):
                open_creator_registration(value, confirmed=True, browser=browser)
            browser.assert_not_called()

    def test_help_is_separately_permission_gated(self):
        browser=mock.Mock(return_value=True)
        with self.assertRaises(PermissionError):
            open_creator_help("tiktok", browser=browser)
        browser.assert_not_called()
        self.assertTrue(open_creator_help("tiktok", confirmed=True, browser=browser))
        browser.assert_called_once_with(creator_site("tiktok").help_url)

    def test_safe_username_ideas_are_not_claimed_as_available(self):
        names=suggest_creator_handles("Nova_Studio")
        self.assertEqual(len(names),4)
        self.assertTrue(all(name.startswith("nova_studio") for name in names))
        self.assertTrue(all(len(name)<=30 for name in names))
        for unsafe in ("", "!!", "a", "русский"):
            with self.assertRaises(CreatorSignupError):
                suggest_creator_handles(unsafe)

    def test_real_signup_window_scrolls_and_keeps_buttons_accessible(self):
        import tkinter as tk
        from creator_accounts_ui import CreatorAccountsWindow
        try:
            root=tk.Tk()
        except tk.TclError:
            self.skipTest("Graphical Tk display unavailable on this runner")
        root.withdraw()
        window=None
        try:
            window=CreatorAccountsWindow(root)
            window.geometry("500x510")
            window.update_idletasks()
            self.assertIsNotNone(window._scroll_canvas.bbox("all"))
            self.assertEqual(len(window._wrap_targets),5)
            canvas=window._scroll_canvas
            self.assertGreaterEqual(
                canvas.bbox("all")[3],int(canvas.winfo_height()))
            self.assertEqual(canvas.winfo_manager(),"pack")
            # Ensure actual controls are present even when panel content
            # is taller than the available screen area.
            self.assertEqual(len(window._scroll_panel.winfo_children()),8)
            canvas.yview_moveto(1.0)
            window.update_idletasks()
            self.assertTrue(0<=canvas.yview()[0]<=1)
        finally:
            if window is not None:
                window.destroy()
            root.destroy()

    def test_all_six_signup_and_help_button_paths_require_user_consent(self):
        """Neither a signup nor a help click can silently open the browser."""
        from types import SimpleNamespace
        from creator_accounts_ui import CreatorAccountsWindow
        target=SimpleNamespace(result=mock.Mock())
        with mock.patch("creator_accounts_ui.messagebox.askyesno",
                        return_value=False), \
             mock.patch("creator_accounts_ui.open_creator_registration") as reg, \
             mock.patch("creator_accounts_ui.open_creator_help") as help_open:
            for site in SITES:
                CreatorAccountsWindow._open(target,site.key)
                CreatorAccountsWindow._help(target,site.key)
            reg.assert_not_called()
            help_open.assert_not_called()
        with mock.patch("creator_accounts_ui.messagebox.askyesno",
                        return_value=True), \
             mock.patch("creator_accounts_ui.open_creator_registration",
                        return_value=True) as reg, \
             mock.patch("creator_accounts_ui.open_creator_help",
                        return_value=True) as help_open:
            for site in SITES:
                CreatorAccountsWindow._open(target,site.key)
                CreatorAccountsWindow._help(target,site.key)
            self.assertEqual(
                [call.args[0] for call in reg.call_args_list],
                [site.key for site in SITES])
            self.assertEqual(
                [call.args[0] for call in help_open.call_args_list],
                [site.key for site in SITES])
            self.assertTrue(all(call.kwargs=={"confirmed":True}
                                for call in reg.call_args_list))
            self.assertTrue(all(call.kwargs=={"confirmed":True}
                                for call in help_open.call_args_list))

    def test_ui_never_collects_passwords_sms_cookies_or_post_videos(self):
        from creator_accounts_ui import CreatorAccountsWindow
        source=inspect.getsource(CreatorAccountsWindow)
        self.assertIn("messagebox.askyesno", source)
        self.assertIn("open_creator_registration", source)
        self.assertNotIn("requests.post", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("password_entry", source)
        self.assertNotIn("oauth_token", source)


if __name__ == "__main__":
    unittest.main()
