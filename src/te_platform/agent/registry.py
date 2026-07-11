from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ToolRegistry:
    """Allowlisted tools for an Agent; arbitrary shell execution is excluded."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, tool: Callable[..., Any]) -> None:
        if not name or name.startswith("_"):
            raise ValueError("Tool name must be public and non-empty")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def call(self, name: str, **arguments: Any) -> Any:
        try:
            tool = self._tools[name]
        except KeyError as error:
            raise KeyError(f"Unknown Agent tool: {name}") from error
        return tool(**arguments)
