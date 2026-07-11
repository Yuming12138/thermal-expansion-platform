from __future__ import annotations

import re
from typing import Any

from te_platform.agent.registry import ToolRegistry


def respond(message: str, registry: ToolRegistry) -> dict[str, Any]:
    text = message.strip()
    sbr = re.fullmatch(r"SBR\s+G=([-+.0-9]+)\s+E=([-+.0-9]+)", text, flags=re.IGNORECASE)
    if sbr:
        return {"tool": "classify_sbr", "result": registry.call("classify_sbr", shear_modulus_gpa=float(sbr.group(1)), bonding_modulus_gpa=float(sbr.group(2)))}
    zte = re.fullmatch(r"ZTE\s+PTE=([-+.0-9]+)\s+NTE=([-+.0-9]+)", text, flags=re.IGNORECASE)
    if zte:
        return {"tool": "optimize_composite", "result": registry.call("optimize_composite", alpha_pte=float(zte.group(1)), alpha_nte=float(zte.group(2)))}
    return {"tool": None, "result": None, "message": "支持：SBR G=20 E=10；ZTE PTE=8 NTE=-12。仅调用白名单科学工具。"}
