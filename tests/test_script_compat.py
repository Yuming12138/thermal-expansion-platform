import unittest

from te_platform.precision.script_compat import make_qha_script_ase_compatible


class ScriptCompatibilityTests(unittest.TestCase):
    def test_replaces_legacy_ase_import_once(self) -> None:
        patched = make_qha_script_ase_compatible(
            "from ase.constraints import ExpCellFilter\nprint('ok')\n"
        )
        self.assertIn("from ase.filters import ExpCellFilter", patched)
        self.assertEqual(patched, make_qha_script_ase_compatible(patched))


if __name__ == "__main__":
    unittest.main()
