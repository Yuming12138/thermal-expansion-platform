from __future__ import annotations

import json
import re
from typing import Any

import httpx

from te_platform.agent.registry import ToolRegistry
from te_platform.config import AgentSettings, agent_settings


SYSTEM_PROMPT = """你是热膨胀材料智能计算与复合设计平台的科学助手。
优先调用白名单工具查询真实数据库和执行可复核计算，不要编造材料数据。
回答时区分数据库事实、模型预测和科学建议，并注明热膨胀系数单位。
当前工具不会启动耗时的ALIGNN、MatterSim弹性或QHA作业；若用户需要这些计算，说明应在结构预测区提交。
保持回答简洁、明确，默认使用中文。"""


class AgentNotConfiguredError(RuntimeError):
    pass


class AgentUpstreamError(RuntimeError):
    pass


def _safe_upstream_detail(error: Exception) -> str:
    response = getattr(error, "response", None)
    if response is None:
        return ""
    try:
        payload = response.json()
        detail: object = payload
        if isinstance(payload, dict):
            nested_error = payload.get("error")
            if isinstance(nested_error, dict):
                detail = nested_error.get("message") or nested_error.get("code") or nested_error
            else:
                detail = payload.get("message") or payload.get("detail") or payload
        text = str(detail)
    except (TypeError, ValueError):
        text = ""
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
    return text[:300]


def capability(settings: AgentSettings | None = None) -> dict[str, object]:
    current = settings or agent_settings()
    return {
        "configured": current.configured,
        "base_url": current.base_url,
        "model": current.model,
        "tool_calling": True,
        "api_key_source": "process_environment" if current.configured else None,
    }


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    return ""


async def chat_with_model(
    message: str,
    registry: ToolRegistry,
    *,
    history: list[dict[str, str]] | None = None,
    settings: AgentSettings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    current = settings or agent_settings()
    if not current.api_key:
        raise AgentNotConfiguredError(
            "AI助手尚未配置密钥。请运行 scripts/configure-agent.ps1 后重启平台。"
        )

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (history or [])[-12:]:
        role = item.get("role")
        content = item.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": message})
    executed: list[dict[str, object]] = []
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=current.timeout_seconds)
    try:
        for _ in range(5):
            try:
                response = await active_client.post(
                    f"{current.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {current.api_key}"},
                    json={
                        "model": current.model,
                        "messages": messages,
                        "tools": registry.openai_tools(),
                        "tool_choice": "auto",
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                assistant_message = payload["choices"][0]["message"]
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                suffix = f"（HTTP {status}）" if status else ""
                detail = _safe_upstream_detail(error)
                detail_suffix = f"：{detail}" if detail else "，请稍后重试。"
                raise AgentUpstreamError(f"AI中转站调用失败{suffix}{detail_suffix}") from error

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                return {
                    "mode": "llm",
                    "model": current.model,
                    "answer": _content_text(assistant_message.get("content")),
                    "tool_calls": executed,
                }

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.get("content"),
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                function = call.get("function") or {}
                name = function.get("name", "")
                arguments: dict[str, Any] = {}
                try:
                    decoded_arguments = json.loads(function.get("arguments") or "{}")
                    if not isinstance(decoded_arguments, dict):
                        raise TypeError("Tool arguments must be a JSON object")
                    arguments = decoded_arguments
                    result = registry.call(name, **arguments)
                    tool_result: object = result
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    tool_result = {"error": str(error)}
                executed.append(
                    {"tool": name, "arguments": arguments, "result": tool_result}
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )
        raise AgentUpstreamError("AI助手连续调用工具次数过多，请缩小问题范围后重试。")
    finally:
        if owns_client:
            await active_client.aclose()
