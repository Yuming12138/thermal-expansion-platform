"""Materials Project-style Crystal Toolkit structure viewer.

The main application is a small FastAPI/HTML application, while Crystal Toolkit
is a Dash component library.  This module keeps the Dash surface deliberately
small and mounts it under ``/ctk/`` through Starlette's WSGI adapter.  The
viewer receives a material key in the query string and loads the exact
crystallographic record from the active catalog release.

Crystal Toolkit owns the scene controls (VESTA/Jmol colours, atom radii,
periodic images, unit-cell choices, polyhedra and image export).  No geometry
is approximated in JavaScript here, so the rendered scene and the structure
download are based on the same pymatgen object.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from dash import Dash, Input, Output, dcc, html
from flask_caching import Cache
from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Poscar

import crystal_toolkit.components as ctc
from crystal_toolkit import CrystalToolkitPlugin

from te_platform.catalog.queries import material_detail


def _preferred_structure(structures: list[dict[str, object]]) -> dict[str, object] | None:
    """Choose a renderable POSCAR/VASP/CIF without considering tensor records."""

    priority = {"POSCAR": 0, "VASP": 0, "CIF": 1}
    candidates = [item for item in structures if item.get("content")]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            priority.get(str(item.get("format", "")).upper(), 2),
            str(item.get("format", "")),
        ),
    )


@lru_cache(maxsize=512)
def _load_structure(
    database_path: str,
    release_slug: str,
    material_key: str,
) -> tuple[Structure, dict[str, object]]:
    """Load and parse one exact catalog structure, with a small process cache."""

    detail = material_detail(Path(database_path), release_slug, material_key)
    record = _preferred_structure(detail.get("structures", []))
    if record is None:
        raise ValueError(f"材料没有可渲染的 POSCAR/CIF：{material_key}")
    content = str(record["content"])
    structure_format = str(record.get("format", "POSCAR")).upper()
    if structure_format in {"POSCAR", "VASP"}:
        structure = Poscar.from_str(content).structure
    else:
        structure = Structure.from_str(content, fmt=structure_format.lower())
    return structure, record


def _material_key_from_search(search: str | None) -> str | None:
    if not search:
        return None
    values = parse_qs(urlparse(search).query).get("material_key", [])
    return values[0].strip() if values and values[0].strip() else None


def create_crystal_toolkit_app(
    catalog_database: Path,
    release_slug: str,
) -> Dash:
    """Create a Dash application for the embedded Crystal Toolkit viewer."""

    structure_component = ctc.StructureMoleculeComponent(
        id="material-structure",
        struct_or_mol=None,
        bonding_strategy="CrystalNN",
        color_scheme="VESTA",
        radius_strategy="uniform",
        unit_cell_choice="input",
        draw_image_atoms=True,
        bonded_sites_outside_unit_cell=True,
        hide_incomplete_bonds=False,
        show_compass=True,
        show_legend=True,
        show_settings=True,
        show_controls=True,
        show_expand_button=True,
        show_image_button=True,
        show_export_button=True,
        show_position_button=True,
        scene_settings={"zoomToFit2D": True},
    )

    # The component's own controls and scene are deliberately retained: they
    # provide the same interaction model as the MP viewer, including the
    # Polyhedra toggle and native PNG/structure export.
    layout = html.Div(
        [
            dcc.Location(id="ctk-location", refresh=False),
            html.Div(
                [
                    html.Div(
                        [
                            html.P("CRYSTAL TOOLKIT", className="ctk-eyebrow"),
                            html.H1("晶体结构查看器", id="ctk-page-title"),
                            html.P(
                                "Materials Project 风格的交互结构视图。可在设置中切换晶胞、配位、多面体和元素显示。",
                                className="ctk-subtitle",
                            ),
                        ],
                        className="ctk-header-copy",
                    ),
                    html.Div(
                        [
                            html.Span("正在读取材料…", id="ctk-status", className="ctk-status"),
                            html.A("返回材料详情", id="ctk-back", href="/", className="ctk-back-link"),
                        ],
                        className="ctk-header-actions",
                    ),
                ],
                className="ctk-header",
            ),
            html.Div(
                structure_component.title_layout(),
                className="ctk-structure-title",
            ),
            html.Div(
                structure_component.layout(size="100%"),
                className="ctk-structure-frame",
            ),
            html.P(
                "结构来源：当前发布目录中的原始 POSCAR/CIF；键和多面体为 Crystal Toolkit 的 CrystalNN 近邻可视化。",
                id="ctk-provenance",
                className="ctk-provenance",
            ),
        ],
        className="ctk-page",
    )

    app = Dash(
        __name__,
        title="Crystal Toolkit · 热膨胀材料平台",
        requests_pathname_prefix="/ctk/",
        # Starlette strips the ``/ctk`` mount prefix before handing the
        # request to the WSGI application.  Keep Flask routes rooted at ``/``
        # while Dash still emits browser URLs under ``/ctk/``.
        routes_pathname_prefix="/",
        suppress_callback_exceptions=True,
        external_stylesheets=[],
    )
    app.index_string = """<!DOCTYPE html>
