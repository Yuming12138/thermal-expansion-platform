import unittest

from te_platform.precision.script_compat import (
    NEW_THERMAL_COPY,
    NEW_THERMAL_INIT,
    NEW_THERMAL_COMMAND,
    OLD_IMPORT,
    OLD_THERMAL_COPY,
    OLD_THERMAL_COMMAND,
    make_qha_script_ase_compatible,
)


class ScriptCompatibilityTests(unittest.TestCase):
    def test_replaces_legacy_ase_import_once(self) -> None:
        patched = make_qha_script_ase_compatible(
            "from ase.constraints import ExpCellFilter\nprint('ok')\n"
        )
        self.assertIn("from ase.filters import ExpCellFilter", patched)
        self.assertEqual(patched, make_qha_script_ase_compatible(patched))

    def test_protects_every_thermal_properties_copy_idempotently(self) -> None:
        source = (
            f"{OLD_IMPORT}\n"
            "def collect():\n"
            f"    {OLD_THERMAL_COPY}\n"
            f"    {OLD_THERMAL_COMMAND}\n"
            "    do_other_work()\n"
            f"    {OLD_THERMAL_COPY}\n"
            f"    {OLD_THERMAL_COMMAND}\n"
        )

        patched = make_qha_script_ase_compatible(source)

        self.assertEqual(patched.count(NEW_THERMAL_COPY), 2)
        self.assertEqual(patched.count(NEW_THERMAL_INIT), 2)
        self.assertEqual(patched.count(NEW_THERMAL_COMMAND), 2)
        self.assertEqual(patched, make_qha_script_ase_compatible(patched))
        compile(patched, "patched_qha_calcu.py", "exec")


if __name__ == "__main__":
    unittest.main()
