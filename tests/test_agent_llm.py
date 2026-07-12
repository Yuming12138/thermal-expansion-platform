import json
import tempfile
import unittest
from pathlib import Path

import httpx

from te_platform.agent.llm import _safe_upstream_detail, capability, chat_with_model
from te_platform.agent.registry import ToolRegistry
from te_platform.config import AgentSettings, load_agent_env


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
                self.assertIn("structure-123", json.dumps(payload["messages"]))
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
                history=[
                    {"role": "user", "content": "上一轮问题"},
                    {"role": "assistant", "content": "上一轮回答"},
                ],
                attachments=[{"structure_id": "structure-123", "filename": "sample.cif"}],
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

    def test_loads_only_allowlisted_agent_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / "agent.env"
            env_path.write_text(
                "# local config\n"
                "TEP_AGENT_MODEL=test-model\n"
                "TEP_AGENT_API_KEY='hidden-value'\n"
                "UNRELATED_VALUE=ignored\n",
                encoding="utf-8",
            )
            values = load_agent_env(env_path)
        self.assertEqual(values["TEP_AGENT_MODEL"], "test-model")
        self.assertEqual(values["TEP_AGENT_API_KEY"], "hidden-value")
        self.assertNotIn("UNRELATED_VALUE", values)

    def test_upstream_error_detail_masks_api_keys(self) -> None:
        request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
        response = httpx.Response(
            503,
            request=request,
            json={"error": {"message": "channel failed for sk-sensitive-value"}},
        )
        error = httpx.HTTPStatusError("failed", request=request, response=response)
        detail = _safe_upstream_detail(error)
        self.assertEqual(detail, "channel failed for sk-***")
