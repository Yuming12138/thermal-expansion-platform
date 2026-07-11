from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ModelMetadata:
    name: str
    version: str
    weights_sha256: str | None = None
    device: str | None = None


class PotentialAdapter(ABC):
    """Stable boundary between platform workflows and a potential backend."""

    @abstractmethod
    def metadata(self) -> ModelMetadata:
        raise NotImplementedError

    @abstractmethod
    def create_calculator(self, parameters: Mapping[str, Any]) -> Any:
        """Return an ASE-compatible calculator or backend wrapper."""
        raise NotImplementedError
