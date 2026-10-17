"""Protocol-only tests: never claim this is real Vision inference."""
import unittest
from vision_engine import LocalOllamaVision, VisionConfig, VisionError


class VisionChatProtocolTests(unittest.TestCase):
    def test_qwen_vl_image_uses_chat_without_thinking(self):
        requests = []
        def fake(route, payload):
            requests.append((route, payload))
            if route == "/api/tags":
                return {"models": [{"name": "qwen3-vl:2b"}]}
            if route == "/api/show":
                return {"capabilities": ["vision", "completion"]}
            if route == "/api/chat":
                return {"message": {"role": "assistant", "content": "Красный квадрат."}}
            raise AssertionError(route)

        vision = LocalOllamaVision(VisionConfig(), transport=fake)
        vision.initialize()
        result = vision.describe("Какого цвета квадрат?", bytes([255, 216, 255]) + b"x" * 80 + bytes([255, 217]))
        self.assertEqual(result, "Красный квадрат.")
        route, payload = requests[-1]
        self.assertEqual(route, "/api/chat")
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(len(payload["messages"][0]["images"]), 1)
        self.assertNotIn("prompt", payload)

    def test_model_reasoning_without_final_content_is_not_fake_answer(self):
        def fake(route, payload):
            return {
                "/api/tags": {"models": [{"name": "qwen3-vl:2b"}]},
                "/api/show": {"capabilities": ["vision"]},
                "/api/chat": {"message": {"role": "assistant", "thinking": "some thoughts", "content": ""}},
            }[route]
        vision = LocalOllamaVision(VisionConfig(), transport=fake)
        vision.initialize()
        with self.assertRaisesRegex(VisionError, "no final answer"):
            vision.describe("Что на картинке?", bytes([255, 216, 255]) + b"x" * 80 + bytes([255, 217]))


if __name__ == "__main__":
    unittest.main()
