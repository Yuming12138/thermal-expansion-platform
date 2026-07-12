import json
import unittest

import httpx

from te_platform.agent.llm import capability, chat_with_model
from te_platform.agent.registry import ToolRegistry
from te_platform.config import AgentSettings


class AgentLlmTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_can_call_allowlisted_tool_then_answer(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            self.assertEqual(request.headers["Authorization"], "Bearer local-test-key")
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "test-model")
            if request_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "call-1",
                                            "type": "function",
                                            "function": {
                                                "name": "echo_number",
                                                "arguments": '{"value": 7}',
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                )
            self.assertEqual(payload["messages"][-1]["role"], "tool")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "结果是7。"}}]},
            )

        registry = ToolRegistry()
        registry.register("echo_number", lambda value: {"value": value})
        settings = AgentSettings(
            base_url="https://example.invalid/v1",
            model="test-model",
            api_key="local-test-key",
            timeout_seconds=10,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await chat_with_model(
                "查询数字",
                registry,
                settings=settings,
                client=client,
            )

        self.assertEqual(result["answer"], "结果是7。")
        self.assertEqual(result["tool_calls"][0]["tool"], "echo_number")
        self.assertEqual(request_count, 2)

    def test_capability_never_returns_key(self) -> None:
        settings = AgentSettings(
            base_url="https://example.invalid/v1",
            model="test-model",
            api_key="local-test-key",
            timeout_seconds=10,
        )
        result = capability(settings)
        self.assertTrue(result["configured"])
        self.assertNotIn("api_key", result)
        self.assertNotIn("local-test-key", json.dumps(result))
