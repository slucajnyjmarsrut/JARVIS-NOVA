"""Protocol-only tests: never claim this is real Vision inference."""
import unittest
from vision_engine import LocalOllamaVision, VisionConfig, VisionError


class VisionChatProtocolTests(unittest.TestCase):
    def test_qwen_vl_image_uses_chat_without_thinking(self):
        requests = []
        def fake(route, payload):
            requests.append((route, payload))
            if route == "/api/tags":
                return {"models": [{"name": "qwen3-vl:2b-instruct"}]}
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
                "/api/tags": {"models": [{"name": "qwen3-vl:2b-instruct"}]},
                "/api/show": {"capabilities": ["vision"]},
                "/api/chat": {"message": {"role": "assistant", "thinking": "some thoughts", "content": ""}},
            }[route]
        vision = LocalOllamaVision(VisionConfig(), transport=fake)
        vision.initialize()
        with self.assertRaisesRegex(VisionError, "no final answer"):
            vision.describe("Что на картинке?", bytes([255, 216, 255]) + b"x" * 80 + bytes([255, 217]))


    def test_untrusted_vision_endpoints_fail_as_controlled_errors(self):
        for endpoint in (
            None, 7, "", "http://[::1", "http://127.0.0.1:bad",
            "http://127.0.0.1:99999", "http://user@127.0.0.1:11434",
            "https://127.0.0.1:11434", "http://127.0.0.1:11434/api/chat",
            "http://127.0.0.1:11434@evil.example",
        ):
            with self.subTest(endpoint=repr(endpoint)), self.assertRaises(VisionError):
                LocalOllamaVision(VisionConfig(endpoint=endpoint))

    def test_vision_response_bounds_reject_invalid_sizes_before_http(self):
        for maximum in (None, True, -1, 0, 99, 8_000_001, "4000"):
            with self.subTest(maximum=maximum), self.assertRaises(VisionError):
                LocalOllamaVision(VisionConfig(max_response_bytes=maximum))

    def test_vision_network_errors_do_not_disclose_local_paths(self):
        from unittest.mock import Mock
        vision = LocalOllamaVision(VisionConfig())
        vision._opener = Mock()
        vision._opener.open.side_effect = OSError(
            "C:/Users/Private/token-and-password.png")
        with self.assertRaises(VisionError) as context:
            vision._request("/api/tags", None)
        self.assertNotIn("Private", str(context.exception))
        self.assertNotIn("password", str(context.exception))

    def test_nontext_vision_question_fails_without_model_request(self):
        sent = []
        def fake(route, payload):
            sent.append(route)
            return {
                "/api/tags": {"models": [{"name": "qwen3-vl:2b-instruct"}]},
                "/api/show": {"capabilities": ["vision"]},
            }[route]
        vision = LocalOllamaVision(VisionConfig(), transport=fake)
        vision.initialize()
        for question in (None, 4, [], True):
            with self.subTest(value=repr(question)), self.assertRaises(VisionError):
                vision.describe(question, b"\xff\xd8\xff" + b"x"*80 + b"\xff\xd9")
        self.assertEqual(sent, ["/api/tags", "/api/show"])

if __name__ == "__main__":
    unittest.main()
