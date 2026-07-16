from __future__ import annotations

from pathlib import Path

from te_platform.agent.actions import create_action_request, get_action_request
from te_platform.agent.database_tools import describe_catalog_database, execute_catalog_sql
from te_platform.agent.registry import ToolRegistry
from te_platform.agent.uploads import inspect_agent_structure
from te_platform.catalog.queries import compare_materials, material_detail, search_materials
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.composites.material_pair import (
    curve_materials,
    optimize_material_pair,
    query_thermal_expansion_catalog,
)
from te_platform.composites.screening import screen_material_pairs
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
        model_visible=False,
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

        registry.register(
            "describe_database",
            lambda: describe_catalog_database(catalog_database),
            description=(
                "检查内置材料目录库的表、字段、外键、单位和可用SQL函数。"
                "当问题需要新的查询方式或不清楚数据结构时先调用本工具。"
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )
        registry.register(
            "query_database",
            lambda **kwargs: execute_catalog_sql(catalog_database, **kwargs),
            description=(
                "执行模型自行编写的单条只读SQLite SELECT/WITH查询。目录库不可修改。"
                "支持alpha_at_temperature(points_json, temperature_k)将真实QHA曲线线性插值为1/K；"
                "乘以1e6得到ppm/K。优先用本工具自行完成任意温度排名、组合筛选、统计和关联查询，"
                "不要要求开发者为每种问题增加专用工具。SQL失败时阅读错误并修正后重试。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "minLength": 1, "maxLength": 20000},
                    "parameters": {
                        "type": "object",
                        "additionalProperties": {"type": ["string", "number", "null"]},
                        "default": {},
                    },
                    "max_rows": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                    "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 5000, "default": 2000},
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        )

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
            model_visible=False,
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
            model_visible=False,
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
            model_visible=False,
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
            model_visible=False,
        )
        registry.register(
            "design_zte_material_pair",
            lambda **kwargs: optimize_material_pair(
                catalog_database,
                pte_release_slug=DEFAULT_PTE_RELEASE_SLUG,
                nte_release_slug=DEFAULT_RELEASE_SLUG,
                **kwargs,
            ),
            description=(
                "使用数据库中的真实PTE/NTE热膨胀曲线，在指定温区比较线性ROM、Turner与Kerner模型，"
                "优化固定体积分数并返回质量分数、误差和ZTE温区覆盖率。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pte_material_key": {"type": "string"},
                    "nte_material_key": {"type": "string"},
                    "temperature_min_k": {"type": "number", "minimum": 0, "default": 300},
                    "temperature_max_k": {"type": "number", "minimum": 1, "default": 800},
                    "target_alpha_ppm_per_k": {"type": "number", "default": 0},
                    "model": {
                        "type": "string",
                        "enum": ["linear_rom", "turner", "kerner"],
                        "default": "linear_rom",
                    },
                    "matrix_phase": {
                        "type": "string",
                        "enum": ["pte", "nte"],
                        "default": "pte",
                        "description": "Kerner模型的连续基体相；其他模型忽略此参数。",
                    },
                    "temperature_step_k": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 100,
                        "default": 10,
                    },
                    "zte_tolerance_ppm_per_k": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 100,
                        "default": 5,
                    },
                },
                "required": ["pte_material_key", "nte_material_key"],
                "additionalProperties": False,
            },
        )
        registry.register(
            "screen_zte_material_pairs",
            lambda **kwargs: screen_material_pairs(
                catalog_database,
                pte_release_slug=DEFAULT_PTE_RELEASE_SLUG,
                nte_release_slug=DEFAULT_RELEASE_SLUG,
                **kwargs,
            ),
            description=(
                "严格遍历目录库中所有满足温区与筛选条件的PTE/NTE组合，按ZTE覆盖率、"
                "最长连续温区和误差排名。用于回答全库最佳组合、候选推荐和配比约束问题；"
                "不要用有限材料搜索结果代替此工具。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "temperature_min_k": {"type": "number", "minimum": 0, "default": 300},
                    "temperature_max_k": {"type": "number", "minimum": 1, "default": 800},
                    "temperature_step_k": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 100,
                        "default": 10,
                    },
                    "target_alpha_ppm_per_k": {"type": "number", "default": 0},
                    "zte_tolerance_ppm_per_k": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 100,
                        "default": 5,
                    },
                    "model": {
                        "type": "string",
                        "enum": ["linear_rom", "turner", "kerner"],
                        "default": "linear_rom",
                    },
                    "matrix_phase": {
                        "type": "string",
                        "enum": ["pte", "nte"],
                        "default": "pte",
                    },
                    "pte_query": {"type": "string", "default": ""},
                    "nte_query": {"type": "string", "default": ""},
                    "nte_volume_fraction_min": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "default": 0,
                    },
                    "nte_volume_fraction_max": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "default": 1,
                    },
                    "require_matrix_majority": {"type": "boolean", "default": False},
                    "required_elements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "default": [],
                        "description": "PTE与NTE组合整体必须包含的元素符号。",
                    },
                    "excluded_elements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "default": [],
                        "description": "任一相含有这些元素时排除组合。",
                    },
                    "require_mass_fraction": {"type": "boolean", "default": False},
                    "require_complete_mechanics": {"type": "boolean", "default": False},
                    "max_density_ratio": {"type": ["number", "null"], "minimum": 1},
                    "max_bulk_modulus_ratio": {"type": ["number", "null"], "minimum": 1},
                    "max_shear_modulus_ratio": {"type": ["number", "null"], "minimum": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
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

        calculation_capabilities = {
            "fast": {
                "label": "快速预测",
                "workflow": "fast_structure_screening",
                "purpose": "ALIGNN预测G、MatterSim得到E_tilde并用SBR判断NTE/PTE倾向。",
                "typical_cost": "低",
            },
            "elastic": {
                "label": "精准弹性预测",
                "workflow": "precision_elastic",
                "purpose": "MatterSim完整弹性张量、Hill剪切模量、E_tilde和SBR。",
                "typical_cost": "中",
            },
            "qha": {
                "label": "QHA热膨胀计算",
                "workflow": "precision_qha",
                "purpose": "MatterSim QHA计算完整alpha(T)曲线。",
                "typical_cost": "高",
            },
        }

        registry.register(
            "describe_calculation_tasks",
            lambda: {
                "tasks": calculation_capabilities,
                "submission_policy": (
                    "所有任务先创建PENDING_APPROVAL审批请求；用户确认后才会生成计算任务。"
                ),
                "required_input": "已上传CIF/POSCAR的structure_id",
            },
            description=(
                "查看可提交的fast、elastic和qha任务、用途、成本层级及审批规则。"
                "当用户目标含糊或需要权衡计算层级时调用。"
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )

        def request_calculation_task(
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
            if mode not in calculation_capabilities:
                raise ValueError("mode must be 'fast', 'elastic', or 'qha'")
            capability = calculation_capabilities[mode]
            action = create_action_request(
                workspace_database,
                action="submit_structure_calculation",
                summary=(
                    f"对上传结构 {structure_id[:12]}… 提交{capability['label']}"
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
                "next_step": "等待用户在对话窗口点击确认并提交。",
            }

        registry.register(
            "request_calculation_task",
            request_calculation_task,
            description=(
                "为已上传结构统一创建计算任务审批请求。根据用户目标自主选择mode："
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
            side_effecting=True,
        )

        registry.register(
            "request_structure_calculation",
            request_calculation_task,
            description="兼容工具：创建结构计算审批请求。",
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
            model_visible=False,
            side_effecting=True,
        )

        registry.register(
            "request_qha_calculation",
            lambda structure_id, **kwargs: request_calculation_task(
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
            model_visible=False,
            side_effecting=True,
        )

        registry.register(
            "get_task_request",
            lambda approval_id: get_action_request(workspace_database, approval_id),
            description="查询计算任务审批请求的状态、参数、执行结果或失败原因。",
            parameters={
                "type": "object",
                "properties": {"approval_id": {"type": "string"}},
                "required": ["approval_id"],
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
