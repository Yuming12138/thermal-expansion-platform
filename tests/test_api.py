import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from te_platform.api.app import create_app
from te_platform.agent.tools import default_registry
from te_platform.config import DEFAULT_CATALOG_DATABASE_PATH
from te_platform.workers.alignn_runner import AlignnWorkerPrediction
from te_platform.workers.mattersim_runner import MatterSimPrediction


POSCAR = b"""BaCrSi4O10
1.0
5.000000 0.000000 0.000000
0.000000 5.000000 0.000000
0.000000 0.000000 5.000000
Ba Cr Si O
1 1 4 10
Direct
"""

CIF = b"""data_example
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
Ba1 Ba 0 0 0
"""


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_directory = tempfile.TemporaryDirectory()
        cls.workspace_database = Path(cls.temp_directory.name) / "workspace.sqlite"
        cls.catalog_hash_before = hashlib.sha256(
            DEFAULT_CATALOG_DATABASE_PATH.read_bytes()
        ).hexdigest()
        cls.client_context = TestClient(
            create_app(
                catalog_database=DEFAULT_CATALOG_DATABASE_PATH,
                workspace_database=cls.workspace_database,
            )
        )
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        catalog_hash_after = hashlib.sha256(
            DEFAULT_CATALOG_DATABASE_PATH.read_bytes()
        ).hexdigest()
        if catalog_hash_after != cls.catalog_hash_before:
            raise AssertionError("API tests modified the immutable catalog database")
        cls.temp_directory.cleanup()

    def test_health_and_dataset_summary(self) -> None:
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("热膨胀材料智能计算与设计平台", home.text)
        self.assertIn("/static/app.js?v=0.10.0-4", home.text)
        for workspace_path in ["/database", "/predict", "/landscape", "/zte", "/about"]:
            workspace_page = self.client.get(workspace_path)
            self.assertEqual(workspace_page.status_code, 200)
            self.assertIn("科研工作区导航", workspace_page.text)
            self.assertIn("当前研究材料", workspace_page.text)
        landscape_material = self.client.get("/landscape?material=Ag%28AuF4%292-mp-18125")
        self.assertEqual(landscape_material.status_code, 200)

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["material_count"], 6701)
        self.assertEqual(health.json()["catalog_database"], "catalog-v1.sqlite")
        self.assertEqual(health.json()["workspace_database"], "workspace.sqlite")
        self.assertTrue(self.workspace_database.is_file())

        about = self.client.get("/api/about")
        self.assertEqual(about.status_code, 200)
        self.assertEqual(about.json()["software"]["version"], "0.10.0")
        self.assertEqual(about.json()["datasets"]["catalog_materials"], 6886)
        self.assertIn("160.21766208", about.json()["descriptor"]["bonding_modulus"])

        dataset = self.client.get("/api/datasets/current")
        self.assertEqual(dataset.status_code, 200)
        self.assertEqual(dataset.json()["counts"]["materials"], 6701)

        fig1d = self.client.get("/static/fig1d-reference.json")
        self.assertEqual(fig1d.status_code, 200)
        self.assertEqual(len(fig1d.json()["points"]), 354)
        self.assertAlmostEqual(fig1d.json()["axis"]["boundary_c"], 2.84151)

        viewer_library = self.client.get("/static/vendor/3Dmol-2.5.5.min.js")
        self.assertEqual(viewer_library.status_code, 200)
        self.assertGreater(len(viewer_library.content), 500_000)

    def test_material_search_detail_and_landscape(self) -> None:
        materials = self.client.get("/api/materials", params={"query": "BaCrSi4O10"})
        self.assertEqual(materials.status_code, 200)
        self.assertGreaterEqual(len(materials.json()), 1)
        material_summary = materials.json()[0]
        material_key = material_summary["material_key"]

        element_stats = self.client.get("/api/materials/elements")
        self.assertEqual(element_stats.status_code, 200)
        self.assertEqual(element_stats.json()["material_count"], 6701)
        self.assertGreater(element_stats.json()["elements"]["O"], 0)

        exact_elements = self.client.get(
            "/api/materials",
            params={
                "query": "BaCrSi4O10",
                "elements": "Ba,Cr,Si,O",
                "element_mode": "exact",
            },
        )
        self.assertEqual(exact_elements.status_code, 200)
        self.assertGreaterEqual(len(exact_elements.json()), 1)

        detail = self.client.get(f"/api/materials/{material_key}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["material"]["material_key"], material_key)
        properties = detail.json()["properties"]
        expected_bonding = (
            160.21766208
            * abs(properties["E_coh_eV_per_atom"]["value"])
            / (properties["AAV"]["value"] * properties["avg_cn"]["value"])
        )
        self.assertAlmostEqual(properties["E_tilde_GPa"]["value"], expected_bonding)
        self.assertAlmostEqual(material_summary["E_tilde_GPa"], expected_bonding)
        self.assertEqual(material_summary["E_tilde_source"], "paper_definition_UV_over_n")
        self.assertAlmostEqual(
            material_summary["xi"],
            material_summary["G_GPa"] / material_summary["E_tilde_GPa"],
        )
        self.assertEqual(detail.json()["dataset_release"]["version"], "1.1.0")
        self.assertIn("ALIGNN", detail.json()["method_notes"]["G_GPa"])
        structure = detail.json()["structures"][0]
        self.assertEqual(structure["format"], "POSCAR")
        self.assertGreater(len(structure["content"]), 100)
        self.assertEqual(len(structure["content_sha256"]), 64)
        structure_view = detail.json()["structure_view"]
        self.assertEqual(structure_view["source"], "pymatgen.CrystalNN")
        self.assertGreater(structure_view["central_count"], 0)
        self.assertGreater(structure_view["bond_count"], 0)
        curve = detail.json()["precision_thermal_expansion"]
        self.assertIsNotNone(curve)
        self.assertGreaterEqual(len(curve["points"]), 2)

        ranked = self.client.get(
            "/api/materials",
            params={
                "limit": 5,
                "sort_by": "CTE_ppm",
                "sort_order": "ascending",
                "cte_max_ppm": -5,
            },
        )
        self.assertEqual(ranked.status_code, 200)
        ranked_items = ranked.json()
        self.assertEqual(len(ranked_items), 5)
        self.assertTrue(all(item["CTE_ppm"] <= -5 for item in ranked_items))
        self.assertEqual(
            [item["CTE_ppm"] for item in ranked_items],
            sorted(item["CTE_ppm"] for item in ranked_items),
        )
        compare_keys = [ranked_items[0]["material_key"], ranked_items[1]["material_key"]]
        comparison = self.client.get(
            "/api/materials/compare",
            params={"material_keys": "|".join(compare_keys), "temperature_k": 300},
        )
        self.assertEqual(comparison.status_code, 200)
        self.assertEqual(comparison.json()["material_count"], 2)
        self.assertIn("alpha(T)", comparison.json()["method_note"])
        self.assertEqual(
            [item["material"]["material_key"] for item in comparison.json()["materials"]],
            compare_keys,
        )
        registry = default_registry(DEFAULT_CATALOG_DATABASE_PATH)
        self.assertIn("compare_catalog_materials", registry.names())
        agent_comparison = registry.call(
            "compare_catalog_materials",
            role="nte",
            material_keys=compare_keys,
            temperature_k=300,
        )
        self.assertEqual(agent_comparison["material_count"], 2)

        poscar_download = self.client.get(
            f"/api/materials/{material_key}/download/POSCAR"
        )
        self.assertEqual(poscar_download.status_code, 200)
        self.assertIn("attachment", poscar_download.headers["content-disposition"])
        self.assertIn("Ba", poscar_download.text)

        dat_download = self.client.get(
            f"/api/materials/{material_key}/download/thermal_expansion.dat"
        )
        self.assertEqual(dat_download.status_code, 200)
        self.assertIn("temperature_K", dat_download.text)
        data_lines = [
            line for line in dat_download.text.splitlines() if line and not line.startswith("#")
        ]
        self.assertGreaterEqual(len(data_lines), 2)
        self.assertLess(abs(float(data_lines[0].split()[1])), 1)

        curve_pdf = self.client.get(
            f"/api/materials/{material_key}/download/thermal_expansion.pdf"
        )
        self.assertEqual(curve_pdf.status_code, 200)
        self.assertTrue(curve_pdf.content.startswith(b"%PDF"))
        self.assertGreater(len(curve_pdf.content), 5_000)

        comparison_pdf = self.client.get(
            "/api/materials/compare/report.pdf",
            params={
                "material_keys": "|".join(compare_keys),
                "temperature_k": 300,
                "project_name": "强 NTE 候选对比",
            },
        )
        self.assertEqual(comparison_pdf.status_code, 200)
        self.assertTrue(comparison_pdf.content.startswith(b"%PDF"))
        self.assertGreater(len(comparison_pdf.content), 8_000)
        self.assertIn("filename*=UTF-8''", comparison_pdf.headers["content-disposition"])
        self.assertIn("%E5%BC%BA%20NTE", comparison_pdf.headers["content-disposition"])

        landscape = self.client.get("/api/materials/landscape", params={"limit": 10})
        self.assertEqual(landscape.status_code, 200)
        self.assertGreaterEqual(len(landscape.json()), 1)

    def test_scientific_calculation_endpoints(self) -> None:
        sbr = self.client.post(
            "/api/sbr/classify",
            json={"shear_modulus_gpa": 20.0, "bonding_modulus_gpa": 10.0},
        )
        self.assertEqual(sbr.status_code, 200)
        self.assertEqual(sbr.json()["classification"], "high_probability_nte")

        fast = self.client.post(
            "/api/sbr/fast-screen",
            json={
                "predicted_shear_modulus_gpa": 10.0,
                "cohesive_energy_ev_per_atom": -5.0,
                "cell_volume_a3": 50.0,
                "atom_count": 10,
                "average_coordination_number": 3.0,
                "shear_model_mae_gpa": 2.0,
            },
        )
        self.assertEqual(fast.status_code, 200)
        self.assertEqual(fast.json()["decision_quality"], "robust_high_probability_nte")

        rom = self.client.post(
            "/api/composites/rom",
            json={"alpha_pte": 8.0, "alpha_nte": -12.0, "target_alpha": 0.0},
        )
        self.assertEqual(rom.status_code, 200)
        self.assertAlmostEqual(rom.json()["nte_volume_fraction"], 0.4)
        curve = self.client.post(
            "/api/composites/curve-rom",
            json={"pte_alpha": [8, 10], "nte_alpha": [-12, -15], "pte_density": 2, "nte_density": 4},
        )
        self.assertEqual(curve.status_code, 200)
        self.assertAlmostEqual(curve.json()["nte_volume_fraction"], 0.4)

    @patch("te_platform.api.app.optimize_material_pair")
    @patch("te_platform.api.app.curve_materials")
    def test_curve_material_search_and_design_endpoints(self, materials_mock, optimize_mock) -> None:
        materials_mock.return_value = [{"material_key": "1.CaO", "alpha_300k_ppm_per_k": 12.0}]
        optimize_mock.return_value = {
            "nte_volume_fraction": 0.4,
            "temperatures_k": [300.0, 600.0],
            "mixed_alpha_ppm_per_k": [0.0, 0.2],
        }
        choices = self.client.get("/api/composites/materials", params={"role": "pte"})
        design = self.client.post(
            "/api/composites/curve-design",
            json={
                "pte_material_key": "1.CaO",
                "nte_material_key": "NTE-mp-1",
                "temperature_min_k": 300,
                "temperature_max_k": 600,
            },
        )
        self.assertEqual(choices.status_code, 200)
        self.assertEqual(choices.json()[0]["material_key"], "1.CaO")
        self.assertEqual(materials_mock.call_args.args[1:], ("pte-reference-185-v1", "", 30))
        self.assertEqual(materials_mock.call_args.kwargs, {"alpha_sign": 1})
        self.assertEqual(design.status_code, 200)
        self.assertAlmostEqual(design.json()["nte_volume_fraction"], 0.4)

    def test_agent_tools_are_allowlisted(self) -> None:
        tools = self.client.get("/api/agent/tools")
        self.assertEqual(tools.status_code, 200)
        self.assertIn("classify_sbr", tools.json()["tools"])
        allowed = self.client.post(
            "/api/agent/call",
            json={"tool": "classify_sbr", "arguments": {"shear_modulus_gpa": 20, "bonding_modulus_gpa": 10}},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["result"]["classification"], "high_probability_nte")
        denied = self.client.post("/api/agent/call", json={"tool": "shell", "arguments": {}})
        self.assertEqual(denied.status_code, 422)
        model_response = {
            "mode": "llm",
            "model": "gpt-5.6-luna",
            "answer": "该材料具有较高NTE倾向。",
            "tool_calls": [{"tool": "classify_sbr"}],
        }
        with patch(
            "te_platform.api.app.chat_with_model",
            new=AsyncMock(return_value=model_response),
        ):
            chat = self.client.post(
                "/api/agent/chat",
                json={
                    "message": "请继续判断这个材料",
                    "history": [
                        {"role": "user", "content": "先搜索材料"},
                        {"role": "assistant", "content": "已找到候选材料"},
                    ],
                },
            )
        self.assertEqual(chat.status_code, 200)
        self.assertEqual(chat.json()["model"], "gpt-5.6-luna")
        self.assertEqual(chat.json()["tool_calls"][0]["tool"], "classify_sbr")
        capability = self.client.get("/api/agent/capability")
        self.assertEqual(capability.status_code, 200)
        self.assertEqual(capability.json()["model"], "gpt-5.6-luna")

    def test_agent_structure_qha_request_requires_explicit_approval(self) -> None:
        upload = self.client.post(
            "/api/agent/structures",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        self.assertEqual(upload.status_code, 200)
        structure_id = upload.json()["structure_id"]
        request = self.client.post(
            "/api/agent/call",
            json={
                "tool": "request_qha_calculation",
                "arguments": {"structure_id": structure_id, "qha_points": 7},
            },
        )
        self.assertEqual(request.status_code, 200)
        approval = request.json()["result"]
        self.assertTrue(approval["approval_required"])
        self.assertEqual(approval["status"], "PENDING_APPROVAL")

        fake_job = {
            "id": "agent-qha-123",
            "workflow": "precision_qha",
            "status": "PENDING",
        }
        with patch("te_platform.api.app.submit_qha_job", return_value=fake_job) as submit_mock:
            approved = self.client.post(
                f"/api/agent/approvals/{approval['approval_id']}/approve"
            )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["approval"]["status"], "EXECUTED")
        self.assertEqual(approved.json()["job"]["id"], "agent-qha-123")
        self.assertEqual(submit_mock.call_args.args[0], self.workspace_database)
        self.assertEqual(submit_mock.call_args.args[2].qha_points, 7)

        duplicate = self.client.post(
            f"/api/agent/approvals/{approval['approval_id']}/approve"
        )
        self.assertEqual(duplicate.status_code, 422)

    def test_agent_routes_fast_and_elastic_modes_through_approval(self) -> None:
        upload = self.client.post(
            "/api/agent/structures",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        structure_id = upload.json()["structure_id"]
        cases = (
            ("fast", "te_platform.api.app.submit_fast_screen_job", "fast-job", "fast_structure_screening"),
            ("elastic", "te_platform.api.app.submit_elastic_job", "elastic-job", "precision_elastic"),
        )
        for mode, patch_target, job_id, workflow in cases:
            with self.subTest(mode=mode):
                request = self.client.post(
                    "/api/agent/call",
                    json={
                        "tool": "request_structure_calculation",
                        "arguments": {"structure_id": structure_id, "mode": mode},
                    },
                )
                self.assertEqual(request.status_code, 200)
                approval = request.json()["result"]
                self.assertEqual(approval["mode"], mode)
                fake_job = {"id": job_id, "workflow": workflow, "status": "PENDING"}
                with patch(patch_target, return_value=fake_job) as submit_mock:
                    approved = self.client.post(
                        f"/api/agent/approvals/{approval['approval_id']}/approve"
                    )
                self.assertEqual(approved.status_code, 200)
                self.assertEqual(approved.json()["job"]["workflow"], workflow)
                submit_mock.assert_called_once()

    def test_agent_qha_request_can_be_rejected_without_starting_job(self) -> None:
        upload = self.client.post(
            "/api/agent/structures",
            files={"file": ("sample.cif", CIF, "text/plain")},
        )
        structure_id = upload.json()["structure_id"]
        request = self.client.post(
            "/api/agent/call",
            json={
                "tool": "request_qha_calculation",
                "arguments": {"structure_id": structure_id},
            },
        ).json()["result"]
        rejected = self.client.post(
            f"/api/agent/approvals/{request['approval_id']}/reject"
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["approval"]["status"], "REJECTED")

    def test_structure_inspection_for_poscar_and_cif(self) -> None:
        poscar = self.client.post(
            "/api/structures/inspect",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        self.assertEqual(poscar.status_code, 200)
        self.assertEqual(poscar.json()["inspection"]["atom_count"], 16)
        self.assertAlmostEqual(poscar.json()["inspection"]["cell_volume_a3"], 125.0)

        cif = self.client.post(
            "/api/structures/inspect",
            files={"file": ("example.cif", CIF, "text/plain")},
        )
        self.assertEqual(cif.status_code, 200)
        self.assertAlmostEqual(cif.json()["inspection"]["cell_volume_a3"], 125.0)

    @patch("te_platform.api.app.predict_alignn_shear")
    def test_alignn_shear_endpoint_uses_controlled_worker(self, prediction_mock) -> None:
        prediction_mock.return_value = AlignnWorkerPrediction(
            prediction={"shear_modulus_gpa": 29.53, "device": "cpu"},
            worker_seconds=3.2,
            configuration={"python_executable": "test-python"},
        )
        response = self.client.post(
            "/api/structures/alignn-shear",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["alignn"]["prediction"]["shear_modulus_gpa"], 29.53)
        self.assertEqual(len(response.json()["structure_sha256"]), 64)
        prediction_mock.assert_called_once()

    @patch("te_platform.api.app.predict_mattersim_descriptors")
    @patch("te_platform.api.app.predict_alignn_shear")
    def test_fast_screen_endpoint_combines_controlled_workers(
        self, alignn_mock, mattersim_mock
    ) -> None:
        alignn_mock.return_value = AlignnWorkerPrediction(
            prediction={"shear_modulus_gpa": 10.0},
            worker_seconds=3.0,
            configuration={},
        )
        mattersim_mock.return_value = MatterSimPrediction(
            descriptors={
                "cohesive_energy_ev_per_atom": -5.0,
                "atom_count": 16,
                "average_coordination_number": 3.0,
            },
            worker_seconds=2.0,
        )
        response = self.client.post(
            "/api/structures/fast-screen",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["fast_sbr"]["decision_quality"],
            "robust_high_probability_nte",
        )

    @patch("te_platform.api.app.submit_precision_job")
    def test_precision_job_submission_endpoint(self, submission_mock) -> None:
        submission_mock.return_value = {"id": "job-123", "status": "PENDING"}
        response = self.client.post(
            "/api/precision/jobs",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "job-123")
        self.assertEqual(submission_mock.call_args.args[0], self.workspace_database)

    @patch("te_platform.api.app.submit_elastic_job")
    def test_elastic_job_submission_endpoint(self, submission_mock) -> None:
        submission_mock.return_value = {"id": "elastic-123", "status": "PENDING"}
        response = self.client.post(
            "/api/precision/elastic-jobs",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "elastic-123")
        self.assertEqual(submission_mock.call_args.args[0], self.workspace_database)

    @patch("te_platform.api.app.submit_qha_job")
    def test_qha_job_submission_endpoint(self, submission_mock) -> None:
        submission_mock.return_value = {"id": "qha-123", "status": "PENDING"}
        response = self.client.post(
            "/api/precision/qha-jobs",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "qha-123")
        self.assertEqual(submission_mock.call_args.args[0], self.workspace_database)

    @patch("te_platform.api.app.refresh_precision_result")
    def test_precision_result_refresh_endpoint(self, refresh_mock) -> None:
        refresh_mock.return_value = {
            "id": "job-123",
            "status": "SUCCEEDED",
            "result": {"quality_warnings": ["Imaginary phonon frequencies were detected"]},
        }

        response = self.client.post("/api/precision/jobs/job-123/refresh-result")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        refresh_mock.assert_called_once()
        self.assertEqual(refresh_mock.call_args.args[0], self.workspace_database)


if __name__ == "__main__":
    unittest.main()
