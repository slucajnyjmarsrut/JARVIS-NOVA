# -*- coding: utf-8 -*-
"""Full source inventory; never starts Ollama or executes other source."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from scripts.audit_module_health import audit_sources

class ModuleInventoryTests(unittest.TestCase):
    def test_repository_modules_parse_and_families_present(self):
        report=audit_sources()
        self.assertEqual(report["status"],"passed",report["issues"][:8])
        self.assertGreater(report["source_files_checked"],200)
        self.assertGreaterEqual(len(report["families"]),9)
        self.assertEqual(report["verification"],"syntax_and_manifest_only")

    def test_missing_module_and_syntax_error_fail_closed(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"broken.py").write_text("def bad(:\n",encoding="utf-8")
            report=audit_sources(root)
            self.assertEqual(report["status"],"failed")
            errors=[e["error"] for e in report["issues"]]
            self.assertIn("SyntaxError",errors)
            self.assertIn("MissingCriticalModule",errors)

    def test_report_never_claims_real_model_quality(self):
        self.assertNotIn("real_llm_passed",audit_sources())
        self.assertNotIn("installer_passed",audit_sources())

if __name__=="__main__":
    unittest.main()
