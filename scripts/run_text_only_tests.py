# -*- coding: utf-8 -*-
"""Text-only production regression suite. Legacy voice tests live in the repo
but are NOT part of the text-only Windows installer build.
"""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TESTS=(
       "test_audience_pipeline.py",
       "test_audience_review_files.py",
       "test_auto_update.py",
       "test_update_center.py",
       "test_lite_edition.py",
       "test_autonomous_montage.py",
       "test_bootstrap.py",
       "test_code_agent.py",
       "test_code_autopilot.py",
       "test_code_edits.py",
       "test_code_integration_smoke.py",
       "test_code_intent.py",
       "test_code_workspace.py",
       "test_editing_knowledge.py",
       "test_faster_app_routes.py",
       "test_filmcraft_bridge.py",
       "test_filmcraft_installer.py",
       "test_freellm_client.py",
       "test_game_video_modes.py",
       "test_installer_appearance.py",
       "test_installer_contract.py",
       "test_local_chat.py",
       
       "test_nova_window_state.py",
       "test_online_media.py",
       "test_overlay_commands.py",
       "test_post_montage_review.py",
       "test_pro_montage.py",
       "test_pro_video_integration.py",
       "test_roblox_asset_pipeline.py",
       "test_roblox_world_builder.py",
       "test_self_improve.py",
       "test_self_repair.py",
       "test_smart_montage.py",
       "test_text_only_mode.py",
       "test_universal_code_engine.py",
       "test_video_quality_modules.py",
       "test_viral_integration.py",
       "test_viral_studio.py",
       "test_vision_chat_protocol.py",
       "test_work_modes.py",
       "test_text_only_bundle.py",)

def main():
    suite=unittest.TestSuite()
    loader=unittest.TestLoader()
    for filename in TESTS:
        if not (ROOT/"tests"/filename).is_file():
            raise SystemExit("Missing mandatory production suite: "+filename)
        suite.addTests(loader.discover(str(ROOT/"tests"),pattern=filename,
                                       top_level_dir=str(ROOT/"tests")))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1

if __name__=="__main__":
    raise SystemExit(main())