<html lang="zh-CN">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            :root { color-scheme: light; font-family: Inter, "Segoe UI", sans-serif; }
            html, body { margin: 0; min-height: 100%; background: #f7f9fc; color: #1d2939; }
            body { overflow-y: auto; }
            .ctk-page { box-sizing: border-box; min-height: 100vh; padding: 28px clamp(18px, 4vw, 56px) 40px; }
            .ctk-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; max-width: 1240px; margin: 0 auto 18px; }
            .ctk-eyebrow { margin: 0 0 7px; color: #526581; font: 700 11px/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .13em; }
            .ctk-header h1 { margin: 0; color: #16263d; font-size: clamp(23px, 3vw, 34px); letter-spacing: -.025em; }
            .ctk-subtitle { max-width: 690px; margin: 8px 0 0; color: #61718a; font-size: 14px; line-height: 1.55; }
            .ctk-header-actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; justify-content: flex-end; }
            .ctk-status { color: #526581; font: 12px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; }
            .ctk-back-link { color: #365f99; font-size: 13px; text-decoration: none; }
            .ctk-back-link:hover { text-decoration: underline; }
            .ctk-structure-title { max-width: 1240px; margin: 0 auto 8px; color: #16263d; }
            .ctk-structure-title h2 { margin: 0; font-size: 18px; font-weight: 650; }
            .ctk-structure-frame { box-sizing: border-box; width: 100%; max-width: 1240px; height: min(720px, 72vh); min-height: 500px; margin: 0 auto; overflow: hidden; border: 1px solid #d9e1ec; border-radius: 12px; background: #fff; box-shadow: 0 12px 32px rgba(28, 45, 72, .08); }
            .ctk-structure-frame > div { width: 100% !important; height: 100% !important; }
            .ctk-provenance { max-width: 1240px; margin: 12px auto 0; color: #718096; font-size: 12px; line-height: 1.5; }
            @media (max-width: 720px) {
                .ctk-page { padding: 18px 12px 28px; }
                .ctk-header { align-items: flex-start; flex-direction: column; gap: 12px; }
                .ctk-header-actions { justify-content: flex-start; }
                .ctk-structure-frame { height: 620px; min-height: 480px; border-radius: 9px; }
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""
    app.layout = layout
    # The plugin registers Crystal Toolkit's component stores and callbacks.
    # Flask-Caching 2.5 renamed the backend module from ``simple`` to
    # ``simplecache``.  Crystal Toolkit still requests the former shorthand,
    # so provide the explicit class name to keep the plugin compatible with
    # the current portable environment.
    ctk_cache = Cache(config={"CACHE_TYPE": "SimpleCache"})
    CrystalToolkitPlugin(layout=layout, cache=ctk_cache, use_default_css=True).plug(app)

    @app.callback(
        Output(structure_component.id(), "data"),
        Output("ctk-page-title", "children"),
        Output("ctk-status", "children"),
        Output("ctk-back", "href"),
        Input("ctk-location", "search"),
    )
    def load_material(search: str | None):
        material_key = _material_key_from_search(search)
        if not material_key:
            return None, "晶体结构查看器", "请从材料详情页打开一个材料。", "/"
        try:
            structure, record = _load_structure(str(catalog_database), release_slug, material_key)
        except (ValueError, OSError, RuntimeError) as error:
            return None, "晶体结构查看器", f"结构加载失败：{error}", "/"
        formula = structure.composition.reduced_formula
        return (
            structure.as_dict(),
            formula,
            f"{material_key} · {record.get('format', 'POSCAR')}",
            f"/materials/{quote(material_key, safe='')}",
        )

    # ``CrystalToolkitPlugin`` uses dynamic callbacks for its scene.  Keeping
    # this callback registration after the plugin is intentional: the
    # component's default data store is then available to both callback sets.
    return app


def clear_structure_cache() -> None:
    """Clear parsed structures after an active catalog release is replaced."""

    _load_structure.cache_clear()
