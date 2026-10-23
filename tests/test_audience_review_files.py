# -*- coding: utf-8 -*-
"""Non-destructive audience review persistence without real user files."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from video_forecast import FinalReview, save_review
from viral_studio import ViralStudioError


def example_review():
    return FinalReview(81,"среднее соответствие","низкая",0,None,
        ({"check":"Монтаж","passed":True,"why":"корректно"},),
        ("Проверь файл вручную",),
        ("Просмотры нельзя предсказать",),12.5,"C:/output/ready.mp4")


class AudienceReviewPersistenceTests(unittest.TestCase):
    def test_two_reviews_have_distinct_json_and_markdown_versions(self):
        with TemporaryDirectory() as tmp:
            project=Path(tmp)
            first=save_review(example_review(),project)
            original_json=(project/"FINAL_AUDIENCE_REVIEW.json").read_bytes()
            original_md=first.read_bytes()
            second=save_review(example_review(),project)
            self.assertEqual(first.name,"FINAL_AUDIENCE_REVIEW_RU.md")
            self.assertEqual(second.name,"FINAL_AUDIENCE_REVIEW_RU_V2.md")
            self.assertEqual((project/"FINAL_AUDIENCE_REVIEW.json").read_bytes(),original_json)
            self.assertEqual(first.read_bytes(),original_md)
            self.assertTrue((project/"FINAL_AUDIENCE_REVIEW_V2.json").exists())
            self.assertEqual(json.loads((project/"FINAL_AUDIENCE_REVIEW_V2.json").read_text("utf-8"))["index"],81)

    def test_preexisting_notes_are_preserved_even_without_json(self):
        with TemporaryDirectory() as tmp:
            project=Path(tmp)
            notes=project/"FINAL_AUDIENCE_REVIEW_RU.md"
            notes.write_text("PRIVATE NOTES: DO NOT OVERWRITE",encoding="utf-8")
            path=save_review(example_review(),project)
            self.assertEqual(path.name,"FINAL_AUDIENCE_REVIEW_RU_V2.md")
            self.assertEqual(notes.read_text("utf-8"),"PRIVATE NOTES: DO NOT OVERWRITE")
            self.assertFalse((project/"FINAL_AUDIENCE_REVIEW.json").exists())
            self.assertTrue((project/"FINAL_AUDIENCE_REVIEW_V2.json").exists())

    def test_error_saving_markdown_rolls_back_own_json_only(self):
        with TemporaryDirectory() as tmp:
            project=Path(tmp)
            original=Path.open
            def fail_markdown(path,mode="r",*args,**kwargs):
                if path.name=="FINAL_AUDIENCE_REVIEW_RU.md" and mode=="x":
                    raise PermissionError("read-only destination")
                return original(path,mode,*args,**kwargs)
            with mock.patch("pathlib.Path.open",new=fail_markdown):
                with self.assertRaisesRegex(PermissionError,"read-only"):
                    save_review(example_review(),project)
            self.assertFalse((project/"FINAL_AUDIENCE_REVIEW.json").exists())
            self.assertFalse((project/"FINAL_AUDIENCE_REVIEW_RU.md").exists())

    def test_user_file_created_during_save_is_never_overwritten(self):
        with TemporaryDirectory() as tmp:
            project=Path(tmp)
            original=Path.open
            personal=project/"FINAL_AUDIENCE_REVIEW_RU.md"
            def concurrent_file(path,mode="r",*args,**kwargs):
                if path==personal and mode=="x":
                    personal.write_text("USER CONTENT",encoding="utf-8")
                    return original(path,mode,*args,**kwargs)
                return original(path,mode,*args,**kwargs)
            with mock.patch("pathlib.Path.open",new=concurrent_file):
                with self.assertRaises(FileExistsError):
                    save_review(example_review(),project)
            self.assertEqual(personal.read_text("utf-8"),"USER CONTENT")
            self.assertFalse((project/"FINAL_AUDIENCE_REVIEW.json").exists())


if __name__=="__main__":
    unittest.main()
