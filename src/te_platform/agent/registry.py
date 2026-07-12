from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RegisteredTool:
    callback: Callable[..., Any]
    description: str
    parameters: dict[str, Any]


class ToolRegistry:
    """Allowlisted tools for an Agent; arbitrary shell execution is excluded."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        name: str,
        tool: Callable[..., Any],
        *,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        if not name or name.startswith("_"):
            raise ValueError("Tool name must be public and non-empty")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = RegisteredTool(
            callback=tool,
            description=description or name,
            parameters=parameters or {"type": "object", "properties": {}},
        )

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def call(self, name: str, **arguments: Any) -> Any:
        try:
            tool = self._tools[name]
        except KeyError as error:
            raise KeyError(f"Unknown Agent tool: {name}") from error
        return tool.callback(**arguments)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for name, tool in sorted(self._tools.items())
        ]
