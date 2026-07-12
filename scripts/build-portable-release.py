from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import tarfile
import tomllib
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "portable-release"
EXECUTABLE_SUFFIXES = {".sh", ".command"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
            ".ruff_cache",
        ),
    )


def validate_catalog(catalog: Path, manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_bytes = catalog.stat().st_size
    actual_sha256 = sha256_file(catalog)
    if actual_bytes != manifest["file_bytes"]:
        raise RuntimeError(
            f"Catalog byte count mismatch: {actual_bytes} != {manifest['file_bytes']}"
        )
    if actual_sha256 != manifest["database_sha256"]:
        raise RuntimeError("Catalog SHA-256 does not match its release manifest")
    return manifest


def write_portable_manifest(
    package_root: Path,
    version: str,
    catalog_manifest: dict[str, object],
    *,
    includes_local_agent_config: bool,
) -> None:
    files = []
    for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        files.append(
            {
                "path": path.relative_to(package_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    excluded_private_files = [
        "var/workspace.sqlite",
        ".runtime/",
        ".venv/",
    ]
    if not includes_local_agent_config:
        excluded_private_files.insert(0, "var/config/agent.env")
    payload = {
        "package": "thermal-expansion-platform-portable",
        "version": version,
        "platforms": ["Windows", "macOS", "Linux"],
        "contains_private_agent_config": includes_local_agent_config,
        "catalog": catalog_manifest,
        "excluded_private_files": excluded_private_files,
        "files": files,
    }
    (package_root / "PORTABLE-MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add_zip_file(
    archive: zipfile.ZipFile,
    source: Path,
    archive_name: str,
) -> None:
    mode = 0o755 if source.suffix in EXECUTABLE_SUFFIXES else 0o644
    info = zipfile.ZipInfo.from_file(source, arcname=archive_name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    with source.open("rb") as input_stream, archive.open(info, "w") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


def build_zip(package_root: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compresslevel=6) as archive:
        for source in sorted(item for item in package_root.rglob("*") if item.is_file()):
            relative = source.relative_to(package_root.parent).as_posix()
            add_zip_file(archive, source, relative)


def build_tar_gz(package_root: Path, output: Path) -> None:
    def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        if info.isfile():
            suffix = Path(info.name).suffix
            info.mode = 0o755 if suffix in EXECUTABLE_SUFFIXES else 0o644
        elif info.isdir():
            info.mode = 0o755
        return info

    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        archive.add(package_root, arcname=package_root.name, filter=normalize)


def build(*, include_local_agent_config: bool = False) -> dict[str, object]:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    private_suffix = "-collaborator-private" if include_local_agent_config else ""
    package_name = f"thermal-expansion-platform-v{version}-portable{private_suffix}"
    package_root = OUTPUT_ROOT / package_name

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir()

    for directory in ["src", "environments", "scripts"]:
        copy_tree(PROJECT_ROOT / directory, package_root / directory)

    root_files = [
        "pyproject.toml",
        "uv.lock",
        "README-PORTABLE.md",
        "CHANGELOG.md",
        "NOTICE-THIRD-PARTY.md",
        "start-windows.cmd",
        "start-windows.ps1",
        "start-macos.command",
        "start-linux.sh",
    ]
    for filename in root_files:
        shutil.copy2(PROJECT_ROOT / filename, package_root / filename)
    shutil.copy2(PROJECT_ROOT / "README-PORTABLE.md", package_root / "README.md")

    source_catalog = PROJECT_ROOT / "var" / "releases" / "catalog-v1.sqlite"
    source_catalog_manifest = source_catalog.with_suffix(".sqlite.manifest.json")
    catalog_manifest = validate_catalog(source_catalog, source_catalog_manifest)
    release_directory = package_root / "var" / "releases"
    release_directory.mkdir(parents=True)
    shutil.copy2(source_catalog, release_directory / source_catalog.name)
    shutil.copy2(
        source_catalog_manifest,
        release_directory / source_catalog_manifest.name,
    )

    for directory in ["config", "uploads", "runs"]:
        (package_root / "var" / directory).mkdir(parents=True, exist_ok=True)
    (package_root / "var" / "config" / "agent.env.example").write_text(
        "TEP_AGENT_BASE_URL=https://api.cmsg666.xyz/v1\n"
        "TEP_AGENT_MODEL=gpt-5.6-luna\n"
        "TEP_AGENT_API_KEY=\n"
        "TEP_AGENT_TIMEOUT_SECONDS=120\n",
        encoding="utf-8",
    )
    (package_root / "var" / "config" / "compute.env.example").write_text(
        "# Optional heavy-compute configuration. Leave blank for catalog-only use.\n"
        "TEP_ALIGNN_PYTHON=\n"
        "TEP_ALIGNN_SOURCE=\n"
        "TEP_ALIGNN_MODEL_DIR=\n"
        "TEP_MATTERSIM_PYTHON=\n"
        "TEP_MATTERSIM_MODEL=mattersim-v1.0.0-5M\n"
        "TEP_PRECISION_SOURCE_ROOT=\n"
        "TEP_WSL_DISTRO=Ubuntu-24.04\n"
        "TEP_PRECISION_CONDA_INIT=\n"
        "TEP_PRECISION_CONDA_ENV=mattersim\n"
        "TEP_VASPKIT_BIN_DIR=\n",
        encoding="utf-8",
    )
    if include_local_agent_config:
        local_agent_config = PROJECT_ROOT / "var" / "config" / "agent.env"
        if not local_agent_config.is_file():
            raise RuntimeError(
                "--include-local-agent-config was requested, but var/config/agent.env is missing"
            )
        shutil.copy2(
            local_agent_config,
            package_root / "var" / "config" / "agent.env",
        )
        (package_root / "PRIVATE-COLLABORATOR-BUILD.txt").write_text(
            "This collaborator build contains a private Agent API configuration.\n"
            "Do not upload this archive to Git, a public cloud drive, or a public repository.\n"
            "Create a normal build without --include-local-agent-config before public release.\n",
            encoding="utf-8",
        )

    write_portable_manifest(
        package_root,
        version,
        catalog_manifest,
        includes_local_agent_config=include_local_agent_config,
    )

    zip_path = OUTPUT_ROOT / f"{package_name}.zip"
    tar_path = OUTPUT_ROOT / f"{package_name}.tar.gz"
    for archive in [zip_path, tar_path]:
        archive.unlink(missing_ok=True)
    build_zip(package_root, zip_path)
    build_tar_gz(package_root, tar_path)
    for archive in [zip_path, tar_path]:
        archive.with_name(archive.name + ".sha256").write_text(
            f"{sha256_file(archive)}  {archive.name}\n",
            encoding="ascii",
        )

    return {
        "version": version,
        "package_directory": str(package_root),
        "zip": {
            "path": str(zip_path),
            "bytes": zip_path.stat().st_size,
            "sha256": sha256_file(zip_path),
        },
        "tar_gz": {
            "path": str(tar_path),
            "bytes": tar_path.stat().st_size,
            "sha256": sha256_file(tar_path),
        },
        "catalog_materials": catalog_manifest["counts"]["materials"],
        "contains_private_agent_config": include_local_agent_config,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-local-agent-config",
        action="store_true",
        help="Create a clearly marked private collaborator build containing var/config/agent.env.",
    )
    arguments = parser.parse_args()
    print(
        json.dumps(
            build(include_local_agent_config=arguments.include_local_agent_config),
            ensure_ascii=False,
            indent=2,
        )
    )
