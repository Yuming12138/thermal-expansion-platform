from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


RESULT_PREFIX = "TEP_MATTERSIM_RESULT="


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--model", default="mattersim-v1.0.0-5M")
    args = parser.parse_args()
    try:
        from ase.io import read
        from mattersim.forcefield import MatterSimCalculator, Potential
        from pymatgen.analysis.local_env import CrystalNN
        from pymatgen.core import Structure

        started = time.perf_counter()
        atoms = read(args.structure, format="cif" if args.structure.suffix.lower() == ".cif" else "vasp")
        potential = Potential.from_checkpoint(
            model_name="m3gnet",
            load_path=args.model,
            device="cpu",
            load_training_state=False,
        )
        atoms.calc = MatterSimCalculator(potential=potential, device="cpu")
        energy_ev = float(atoms.get_potential_energy())
        structure = Structure.from_file(args.structure)
        crystal_nn = CrystalNN()
        coordination = [float(crystal_nn.get_cn(structure, index)) for index in range(len(structure))]
        result = {
            "cohesive_energy_ev_per_atom": energy_ev / len(atoms),
            "total_energy_ev": energy_ev,
            "atom_count": len(atoms),
            "average_coordination_number": sum(coordination) / len(coordination),
            "model_name": args.model,
            "device": "cpu",
            "inference_seconds": time.perf_counter() - started,
        }
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=__import__("sys").stderr)
        return 2
    print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
