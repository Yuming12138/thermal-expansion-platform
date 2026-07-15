from __future__ import annotations

import json
import re
from typing import Any

import httpx

from te_platform.agent.registry import ToolRegistry
from te_platform.config import AgentSettings, agent_settings


MAX_AGENT_STEPS = 12


SYSTEM_PROMPT = """你是热膨胀材料科研工作台的自主科学Agent。
围绕用户目标持续执行“理解问题—选择工具—观察结果—修正方案—验证结论”的循环，直到完成或遇到必须由用户决定的边界。
优先使用少量通用工具，不要因为没有某个专用函数就停止：先用describe_database理解表结构，再自行编写只读SQL并用query_database完成检索、关联、统计、任意温度插值和全库排名。SQL失败时根据错误修改后重试。
数据库目录库永远只读。回答必须区分数据库事实、模型预测和科学建议，注明热膨胀系数单位；全库排名必须报告实际覆盖目标温度并参与排序的材料数量，不能把有限候选称为全库结论。
涉及上传结构的fast、elastic或qha任务时，先检查结构，必要时查看任务能力，再调用request_calculation_task创建审批请求。fast用于快速NTE/PTE倾向，elastic用于完整弹性张量和精准SBR，qha用于alpha(T)曲线。审批请求不等于任务已提交；必须等待用户确认。创建一个审批请求后不要继续创建其他任务，只需说明任务类型、参数和确认步骤。
用户批准后，使用对话历史中的job_id调用get_calculation_job查询状态和结果。数据库读取可自动执行，目录库写入、耗时计算和其他副作用不得绕过审批。
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
        "agent_loop": True,
        "max_tool_steps": MAX_AGENT_STEPS,
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
    attachments: list[dict[str, Any]] | None = None,
    pending_actions: list[dict[str, Any]] | None = None,
    settings: AgentSettings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    current = settings or agent_settings()
    if not current.api_key:
        raise AgentNotConfiguredError(
            "AI助手尚未配置密钥。请运行 scripts/configure-agent.ps1 后重启平台。"
        )

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if attachments:
        messages.append(
            {
                "role": "system",
                "content": (
                    "本轮可用的已上传结构如下。需要读取或计算时使用对应structure_id调用工具：\n"
                    + json.dumps(attachments, ensure_ascii=False)
                ),
            }
        )
    if pending_actions:
        messages.append(
            {
                "role": "system",
                "content": (
                    "当前工作区已有以下待用户确认的计算审批。不要重复创建任务；"
                    "若用户询问提交状态，说明需要先在界面确认或取消：\n"
                    + json.dumps(pending_actions, ensure_ascii=False)
                ),
            }
        )
    for item in (history or [])[-12:]:
        role = item.get("role")
        content = item.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": message})
    executed: list[dict[str, object]] = []
    call_counts: dict[str, int] = {}
    approval_pending = bool(pending_actions)
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=current.timeout_seconds)
    try:
        for step in range(1, MAX_AGENT_STEPS + 1):
            try:
                response = await active_client.post(
                    f"{current.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {current.api_key}"},
                    json={
                        "model": current.model,
                        "messages": messages,
                        "tools": registry.openai_tools(
                            include_side_effecting=not approval_pending
                        ),
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
                    fingerprint = name + ":" + json.dumps(
                        arguments, ensure_ascii=False, sort_keys=True
                    )
                    call_counts[fingerprint] = call_counts.get(fingerprint, 0) + 1
                    if call_counts[fingerprint] >= 3:
                        raise ValueError(
                            "The same tool call has already failed or repeated twice; revise the plan"
                        )
                    if approval_pending and registry.is_side_effecting(name):
                        raise ValueError(
                            "A task approval is already pending; do not create another side effect"
                        )
                    tool_result = registry.call(name, **arguments)
                    if isinstance(tool_result, dict) and tool_result.get("approval_required"):
                        approval_pending = True
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    tool_result = {"error": str(error)}
                executed.append(
                    {
                        "step": step,
                        "tool": name,
                        "arguments": arguments,
                        "result": tool_result,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )
            if approval_pending:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "当前已有待用户确认的任务审批。不要再创建任务；"
                            "请向用户概括审批内容并说明点击确认后才会提交。"
                        ),
                    }
                )
        raise AgentUpstreamError(
            f"AI助手已达到{MAX_AGENT_STEPS}步工具预算，仍未形成结论。请缩小问题范围后重试。"
        )
    finally:
        if owns_client:
            await active_client.aclose()
