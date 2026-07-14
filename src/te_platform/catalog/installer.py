from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


PUBLIC_CATALOG_BUNDLE_URL = (
    "https://github.com/Yuming12138/thermal-expansion-platform/releases/download/"
    "v0.10.0/thermal-expansion-platform-v0.10.0-portable.zip"
)
PUBLIC_CATALOG_BUNDLE_CHECKSUM_URL = PUBLIC_CATALOG_BUNDLE_URL + ".sha256"
CATALOG_ARCHIVE_SUFFIX = "/var/releases/catalog-v1.sqlite"
CATALOG_MANIFEST_ARCHIVE_SUFFIX = "/var/releases/catalog-v1.sqlite.manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={"User-Agent": "thermal-expansion-platform-catalog-installer/1"},
    )


def _read_text(url: str, timeout_seconds: float) -> str:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(_request(url), timeout=timeout_seconds) as response:
                return response.read().decode("utf-8")
        except (OSError, urllib.error.URLError):
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Unreachable catalog checksum retry state")


def _download(url: str, destination: Path, timeout_seconds: float) -> None:
    for attempt in range(4):
        try:
            with (
                urllib.request.urlopen(_request(url), timeout=timeout_seconds) as response,
                destination.open("wb") as output,
            ):
                shutil.copyfileobj(response, output, length=1024 * 1024)
            return
        except (OSError, urllib.error.URLError):
            destination.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def _archive_member(archive: zipfile.ZipFile, suffix: str) -> str:
    normalized_suffix = suffix.lstrip("/")
    matches = [
        name
        for name in archive.namelist()
        if name == normalized_suffix or name.endswith(suffix)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Portable bundle must contain exactly one {normalized_suffix}; found {len(matches)}"
        )
    return matches[0]


def _validate_catalog(catalog: Path, manifest: Path) -> None:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    expected_bytes = int(payload["file_bytes"])
    expected_sha256 = str(payload["database_sha256"]).lower()
    if catalog.stat().st_size != expected_bytes:
        raise RuntimeError("Downloaded catalog byte count does not match its manifest")
    if sha256_file(catalog) != expected_sha256:
        raise RuntimeError("Downloaded catalog SHA-256 does not match its manifest")


def install_catalog_from_public_bundle(
    catalog_path: str | Path,
    *,
    bundle_url: str | None = None,
    checksum_url: str | None = None,
    timeout_seconds: float = 180.0,
) -> Path:
    """Download the public portable bundle and atomically install its catalog."""
    catalog = Path(catalog_path)
    manifest = catalog.with_suffix(catalog.suffix + ".manifest.json")
    catalog.parent.mkdir(parents=True, exist_ok=True)
    selected_bundle_url = bundle_url or os.environ.get(
        "TEP_CATALOG_BUNDLE_URL", PUBLIC_CATALOG_BUNDLE_URL
    )
    selected_checksum_url = checksum_url or os.environ.get(
        "TEP_CATALOG_BUNDLE_CHECKSUM_URL",
        selected_bundle_url + ".sha256"
        if bundle_url or os.environ.get("TEP_CATALOG_BUNDLE_URL")
        else PUBLIC_CATALOG_BUNDLE_CHECKSUM_URL,
    )

    with tempfile.TemporaryDirectory(
        prefix="catalog-install-", dir=catalog.parent
    ) as temporary_directory:
        staging = Path(temporary_directory)
        bundle = staging / "catalog-bundle.zip"
        extracted_catalog = staging / catalog.name
        extracted_manifest = staging / manifest.name
        expected_bundle_sha256 = _read_text(
            selected_checksum_url, timeout_seconds
        ).split()[0].lower()
        if len(expected_bundle_sha256) != 64:
            raise RuntimeError("Catalog bundle checksum file is invalid")
        _download(selected_bundle_url, bundle, timeout_seconds)
        if sha256_file(bundle) != expected_bundle_sha256:
            raise RuntimeError("Catalog bundle SHA-256 verification failed")

        with zipfile.ZipFile(bundle) as archive:
            catalog_member = _archive_member(archive, CATALOG_ARCHIVE_SUFFIX)
            manifest_member = _archive_member(
                archive, CATALOG_MANIFEST_ARCHIVE_SUFFIX
            )
            with (
                archive.open(catalog_member) as source,
                extracted_catalog.open("wb") as output,
            ):
                shutil.copyfileobj(source, output, length=1024 * 1024)
            with (
                archive.open(manifest_member) as source,
                extracted_manifest.open("wb") as output,
            ):
                shutil.copyfileobj(source, output, length=1024 * 1024)

        _validate_catalog(extracted_catalog, extracted_manifest)
        extracted_catalog.replace(catalog)
        extracted_manifest.replace(manifest)
    return catalog
