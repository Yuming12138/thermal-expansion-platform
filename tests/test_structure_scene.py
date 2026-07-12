import unittest

from te_platform.structures.scene import build_structure_view


POSCAR = """NaCl
1.0
3.5 0.0 0.0
0.0 3.5 0.0
0.0 0.0 3.5
Na Cl
1 1
Direct
0.0 0.0 0.0
0.5 0.5 0.5
"""


class StructureSceneTests(unittest.TestCase):
    def test_builds_periodic_crystalnn_scene(self) -> None:
        scene = build_structure_view(POSCAR)

        self.assertEqual(scene["source"], "pymatgen.CrystalNN")
        self.assertEqual(scene["central_count"], 2)
        self.assertGreater(scene["periodic_count"], 0)
        self.assertGreater(scene["bond_count"], 0)
        self.assertEqual(len(scene["lattice"]), 3)
        self.assertEqual(len(scene["atoms"]), scene["central_count"] + scene["periodic_count"])


if __name__ == "__main__":
    unittest.main()
