# -*- coding: utf-8 -*-
"""Roblox self-contained glTF mesh geometry and SVG level-plan tests.

No Roblox account, network access, Blender or display is required.
These tests verify structural geometry, NOT the final Studio appearance.
"""
from __future__ import annotations

import base64
import json
import math
import struct
import unittest
from xml.etree import ElementTree as ET

from roblox_asset_pipeline import export_prop_gltf, make_map_svg
from roblox_world_builder import THEMES, MODELS, build_world, build_model
from code_workspace import validate_plan, WorkspaceError


class RobloxAssetPipelineTests(unittest.TestCase):
    def test_each_model_is_complete_offline_gltf_with_pbr_textures(self):
        for kind in MODELS:
            with self.subTest(kind=kind):
                source=export_prop_gltf("StudioItem",kind,seed=37)
                self.assertLess(len(source),300_000)
                scene=json.loads(source)
                self.assertEqual(scene["asset"]["version"],"2.0")
                self.assertGreater(len(scene["nodes"]),3)
                self.assertGreater(len(scene["meshes"]),1)
                self.assertGreater(len(scene["materials"]),1)
                self.assertEqual(scene["scenes"][0]["nodes"],
                                 list(range(len(scene["nodes"]))))
                uri=scene["buffers"][0]["uri"]
                self.assertTrue(uri.startswith("data:application/octet-stream;base64,"))
                raw=base64.b64decode(uri.split(",",1)[1],validate=True)
                self.assertEqual(len(raw),scene["buffers"][0]["byteLength"])
                self.assertGreater(len(raw),500)
                for image in scene["images"]:
                    self.assertTrue(image["uri"].startswith("data:image/png;base64,"))
                    data=base64.b64decode(image["uri"].split(",",1)[1],validate=True)
                    self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
                    self.assertGreater(len(data),60)
                for view in scene["bufferViews"]:
                    self.assertEqual(view["byteOffset"]%4,0)
                    self.assertGreater(view["byteLength"],0)
                    self.assertLessEqual(view["byteOffset"]+view["byteLength"],len(raw))
                for material in scene["materials"]:
                    pbr=material["pbrMetallicRoughness"]
                    self.assertIn("baseColorTexture",pbr)
                    self.assertIn("metallicRoughnessTexture",pbr)
                    self.assertTrue(0<=pbr["roughnessFactor"]<=1)
                    self.assertTrue(0<=pbr["metallicFactor"]<=1)
                for mesh in scene["meshes"]:
                    triangles=0
                    for prim in mesh["primitives"]:
                        self.assertEqual(prim["mode"],4)
                        attrs=prim["attributes"]
                        self.assertIn("POSITION",attrs)
                        self.assertIn("NORMAL",attrs)
                        self.assertIn("TEXCOORD_0",attrs)
                        pos=scene["accessors"][attrs["POSITION"]]
                        nrm=scene["accessors"][attrs["NORMAL"]]
                        uv=scene["accessors"][attrs["TEXCOORD_0"]]
                        self.assertEqual(pos["count"],nrm["count"])
                        self.assertEqual(pos["count"],uv["count"])
                        index=scene["accessors"][prim["indices"]]
                        self.assertEqual(index["type"],"SCALAR")
                        self.assertEqual(index["count"]%3,0)
                        indices_data=scene["bufferViews"][index["bufferView"]]
                        values=struct.unpack_from(
                            "<"+"H"*index["count"],raw,indices_data["byteOffset"])
                        self.assertTrue(values)
                        self.assertLess(max(values),pos["count"])
                        triangles+=index["count"]//3
                    self.assertLess(triangles,20_000)
                self.assertTrue(all("uri" not in node for node in scene["nodes"]))

    def test_geometry_has_outward_winding_for_box_sphere_cone(self):
        from roblox_asset_pipeline import _geometry
        for shape in ("box","cylinder","sphere","cone"):
            with self.subTest(shape=shape):
                verts,normals,uvs,indices=_geometry(shape)
                self.assertEqual(len(verts),len(normals))
                self.assertEqual(len(verts),len(uvs))
                self.assertTrue(all(-.51<=p<=.51 for row in verts for p in row))
                self.assertTrue(all(0<=p<=1 for row in uvs for p in row))
                self.assertLess(max(indices),len(verts))
                count=0
                for a,b,c in zip(indices[::3],indices[1::3],indices[2::3]):
                    p,q,r=verts[a],verts[b],verts[c]
                    u=tuple(q[i]-p[i] for i in range(3))
                    v=tuple(r[i]-p[i] for i in range(3))
                    cross=(u[1]*v[2]-u[2]*v[1],
                           u[2]*v[0]-u[0]*v[2],
                           u[0]*v[1]-u[1]*v[0])
                    avg=tuple(sum(normals[idx][i] for idx in (a,b,c))/3
                              for i in range(3))
                    sign=sum(cross[i]*avg[i] for i in range(3))
                    if abs(sign)>1e-7:
                        self.assertGreater(sign,0,f"{shape} triangle winding inverted")
                        count+=1
                self.assertGreater(count,4)

    def test_proposals_include_gltf_and_svg_and_are_deterministic(self):
        for kind in MODELS:
            plan=build_model("RobloxAsset",model_type=kind)
            validate_plan(plan)
            self.assertEqual(len(plan.files),3)
            mesh=next(p for p in plan.files if p.path.endswith(".gltf"))
            self.assertEqual(json.loads(mesh.content)["asset"]["version"],"2.0")
            self.assertEqual(plan,build_model("RobloxAsset",model_type=kind))
        for theme in THEMES:
            plan=build_world("RobloxMap",theme=theme,size=256)
            validate_plan(plan)
            self.assertEqual(len(plan.files),4)
            mapfile=next(p for p in plan.files if p.path.endswith(".svg"))
            document=ET.fromstring(mapfile.content)
            self.assertTrue(document.tag.endswith("svg"))
            self.assertGreaterEqual(len(mapfile.content),1000)
            self.assertEqual(plan,build_world("RobloxMap",theme=theme,size=256))

    def test_svg_contains_map_plan_but_no_scripts_or_external_assets(self):
        for theme in THEMES:
            svg=make_map_svg(theme,384,seed=42)
            self.assertIn("TOP-DOWN DESIGN CONCEPT",svg)
            self.assertNotIn("<script",svg)
            self.assertNotIn("https://",svg)
            self.assertNotIn("javascript:",svg)
            self.assertIn(theme.upper(),svg)
            ET.fromstring(svg)

    def test_rejects_untrusted_options_and_stays_bounded(self):
        for bad in ("../../outside","bad name","https://files.example"):
            with self.subTest(bad=bad),self.assertRaises((ValueError,WorkspaceError)):
                export_prop_gltf(bad,"house")
        for values in (("house",-1),("sci_fi_portal",True)):
            with self.subTest(values=values),self.assertRaises(ValueError):
                export_prop_gltf("Valid",values[0],seed=values[1])
        with self.assertRaises(ValueError):
            export_prop_gltf("Valid","player_rigged")
        with self.assertRaises(ValueError):
            make_map_svg("unknown",256)

    def test_gui_does_not_dump_encoded_mesh_into_tk_text(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        source=(root/"code_gui.py").read_text(encoding="utf-8")
        self.assertIn("if item.path.endswith('.gltf'):",source)
        self.assertIn("base64",source)
        self.assertIn("Создать карту + план",source)
        self.assertIn("Создать 3D-модель + PBR",source)


if __name__ == "__main__":
    unittest.main()
