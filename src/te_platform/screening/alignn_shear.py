from __future__ import annotations

import importlib.util
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from te_platform.catalog.provenance import sha256_file


ALIGNN_TEST_MAE_GPA = 9.476007
ALIGNN_TEST_RMSE_GPA = 17.796999
ALIGNN_TEST_R2 = 0.769104


@dataclass(frozen=True)
class AlignnEnvironmentStatus:
    ready: bool
    missing_modules: tuple[str, ...]
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AlignnShearPrediction:
    shear_modulus_gpa: float
    inference_seconds: float
    model_name: str
    model_target: str
    checkpoint_sha256: str
    model_test_mae_gpa: float
    device: str

    def to_dict(self) -> dict[str, float | str]:
        return asdict(self)


class AlignnShearPredictor:
    """Lazy, reusable ALIGNN predictor for the JARVIS shear modulus model."""

    def __init__(self, alignn_source_root: str | Path, model_dir: str | Path) -> None:
        self.alignn_source_root = Path(alignn_source_root).resolve()
        self.model_dir = Path(model_dir).resolve()
        self._model: Any | None = None
        self._torch: Any | None = None
        self._graph_class: Any | None = None
        self._device: Any | None = None
        self._config: dict[str, Any] | None = None
        self._checkpoint_path: Path | None = None

    def environment_status(self) -> AlignnEnvironmentStatus:
        source = str(self.alignn_source_root)
        if source not in sys.path:
            sys.path.insert(0, source)
        missing = tuple(
            module
            for module in ("torch", "dgl", "jarvis", "alignn")
            if importlib.util.find_spec(module) is None
        )
        issues: list[str] = []
        if not self.alignn_source_root.is_dir():
            issues.append(f"ALIGNN source root does not exist: {self.alignn_source_root}")
        if not (self.model_dir / "config.json").is_file():
            issues.append(f"ALIGNN model config does not exist: {self.model_dir}")
        try:
            import numpy as np

            if int(np.__version__.split(".", 1)[0]) >= 2:
                issues.append("This ALIGNN checkout requires numpy<2.0")
        except Exception:
            if "numpy" not in missing:
                issues.append("NumPy could not be inspected")
        return AlignnEnvironmentStatus(
            ready=not missing and not issues,
            missing_modules=missing,
            issues=tuple(issues),
        )

    def _select_checkpoint(self) -> Path:
        best = self.model_dir / "best_model.pt"
        if best.is_file():
            return best
        checkpoints = list(self.model_dir.glob("checkpoint_*.pt"))
        if not checkpoints:
            raise FileNotFoundError(f"No ALIGNN checkpoint found in {self.model_dir}")

        def checkpoint_number(path: Path) -> int:
            try:
                return int(path.stem.removeprefix("checkpoint_"))
            except ValueError:
                return -1

        return max(checkpoints, key=checkpoint_number)

    def load(self) -> None:
        if self._model is not None:
            return
        status = self.environment_status()
        if not status.ready:
            details = "; ".join((*status.missing_modules, *status.issues))
            raise RuntimeError(f"ALIGNN prediction environment is not ready: {details}")

        import dgl
        import torch
        from alignn.graphs import Graph
        from alignn.models.alignn import ALIGNN, ALIGNNConfig

        config_path = self.model_dir / "config.json"
        with config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        checkpoint = self._select_checkpoint()
        model = ALIGNN(ALIGNNConfig(**config["model"]))
        state = torch.load(checkpoint, map_location="cpu")
        if isinstance(state, dict) and "model" in state:
            state = state["model"]
        model.load_state_dict(state)
        device = torch.device("cpu")
        if torch.cuda.is_available():
            try:
                dgl.graph(([0], [0])).to(torch.device("cuda"))
                device = torch.device("cuda")
            except Exception:
                device = torch.device("cpu")
        model.to(device)
        model.eval()

        self._torch = torch
        self._graph_class = Graph
        self._device = device
        self._config = config
        self._checkpoint_path = checkpoint
        self._model = model

    def _atoms_from_file(self, structure_path: str | Path) -> Any:
        from jarvis.core.atoms import Atoms

        path = Path(structure_path).resolve()
        if path.suffix.lower() == ".cif":
            return Atoms.from_cif(str(path))
        return Atoms.from_poscar(str(path))

    def predict_file(self, structure_path: str | Path) -> AlignnShearPrediction:
        self.load()
        atoms = self._atoms_from_file(structure_path)
        assert self._config is not None
        assert self._graph_class is not None
        assert self._torch is not None
        assert self._checkpoint_path is not None
        options = self._config
        graph, line_graph = self._graph_class.atom_dgl_multigraph(
            atoms,
            neighbor_strategy=options.get("neighbor_strategy", "k-nearest"),
            cutoff=float(options.get("cutoff", 8.0)),
            max_neighbors=int(options.get("max_neighbors", 12)),
            atom_features=options.get("atom_features", "cgcnn"),
            compute_line_graph=True,
            use_canonize=bool(options.get("use_canonize", True)),
        )
        lattice = self._torch.tensor(
            atoms.lattice_mat, dtype=self._torch.get_default_dtype()
        )
        started = time.perf_counter()
        with self._torch.no_grad():
            output = self._model(
                [
                    graph.to(self._device),
                    line_graph.to(self._device),
                    lattice.to(self._device),
                ]
            )
        elapsed = time.perf_counter() - started
        value = float(output.detach().cpu().reshape(-1)[0].item())
        return AlignnShearPrediction(
            shear_modulus_gpa=value,
            inference_seconds=elapsed,
            model_name="jv_shear_modulus_gv_alignn",
            model_target=str(options.get("target", "shear_modulus_gv")),
            checkpoint_sha256=sha256_file(self._checkpoint_path),
            model_test_mae_gpa=ALIGNN_TEST_MAE_GPA,
            device=str(self._device),
        )
