from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        from ase.io import read, write

        atoms = read(args.input, format="cif")
        write(args.output, atoms, format="vasp", direct=True, vasp5=True)
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=__import__("sys").stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
