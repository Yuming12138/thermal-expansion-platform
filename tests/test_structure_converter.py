import tempfile
import unittest
from pathlib import Path

from te_platform.workers.structure_converter import write_precision_poscar


class StructureConverterTests(unittest.TestCase):
    def test_writes_poscar_input_without_external_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            content = b"POSCAR content"
            output = write_precision_poscar(temp, filename="POSCAR", content=content)
            self.assertEqual(output.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
