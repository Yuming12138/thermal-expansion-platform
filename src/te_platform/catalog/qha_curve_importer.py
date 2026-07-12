from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from te_platform.db.schema import connect_database, initialize_database
from te_platform.jobs.repository import import_historical_thermal_expansion_curve
from te_platform.precision.results import interpolate_alpha, parse_thermal_expansion_file


_BAD_SUFFIX = re.compile(r"(?:[-_]bad)$", flags=re.IGNORECASE)
_MP_SEPARATOR = re.compile(r"[_-](mp-\d+)$", flags=re.IGNORECASE)


@dataclass(frozen=True)
class QhaCurveImportSummary:
    scanned_files: int
    parsed_files: int
    imported_curves: int
    unmatched_files: int
    invalid_files: int
    unmatched_examples: tuple[str, ...]
    invalid_examples: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_material_key(value: str) -> str:
    value = _BAD_SUFFIX.sub("", value.strip())
    return _MP_SEPARATOR.sub(r"-\1", value)


def _catalog_lookup(connection: Any) -> dict[str, int | None]:
    candidates: dict[str, list[int]] = {}
    for row in connection.execute("SELECT id, material_key FROM materials"):
        candidates.setdefault(_canonical_material_key(row["material_key"]), []).append(row["id"])
    return {
        key: values[0] if len(values) == 1 else None
        for key, values in candidates.items()
    }


def _iter_curve_files(roots: Iterable[str | Path]) -> Iterable[Path]:
    for root_value in roots:
        root = Path(root_value)
        if not root.is_dir():
            raise ValueError(f"QHA result root does not exist: {root}")
        yield from sorted(root.rglob("thermal_expansion.dat"))


def import_historical_qha_curves(
    database_path: str | Path, roots: Iterable[str | Path]
) -> QhaCurveImportSummary:
    """Import every explicitly supplied QHA curve and match it by its material directory."""
    roots = tuple(Path(root) for root in roots)
    initialize_database(database_path)
    scanned = parsed = imported = unmatched = invalid = 0
    unmatched_examples: list[str] = []
    invalid_examples: list[str] = []

    with connect_database(database_path) as connection:
        catalog = _catalog_lookup(connection)
        for path in _iter_curve_files(roots):
            scanned += 1
            material_id = catalog.get(_canonical_material_key(path.parent.name))
            if material_id is None:
                unmatched += 1
                if len(unmatched_examples) < 20:
                    unmatched_examples.append(str(path))
                continue
            try:
                curve = parse_thermal_expansion_file(path)
            except ValueError:
                invalid += 1
                if len(invalid_examples) < 20:
                    invalid_examples.append(str(path))
                continue
            parsed += 1
            import_historical_thermal_expansion_curve(
                connection,
                material_id=material_id,
                source_path=str(path.resolve()),
                thermal_expansion_curve=curve,
                alpha_300k_per_k=interpolate_alpha(curve, 300.0),
            )
            imported += 1

    return QhaCurveImportSummary(
        scanned_files=scanned,
        parsed_files=parsed,
        imported_curves=imported,
        unmatched_files=unmatched,
        invalid_files=invalid,
        unmatched_examples=tuple(unmatched_examples),
        invalid_examples=tuple(invalid_examples),
    )
