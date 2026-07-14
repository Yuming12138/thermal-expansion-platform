from __future__ import annotations

from pathlib import Path

from te_platform.agent.actions import create_action_request
from te_platform.agent.registry import ToolRegistry
from te_platform.agent.uploads import inspect_agent_structure
from te_platform.catalog.queries import compare_materials, material_detail, search_materials
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.composites.material_pair import (
    curve_materials,
    optimize_material_pair,
    query_thermal_expansion_catalog,
)
from te_platform.config import DEFAULT_PTE_RELEASE_SLUG, DEFAULT_RELEASE_SLUG
from te_platform.jobs.precision_runner import precision_progress
from te_platform.jobs.repository import get_job
from te_platform.precision.wsl_executor import PrecisionTaskConfig
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr


def default_registry(
    catalog_database: Path | None = None,
    workspace_database: Path | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        "classify_sbr",
        lambda **kwargs: classify_sbr(**kwargs).to_dict(),
        description=(
            "根据剪切模量G和论文定义的键合模量E_tilde=U_V/n计算SBR并判断NTE倾向。"
        ),
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
        description=(
            "用内聚能、平均原子体积和平均配位数计算E_tilde=U_V/n，"
            "再结合预测剪切模量执行快速SBR筛选。"
        ),
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

        def compare_catalog_materials(
            role: str,
            material_keys: list[str],
            temperature_k: float = 300.0,
        ):
            normalized_role = role.lower()
            if normalized_role not in releases:
                raise ValueError("role must be 'nte' or 'pte'")
            return compare_materials(
                catalog_database,
                releases[normalized_role],
                material_keys,
                temperature_k=temperature_k,
            )

        registry.register(
            "search_catalog",
            search_catalog,
            description=(
                "仅在用户尚未给出准确material_key时搜索NTE或PTE目录，返回候选material_key。"
                "若用户已经给出两个以上完整material_key并要求比较，应直接调用compare_catalog_materials，"
                "不要重复搜索。"
            ),
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
            "compare_catalog_materials",
            compare_catalog_materials,
            description=(
                "严格比较2到6个指定材料的G、论文定义E_tilde、xi、目录CTE以及指定温度下"
                "由真实QHA曲线插值得到的alpha。用户提出多个材料谁更强、曲线有何差异、"
                "在某温度如何排序时使用此工具。若输入已经是完整material_key，直接调用本工具，"
                "不要先调用search_catalog。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["nte", "pte"]},
                    "material_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 6,
                    },
                    "temperature_k": {"type": "number", "minimum": 0, "default": 300},
                },
                "required": ["role", "material_keys"],
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
    if workspace_database is not None:
        registry.register(
            "inspect_uploaded_structure",
            lambda structure_id: inspect_agent_structure(workspace_database, structure_id),
            description="检查对话中已上传的CIF/POSCAR结构，返回格式、原子数和晶胞体积。",
            parameters={
                "type": "object",
                "properties": {"structure_id": {"type": "string"}},
                "required": ["structure_id"],
                "additionalProperties": False,
            },
        )

        def request_structure_calculation(
            structure_id: str,
            mode: str,
            qha_points: int = 11,
            qha_mesh: int = 30,
            qha_scale: float = 0.003,
            parallel_workers: int = 1,
        ):
            structure = inspect_agent_structure(workspace_database, structure_id)
            config = PrecisionTaskConfig(
                qha_points=qha_points,
                qha_mesh=qha_mesh,
                qha_scale=qha_scale,
                parallel_workers=parallel_workers,
            )
            config.validate()
            labels = {
                "fast": "快速预测（ALIGNN G + MatterSim E_tilde + SBR）",
                "elastic": "精准弹性预测（完整弹性张量 + Hill G + SBR）",
                "qha": "MatterSim QHA 热膨胀曲线计算",
            }
            if mode not in labels:
                raise ValueError("mode must be 'fast', 'elastic', or 'qha'")
            action = create_action_request(
                workspace_database,
                action="submit_structure_calculation",
                summary=(
                    f"对上传结构 {structure_id[:12]}… 提交{labels[mode]}"
                    + (
                        f"；qha_points={qha_points}, mesh={qha_mesh}, scale={qha_scale}, "
                        f"parallel_workers={parallel_workers}"
                        if mode == "qha"
                        else ""
                    )
                ),
                arguments={
                    "structure_id": structure_id,
                    "mode": mode,
                    "config": config.__dict__,
                    "filename": structure["stored_filename"],
                },
            )
            return {
                "approval_required": True,
                "approval_id": action["id"],
                "action": action["action"],
                "mode": mode,
                "summary": action["summary"],
                "status": action["status"],
                "structure": structure,
            }

        registry.register(
            "request_structure_calculation",
            request_structure_calculation,
            description=(
                "为已上传结构创建计算审批请求。根据用户目标自主选择mode："
                "fast用于快速判断NTE/PTE倾向，elastic用于完整弹性张量和精准SBR，"
                "qha用于直接计算alpha(T)热膨胀曲线。此工具不会直接启动计算，必须由用户批准。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "structure_id": {"type": "string"},
                    "mode": {"type": "string", "enum": ["fast", "elastic", "qha"]},
                    "qha_points": {"type": "integer", "enum": [7, 9, 11], "default": 11},
                    "qha_mesh": {"type": "integer", "minimum": 10, "maximum": 60, "default": 30},
                    "qha_scale": {"type": "number", "exclusiveMinimum": 0, "maximum": 0.01, "default": 0.003},
                    "parallel_workers": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1},
                },
                "required": ["structure_id", "mode"],
                "additionalProperties": False,
            },
        )

        registry.register(
            "request_qha_calculation",
            lambda structure_id, **kwargs: request_structure_calculation(
                structure_id=structure_id, mode="qha", **kwargs
            ),
            description="兼容工具：为上传结构创建QHA热膨胀计算审批请求。",
            parameters={
                "type": "object",
                "properties": {
                    "structure_id": {"type": "string"},
                    "qha_points": {"type": "integer", "enum": [7, 9, 11], "default": 11},
                    "qha_mesh": {"type": "integer", "minimum": 10, "maximum": 60, "default": 30},
                    "qha_scale": {"type": "number", "exclusiveMinimum": 0, "maximum": 0.01, "default": 0.003},
                    "parallel_workers": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1},
                },
                "required": ["structure_id"],
                "additionalProperties": False,
            },
        )

        def calculation_job_status(job_id: str):
            job = get_job(workspace_database, job_id)
            job["progress"] = precision_progress(workspace_database, job_id)
            return job

        registry.register(
            "get_calculation_job",
            calculation_job_status,
            description="查询已提交弹性或QHA任务的状态、进度、错误和结构化结果。",
            parameters={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
                "additionalProperties": False,
            },
        )
    return registry
