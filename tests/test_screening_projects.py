import tempfile
import unittest
from pathlib import Path

from te_platform.composites.projects import (
    delete_screening_project,
    get_screening_project,
    list_screening_projects,
    save_screening_project,
)
from te_platform.db.schema import initialize_database


class ScreeningProjectTests(unittest.TestCase):
    def test_saves_lists_loads_and_deletes_screening_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "workspace.sqlite"
            initialize_database(database)
            saved = save_screening_project(
                database,
                project_name="300-800 K candidates",
                screening_parameters={"model": "turner", "temperature_min_k": 300},
                screening_result={"results": [{"rank": 1}, {"rank": 2}]},
                selected_pairs=[
                    {"pte_material_key": "1.CaO", "nte_material_key": "NTE-1", "rank": 1}
                ],
            )

            projects = list_screening_projects(database)
            loaded = get_screening_project(database, saved["id"])

            self.assertEqual(projects[0]["project_name"], "300-800 K candidates")
            self.assertEqual(projects[0]["result_count"], 2)
            self.assertEqual(loaded["screening_parameters"]["model"], "turner")
            self.assertEqual(loaded["selected_pairs"][0]["rank"], 1)
            self.assertTrue(delete_screening_project(database, saved["id"]))
            self.assertEqual(list_screening_projects(database), [])


if __name__ == "__main__":
    unittest.main()
