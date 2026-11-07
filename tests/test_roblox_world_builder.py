# -*- coding: utf-8 -*-
"""Roblox architectural map and prop plans; no live Studio integration claims."""
import json
from pathlib import Path
import tempfile
import unittest
from code_workspace import WorkspaceError, preview, apply_plan
from roblox_world_builder import (
    THEMES, MODELS, SIZES, build_world, build_model,
)


class RobloxWorldBuilderTests(unittest.TestCase):
    def test_all_six_roblox_themes_generate_editable_terrain(self):
        for theme in THEMES:
            with self.subTest(theme=theme),tempfile.TemporaryDirectory() as tmp:
                plan=build_world("SkyRealm",theme=theme,size=256,seed=2026)
                self.assertEqual(plan.language,"luau")
                self.assertEqual(len(plan.files),3)
                code=next(x.content for x in plan.files
                          if x.path=="tools/GenerateWorld.luau")
                self.assertIn("Terrain:FillBlock(",code)
                self.assertIn("Instance.new(\"Model\")",code)
                self.assertIn("Enum.Material.",code)
                self.assertIn("Lighting",code)
                self.assertIn("SpawnLocation",code)
                self.assertIn("Anchored=true",code)
                self.assertIn("MAX_PARTS",code)
                self.assertIn(f'local THEME="{theme}"',code)
                self.assertNotIn("Terrain:Clear(",code)
                self.assertNotIn("game:HttpGet(",code)
                self.assertNotIn("require(",code)
                self.assertNotIn("loadstring",code)
                self.assertNotIn("InsertService",code)
                with self.assertRaises(PermissionError):
                    apply_plan(plan,Path(tmp))
                paths=apply_plan(plan,Path(tmp),confirmed=True)
                self.assertEqual(len(paths),3)
                self.assertTrue((Path(tmp)/"tools/GenerateWorld.luau").exists())
                config=json.loads((Path(tmp)/"WORLD_DESIGN.json").read_text(encoding="utf-8"))
                self.assertEqual(config["theme"],theme)
                self.assertEqual(config["seed"],2026)
                self.assertTrue((Path(tmp)/"README.md").exists())

    def test_all_six_props_have_editable_parts(self):
        for kind in MODELS:
            with self.subTest(kind=kind):
                plan=build_model("StudioObject",model_type=kind)
                code=next(x.content for x in plan.files if x.path.endswith(".luau"))
                self.assertIn('local MODEL="'+kind+'"',code)
                self.assertIn("Enum.Material.",code)
                self.assertIn('part(',code)
                self.assertIn('world:SetAttribute("AssetType",MODEL)',code)
                self.assertNotIn("Terrain:Clear(",code)
                self.assertIn("View > Command Bar",
                              next(x.content for x in plan.files if x.path=="README.md"))

    def test_reproducible_seed_and_quality_configuration(self):
        a=build_world("Level",theme="island",size=512,quality="detailed",seed=421)
        b=build_world("Level",theme="island",size=512,quality="detailed",seed=421)
        self.assertEqual(a,b)
        brief=build_world("Level",theme="island",size=192,quality="balanced",seed=421)
        self.assertNotEqual(a,brief)
        self.assertIn("local SIZE=512",a.files[0].content)
        self.assertIn('local QUALITY="balanced"',brief.files[0].content)

    def test_rejects_invalid_names_and_parameters(self):
        for bad in ("../Danger","C:/evil","break script","", "a"*50):
            with self.subTest(bad=bad),self.assertRaises(WorkspaceError):
                build_world(bad)
        for kwargs in (
            dict(theme="invalid"),dict(size=9999),dict(quality="ultra"),
            dict(seed=-1),dict(seed=True),
        ):
            with self.subTest(opts=kwargs),self.assertRaises(WorkspaceError):
                build_world("Demo",**kwargs)
        with self.assertRaises(WorkspaceError):
            build_model("Demo",model_type="external_url")

    def test_generated_luau_is_only_a_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            script=build_model("Temple",model_type="castle")
            before=list(path.iterdir())
            self.assertEqual(before,[])
            entries=preview(script,path)
            self.assertEqual(len(entries),2)
            self.assertEqual(list(path.iterdir()),[])
            apply_plan(script,path,confirmed=True)
            self.assertTrue((path/"tools/GenerateModel.luau").is_file())
            self.assertEqual(preview(script,path)[0]["action"],"replace")

    def test_coding_gui_has_map_and_model_controls(self):
        source=(Path(__file__).resolve().parents[1]/"code_gui.py").read_text(encoding="utf-8")
        for phrase in ("Создать карту","Создать 3D-модель","build_world(",
                       "build_model(","Полный проект:"):
            self.assertIn(phrase,source)

if __name__=="__main__":
    unittest.main()
