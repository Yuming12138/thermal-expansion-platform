from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


RESULT_PREFIX = "TEP_ALIGNN_RESULT="


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--alignn-source", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_root = Path(__file__).resolve().parents[2]
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from te_platform.screening.alignn_shear import AlignnShearPredictor

    try:
        predictor = AlignnShearPredictor(args.alignn_source, args.model_dir)
        result = predictor.predict_file(args.structure)
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(RESULT_PREFIX + json.dumps(result.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
