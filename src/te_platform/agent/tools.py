from __future__ import annotations

from te_platform.agent.registry import ToolRegistry
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("classify_sbr", classify_sbr)
    registry.register("fast_screen_structure_features", fast_screen_sbr)
    registry.register("optimize_composite", optimize_zte_fraction)
    return registry
