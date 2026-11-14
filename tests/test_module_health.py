# -*- coding: utf-8 -*-
"""Read-only capability checks cover model specialists, video, vision and RAM."""
import unittest
from unittest.mock import Mock
from pathlib import Path
from queue import Queue
from dataclasses import dataclass

from module_health import collect_health, HealthReport
from night_resource_guard import MemorySnapshot, MIB


class ModuleHealthTests(unittest.TestCase):
    def test_complete_healthy_local_installation(self):
        from task_ai_registry import get_specialist
        available=[get_specialist(r).model for r in
                   ("scenario","code","chat","montage")]
        report=collect_health(
            assets=Path("."),
            tags_fetcher=lambda:available,
            vision_checker=lambda assets:True,
            ffmpeg_finder=lambda:("ffmpeg","ffprobe"),
            memory_probe=lambda:MemorySnapshot(8_000*MIB,16_000*MIB),
            disk_probe=lambda:10 * 1024**3)
        self.assertIsInstance(report,HealthReport)
        self.assertEqual(len(report.items),12)
        statuses={x.name:x.status for x in report.items}
        self.assertEqual(statuses["ИИ-сценарист"],"ready")
        self.assertEqual(statuses["Локальное зрение"],"ready")
        self.assertEqual(statuses["Монтаж и MP4"],"ready")
        self.assertEqual(statuses["Оперативная память"],"ready")
        self.assertEqual(statuses["Свободное место"],"ready")
        self.assertEqual(statuses["Фоновый Supervisor"],"unknown")
        self.assertIn("готовы 8",report.summary())

    def test_missing_ollama_is_not_mislabeled_uninstalled(self):
        def fail():
            raise OSError("C:/Users/secret/token")
        report=collect_health(
            assets=None,tags_fetcher=fail,ffmpeg_finder=lambda:("ffmpeg","ffprobe"),
            memory_probe=lambda:None,disk_probe=lambda:1)
        self.assertTrue(all(x.status=="unknown" for x in report.items[:5]))
        self.assertEqual(report.items[6].status,"unknown")
        self.assertEqual(report.items[7].status,"warning")
        self.assertNotIn("secret",str(report))

    def test_no_disk_or_video_does_not_start_tools(self):
        ffmpeg=Mock(side_effect=OSError("missing"))
        report=collect_health(
            tags_fetcher=lambda:(),ffmpeg_finder=ffmpeg,
            memory_probe=lambda:MemorySnapshot(10*MIB,8_000*MIB),
            disk_probe=lambda: (_ for _ in ()).throw(OSError("drive offline")))
        self.assertEqual(report.items[5].status,"missing")
        self.assertEqual(report.items[6].status,"warning")
        self.assertEqual(report.items[7].status,"unknown")
        ffmpeg.assert_called_once_with()

    def test_unknown_model_inventory_distinct_from_missing_model(self):
        def inspect(tags):
            return collect_health(
                tags_fetcher=lambda: tags,
                ffmpeg_finder=lambda:("ffmpeg","ffprobe"),
                memory_probe=lambda:MemorySnapshot(4_000*MIB,8_000*MIB),
                disk_probe=lambda: 8*1024**3)
        self.assertTrue(all(x.status=="missing" for x in inspect(()).items[:4]))
        self.assertTrue(all(x.status=="ready" for x in inspect((
            "gemma3:4b", "qwen2.5-coder:7b", "qwen3:4b",
            "llama3.2:3b")).items[:4]))

    def test_health_window_worker_queue_contract_is_visible(self):
        import inspect
        from module_health_ui import ModuleHealthWindow
        source=inspect.getsource(ModuleHealthWindow)
        self.assertIn("self._events.put",source)
        self.assertIn("def _pump",source)
        self.assertNotIn("self.after(0",source)
        self.assertNotIn("requests.post",source)


if __name__=="__main__":
    unittest.main()
