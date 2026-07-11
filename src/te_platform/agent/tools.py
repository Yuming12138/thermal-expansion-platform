from __future__ import annotations

from te_platform.agent.registry import ToolRegistry
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("classify_sbr", lambda **kwargs: classify_sbr(**kwargs).to_dict())
    registry.register("fast_screen_structure_features", lambda **kwargs: fast_screen_sbr(**kwargs).to_dict())
    registry.register("optimize_composite", lambda **kwargs: optimize_zte_fraction(**kwargs).to_dict())
    return registry
