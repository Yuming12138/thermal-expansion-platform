import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from te_platform.api.services import ensure_catalog_database
from te_platform.config import DEFAULT_PTE_RELEASE_SLUG, DEFAULT_RELEASE_SLUG


class CatalogInstallerTests(unittest.TestCase):
    def test_installs_and_verifies_catalog_from_public_bundle_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_catalog = root / "source.sqlite"
            connection = sqlite3.connect(source_catalog)
            try:
                connection.execute("CREATE TABLE dataset_releases(slug TEXT NOT NULL)")
                connection.executemany(
                    "INSERT INTO dataset_releases(slug) VALUES (?)",
                    [(DEFAULT_RELEASE_SLUG,), (DEFAULT_PTE_RELEASE_SLUG,)],
                )
                connection.commit()
            finally:
                connection.close()
            catalog_sha256 = hashlib.sha256(source_catalog.read_bytes()).hexdigest()
            source_manifest = root / "source.sqlite.manifest.json"
            source_manifest.write_text(
                json.dumps(
                    {
                        "file_bytes": source_catalog.stat().st_size,
                        "database_sha256": catalog_sha256,
                    }
                ),
                encoding="utf-8",
            )

            bundle = root / "thermal-expansion-platform-portable.zip"
            package_root = "thermal-expansion-platform-v-test-portable"
            with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(
                    source_catalog,
                    f"{package_root}/var/releases/catalog-v1.sqlite",
                )
                archive.write(
                    source_manifest,
                    f"{package_root}/var/releases/catalog-v1.sqlite.manifest.json",
                )
            checksum = root / "bundle.zip.sha256"
            checksum.write_text(
                f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  {bundle.name}\n",
                encoding="ascii",
            )

            installed = root / "install" / "catalog-v1.sqlite"
            ensure_catalog_database(
                installed,
                allow_download=True,
                bundle_url=bundle.as_uri(),
                checksum_url=checksum.as_uri(),
            )

            self.assertTrue(installed.is_file())
            self.assertTrue(
                installed.with_suffix(".sqlite.manifest.json").is_file()
            )
            self.assertEqual(
                hashlib.sha256(installed.read_bytes()).hexdigest(), catalog_sha256
            )


if __name__ == "__main__":
    unittest.main()
