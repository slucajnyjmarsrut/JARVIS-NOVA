# -*- coding: utf-8 -*-
"""Read-only syntax/manifest audit of ALL checked-in JARVIS Python modules.

No source is imported or executed, no model downloaded. A passing result is
NOT evidence of functional correctness, model quality or installability.
"""
from __future__ import annotations
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FAMILIES={
    "models":("task_ai_registry.py","task_ai_hub.py","local_chat.py","scenario_specialist.py"),
    "scenarios":("video_scenario_autonomy.py","quick_video_brief.py"),
    "coding":("code_project_engine.py","code_agent.py","code_workspace.py","code_checks.py"),
    "video":("topic_video_engine.py","viral_studio.py","smart_montage.py","post_montage_review.py"),
    "vision":("screen_capture.py","screenshot_review.py","desktop.py"),
    "supervisor":("night_supervisor.py","night_supervisor_service.py","night_resource_guard.py","night_autorecovery.py"),
    "permissions":("startup_permissions.py","publisher_trust.py","code_autosave_policy.py"),
    "ui":("text_only_main.py","text_only_ui.py","nova_command_palette.py"),
    "installer":("bootstrap.py","updater_worker.py","auto_update.py","model_storage.py"),
}

def audit_sources(root=ROOT):
    root=Path(root)
    paths=sorted(set(root.glob("*.py")) |
                 set((root/"scripts").glob("*.py")) |
                 set((root/"tests").glob("*.py")))
    issues=[]
    for p in paths:
        try:
            ast.parse(p.read_text(encoding="utf-8"),filename=str(p))
        except (OSError,UnicodeError,ValueError,SyntaxError) as exc:
            issues.append({"path":str(p.relative_to(root)),
                           "error":type(exc).__name__,
                           "line":getattr(exc,"lineno",None)})
    families={}
    for family,files in FAMILIES.items():
        missing=[x for x in files if not (root/x).is_file()]
        families[family]={"source_modules":len(files),"present":not missing}
        issues.extend({"path":x,"error":"MissingCriticalModule"}
                      for x in missing)
    return {"source_files_checked":len(paths),"families":families,
            "issues":issues,
            "status":"passed" if paths and not issues else "failed",
            "verification":"syntax_and_manifest_only"}

def main():
    report=audit_sources()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["status"]=="passed" else 1

if __name__=="__main__":
    raise SystemExit(main())
