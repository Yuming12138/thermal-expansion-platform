from __future__ import annotations

from pathlib import Path

from te_platform.agent.registry import ToolRegistry
from te_platform.catalog.queries import material_detail, search_materials
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.composites.material_pair import (
    curve_materials,
    optimize_material_pair,
    query_thermal_expansion_catalog,
)
from te_platform.config import DEFAULT_PTE_RELEASE_SLUG, DEFAULT_RELEASE_SLUG
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr


def default_registry(catalog_database: Path | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        "classify_sbr",
        lambda **kwargs: classify_sbr(**kwargs).to_dict(),
        description="根据剪切模量G和键合模量E_tilde计算SBR并判断NTE倾向。",
        parameters={
            "type": "object",
            "properties": {
                "shear_modulus_gpa": {"type": "number", "minimum": 0},
                "bonding_modulus_gpa": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["shear_modulus_gpa", "bonding_modulus_gpa"],
            "additionalProperties": False,
        },
    )
    registry.register(
        "fast_screen_structure_features",
        lambda **kwargs: fast_screen_sbr(**kwargs).to_dict(),
        description="用已有的结构描述符和预测剪切模量执行快速SBR筛选。",
    )
    registry.register(
        "optimize_composite",
        lambda **kwargs: optimize_zte_fraction(**kwargs).to_dict(),
        description="用两个单点热膨胀系数估算ZTE体积分数，仅适合快速估算。",
        parameters={
            "type": "object",
            "properties": {
                "alpha_pte": {"type": "number"},
                "alpha_nte": {"type": "number"},
                "target_alpha": {"type": "number", "default": 0},
            },
            "required": ["alpha_pte", "alpha_nte"],
            "additionalProperties": False,
        },
    )
    if catalog_database is not None:
        releases = {"nte": DEFAULT_RELEASE_SLUG, "pte": DEFAULT_PTE_RELEASE_SLUG}

        def search_catalog(role: str, query: str = "", limit: int = 10):
            normalized_role = role.lower()
            if normalized_role not in releases:
                raise ValueError("role must be 'nte' or 'pte'")
            if normalized_role == "pte":
                return curve_materials(
                    catalog_database, releases[normalized_role], query, min(limit, 30), alpha_sign=1
                )
            return search_materials(
                catalog_database, releases[normalized_role], query, min(limit, 30)
            )

        def get_material(role: str, material_key: str):
            normalized_role = role.lower()
            if normalized_role not in releases:
                raise ValueError("role must be 'nte' or 'pte'")
            return material_detail(catalog_database, releases[normalized_role], material_key)

        registry.register(
            "search_catalog",
            search_catalog,
            description="搜索平台内置的NTE或PTE材料目录，返回可用于进一步查询的material_key。",
            parameters={
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["nte", "pte"]},
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                },
                "required": ["role"],
                "additionalProperties": False,
            },
        )
        registry.register(
            "get_material",
            get_material,
            description="按material_key读取一个NTE或PTE材料的结构、属性和完整QHA热膨胀曲线。",
            parameters={
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["nte", "pte"]},
                    "material_key": {"type": "string"},
                },
                "required": ["role", "material_key"],
                "additionalProperties": False,
            },
        )
        registry.register(
            "query_thermal_expansion_catalog",
            lambda role="all", **kwargs: query_thermal_expansion_catalog(
                catalog_database,
                tuple(releases.values()) if role == "all" else releases[role],
                **kwargs,
            ),
            description=(
                "在NTE、PTE或全部目录的所有真实QHA曲线上计算任意温度的alpha，"
                "然后进行全库筛选和严格排序。遇到最大、最小、排名、前N名、温度条件比较时应优先使用此工具，"
                "不要用search_catalog的有限候选代替全库统计。ascending返回最负值优先。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["nte", "pte", "all"], "default": "all"},
                    "temperature_k": {"type": "number", "minimum": 0, "default": 300},
                    "query": {"type": "string", "default": ""},
                    "alpha_min_ppm_per_k": {"type": ["number", "null"]},
                    "alpha_max_ppm_per_k": {"type": ["number", "null"]},
                    "sort_order": {"type": "string", "enum": ["ascending", "descending"], "default": "ascending"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "additionalProperties": False,
            },
        )
        registry.register(
            "design_zte_material_pair",
            lambda **kwargs: optimize_material_pair(
                catalog_database,
                pte_release_slug=DEFAULT_PTE_RELEASE_SLUG,
                nte_release_slug=DEFAULT_RELEASE_SLUG,
                **kwargs,
            ),
            description="使用数据库中的真实PTE/NTE热膨胀曲线优化指定温区的ZTE固定体积分数。",
            parameters={
                "type": "object",
                "properties": {
                    "pte_material_key": {"type": "string"},
                    "nte_material_key": {"type": "string"},
                    "temperature_min_k": {"type": "number", "minimum": 0, "default": 300},
                    "temperature_max_k": {"type": "number", "minimum": 1, "default": 800},
                    "target_alpha_ppm_per_k": {"type": "number", "default": 0},
                },
                "required": ["pte_material_key", "nte_material_key"],
                "additionalProperties": False,
            },
        )
    return registry
