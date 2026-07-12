from __future__ import annotations

from functools import lru_cache
from itertools import combinations
import warnings

import numpy as np
from pymatgen.analysis.graphs import StructureGraph
from pymatgen.analysis.local_env import CrystalNN
from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Poscar


ImageVector = tuple[int, int, int]
SiteKey = tuple[int, ImageVector]


def _normalized_structure(content: str, structure_format: str) -> Structure:
    if structure_format.upper() in {"POSCAR", "VASP"}:
        structure = Poscar.from_str(content).structure
    else:
        structure = Structure.from_str(content, fmt=structure_format.lower())
    return Structure(
        structure.lattice,
        structure.species_and_occu,
        np.mod(structure.frac_coords, 1),
        site_properties=structure.site_properties,
    )


def _structure_graph(structure: Structure) -> StructureGraph:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="No oxidation states specified on sites!")
        warnings.filterwarnings("ignore", message="CrystalNN: cannot locate an appropriate radius.*")
        return StructureGraph.from_local_env_strategy(structure, CrystalNN())


def _boundary_image_sites(structure: Structure, tolerance: float = 0.05) -> set[SiteKey]:
    sites: set[SiteKey] = set()
    for site_index, site in enumerate(structure):
        near_zero = [axis for axis, value in enumerate(site.frac_coords) if np.isclose(value, 0, atol=tolerance)]
        near_one = [axis for axis, value in enumerate(site.frac_coords) if np.isclose(value, 1, atol=tolerance)]
        for axes in (
            combination
            for length in range(1, len(near_zero) + 1)
            for combination in combinations(near_zero, length)
        ):
            sites.add((site_index, tuple(int(axis in axes) for axis in range(3))))
        for axes in (
            combination
            for length in range(1, len(near_one) + 1)
            for combination in combinations(near_one, length)
        ):
            sites.add((site_index, tuple(-int(axis in axes) for axis in range(3))))
    return sites


def _element_symbol(structure: Structure, site_index: int) -> str:
    species = structure[site_index].species
    element = max(species.items(), key=lambda item: item[1])[0]
    return element.element.symbol if hasattr(element, "element") else element.symbol


@lru_cache(maxsize=512)
def build_structure_view(
    content: str,
    structure_format: str = "POSCAR",
) -> dict[str, object]:
    """Build a Materials Project-style periodic bond scene for the web viewer."""
    structure = _normalized_structure(content, structure_format)
    if len(structure) > 400:
        raise ValueError("structures with more than 400 sites use the basic viewer")
    graph = _structure_graph(structure)

    central_keys: list[SiteKey] = [(index, (0, 0, 0)) for index in range(len(structure))]
    sites_to_draw = set(central_keys)
    sites_to_draw.update(_boundary_image_sites(structure))

    # Follow one shell of graph edges so bonds crossing a periodic boundary end
    # at a real image atom instead of being shown as disconnected stubs.
    for site_index, image in list(sites_to_draw):
        for connected in graph.get_connected_sites(site_index, jimage=image):
            sites_to_draw.add(
                (connected.index, tuple(int(value) for value in connected.jimage))
            )

    image_keys = sorted(
        sites_to_draw.difference(central_keys),
        key=lambda item: (item[1], item[0]),
    )
    ordered_keys = central_keys + image_keys
    atom_index = {key: index for index, key in enumerate(ordered_keys)}

    atoms: list[dict[str, object]] = []
    for site_index, image in ordered_keys:
        fractional = structure[site_index].frac_coords + np.asarray(image)
        x, y, z = structure.lattice.get_cartesian_coords(fractional)
        atoms.append(
            {
                "element": _element_symbol(structure, site_index),
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "central": image == (0, 0, 0),
                "site_index": site_index,
                "image": list(image),
                "bonds": [],
            }
        )

    bond_pairs: set[tuple[int, int]] = set()
    for key, left_index in atom_index.items():
        site_index, image = key
        for connected in graph.get_connected_sites(site_index, jimage=image):
            target_key = (
                connected.index,
                tuple(int(value) for value in connected.jimage),
            )
            if target_key not in atom_index:
                continue
            right_index = atom_index[target_key]
            if left_index == right_index:
                continue
            bond_pairs.add(tuple(sorted((left_index, right_index))))

    for left_index, right_index in sorted(bond_pairs):
        atoms[left_index]["bonds"].append(right_index)  # type: ignore[index]
        atoms[right_index]["bonds"].append(left_index)  # type: ignore[index]

    return {
        "source": "pymatgen.CrystalNN",
        "atoms": atoms,
        "lattice": structure.lattice.matrix.tolist(),
        "central_count": len(central_keys),
        "periodic_count": len(image_keys),
        "bond_count": len(bond_pairs),
    }
