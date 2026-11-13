from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import tempfile
import zipfile
from typing import Any, Mapping
import zlib

from ..models import InspectionRun
from ..reporting import to_jsonable, write_run_artifacts


class BundleError(ValueError):
    pass


REQUIRED_RESULT_ARTIFACTS = frozenset({
    "inspection_run.json", "inspection_report.md", "work_orders.json",
})
REQUIRED_ARTIFACT_MAX_BYTES = {
    "inspection_run.json": 16 * 1024 * 1024,
    "work_orders.json": 8 * 1024 * 1024,
    "inspection_report.md": 2 * 1024 * 1024,
}
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_MAX_BYTES = 2 * 1024 * 1024
_MAX_ARTIFACTS = 1024
_CHUNK_SIZE = 1024 * 1024


def _validate_artifact_name(name: Any) -> str:
    if (not isinstance(name, str) or not _ARTIFACT_NAME.fullmatch(name)
            or name in {".", "..", "result_manifest.json"}):
        raise BundleError("Bundle contains an invalid artifact name.")
    return name


def _add_file(archive: zipfile.ZipFile, name: str, path: Path,
              remaining_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    limit = min(remaining_bytes, REQUIRED_ARTIFACT_MAX_BYTES.get(name, remaining_bytes))
    with path.open("rb") as source, archive.open(name, "w") as target:
        while chunk := source.read(_CHUNK_SIZE):
            size += len(chunk)
            if size > limit:
                if name in REQUIRED_ARTIFACT_MAX_BYTES:
                    raise BundleError(
                        f"Required metadata artifact {name} exceeds its size limit.")
                raise BundleError("Bundle expands beyond the configured size limit.")
            digest.update(chunk)
            target.write(chunk)
    return digest.hexdigest(), size


def build_result_bundle(
    output_dir: Path,
    run: InspectionRun,
    config_sha256: str,
    software_version: str = "0.2.0",
    additional_artifacts: Mapping[str, Path] | None = None,
    max_uncompressed_bytes: int = 200 * 1024 * 1024,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = output_dir / "generated"
    write_run_artifacts(run, generated)
    work_orders = [
        to_jsonable(item.work_order)
        for item in run.results if item.work_order is not None
    ]
    work_orders_path = generated / "work_orders.json"
    work_orders_path.write_text(
        json.dumps(work_orders, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files: dict[str, Path] = {
        "inspection_run.json": generated / "inspection_run.json",
        "inspection_report.md": generated / "inspection_report.md",
        "work_orders.json": work_orders_path,
    }
    for raw_name, raw_path in (additional_artifacts or {}).items():
        name = _validate_artifact_name(raw_name)
        path = Path(raw_path)
        if name in files:
            raise BundleError(f"Duplicate result artifact: {name}.")
        if path.is_symlink() or not path.is_file():
            raise BundleError(f"Result artifact is not a regular file: {name}.")
        files[name] = path
    if len(files) > _MAX_ARTIFACTS:
        raise BundleError("Bundle contains too many artifacts.")

    manifest_artifacts = []
    total_size = 0
    archive_path = output_dir / "result_bundle.zip"
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in sorted(files.items()):
                digest, size = _add_file(
                    archive, name, path, max_uncompressed_bytes - total_size)
                total_size += size
                manifest_artifacts.append({
                    "name": name,
                    "sha256": digest,
                    "size_bytes": size,
                })
            manifest = {
                "schema_version": 1,
                "run_id": run.run_id,
                "source": run.source,
                "software_version": software_version,
                "config_sha256": config_sha256,
                "artifacts": manifest_artifacts,
            }
            manifest_bytes = (json.dumps(
                manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
            if total_size + len(manifest_bytes) > max_uncompressed_bytes:
                raise BundleError("Bundle expands beyond the configured size limit.")
            if len(manifest_bytes) > _MANIFEST_MAX_BYTES:
                raise BundleError("Result manifest exceeds its size limit.")
            archive.writestr("result_manifest.json", manifest_bytes)
    except (OSError, zipfile.BadZipFile) as exc:
        archive_path.unlink(missing_ok=True)
        raise BundleError(f"Could not build result bundle ({type(exc).__name__}).") from exc
    except BundleError:
        archive_path.unlink(missing_ok=True)
        raise
    return archive_path


def extract_result_bundle(
    path: Path,
    output_dir: Path,
    max_uncompressed_bytes: int = 200 * 1024 * 1024,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    created_paths: list[Path] = []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > _MAX_ARTIFACTS + 1:
                raise BundleError("Bundle contains an invalid number of files.")
            by_name: dict[str, zipfile.ZipInfo] = {}
            for info in infos:
                name = info.filename
                if (name != "result_manifest.json"):
                    _validate_artifact_name(name)
                if (info.is_dir() or info.flag_bits & 0x1
                        or stat.S_ISLNK(info.external_attr >> 16)):
                    raise BundleError("Bundle contains a directory, encrypted file, or link.")
                if name in by_name:
                    raise BundleError(f"Bundle contains a duplicate file: {name}.")
                by_name[name] = info
            manifest_info = by_name.get("result_manifest.json")
            if manifest_info is None:
                raise BundleError("Bundle is missing result_manifest.json.")
            if manifest_info.file_size > _MANIFEST_MAX_BYTES:
                raise BundleError("Result manifest exceeds its size limit.")
            declared_total = sum(info.file_size for info in infos)
            if declared_total > max_uncompressed_bytes:
                raise BundleError("Bundle expands beyond the configured size limit.")

            with archive.open(manifest_info) as source:
                manifest_bytes = source.read(_MANIFEST_MAX_BYTES + 1)
            if (len(manifest_bytes) > _MANIFEST_MAX_BYTES
                    or len(manifest_bytes) != manifest_info.file_size):
                raise BundleError("Result manifest has an invalid size.")
            try:
                manifest = json.loads(manifest_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BundleError("Bundle contains an invalid result manifest.") from exc
            if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
                raise BundleError("Result manifest has an invalid artifact list.")
            descriptors: dict[str, dict[str, Any]] = {}
            for item in manifest["artifacts"]:
                if not isinstance(item, dict) or set(item) != {"name", "sha256", "size_bytes"}:
                    raise BundleError("Result manifest contains an invalid artifact descriptor.")
                name = _validate_artifact_name(item["name"])
                digest = item["sha256"]
                size = item["size_bytes"]
                if name in descriptors:
                    raise BundleError(f"Result manifest repeats artifact {name}.")
                if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                    raise BundleError(f"Artifact {name} has an invalid SHA-256 value.")
                if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                    raise BundleError(f"Artifact {name} has an invalid size.")
                limit = REQUIRED_ARTIFACT_MAX_BYTES.get(name)
                if limit is not None and size > limit:
                    raise BundleError(f"Required metadata artifact {name} exceeds its size limit.")
                descriptors[name] = item
            if len(descriptors) > _MAX_ARTIFACTS:
                raise BundleError("Bundle contains too many artifacts.")
            if not REQUIRED_RESULT_ARTIFACTS.issubset(descriptors):
                raise BundleError("Bundle is missing required result artifacts.")
            if set(by_name) != {"result_manifest.json", *descriptors}:
                raise BundleError("Bundle files do not match the result manifest.")
            for name, descriptor in descriptors.items():
                if by_name[name].file_size != descriptor["size_bytes"]:
                    raise BundleError(f"Artifact size mismatch for {name}.")

            output_dir.mkdir(parents=True, exist_ok=True)
            artifact_paths: dict[str, Path] = {}
            for name, descriptor in descriptors.items():
                destination = output_dir / name
                digest = hashlib.sha256()
                size = 0
                with archive.open(by_name[name]) as source, destination.open("xb") as target:
                    created_paths.append(destination)
                    while chunk := source.read(_CHUNK_SIZE):
                        size += len(chunk)
                        if size > descriptor["size_bytes"]:
                            raise BundleError(f"Artifact size mismatch for {name}.")
                        digest.update(chunk)
                        target.write(chunk)
                if size != descriptor["size_bytes"] or digest.hexdigest() != descriptor["sha256"]:
                    raise BundleError(f"Artifact checksum mismatch for {name}.")
                artifact_paths[name] = destination

        try:
            inspection_run = json.loads(
                artifact_paths["inspection_run.json"].read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BundleError("Bundle contains invalid inspection_run.json.") from exc
        return manifest, inspection_run, artifact_paths
    except BundleError:
        for created in created_paths:
            created.unlink(missing_ok=True)
        raise
    except OSError:
        for created in created_paths:
            created.unlink(missing_ok=True)
        raise
    except (RuntimeError, EOFError, zipfile.BadZipFile, zlib.error) as exc:
        for created in created_paths:
            created.unlink(missing_ok=True)
        raise BundleError(f"Could not read result bundle ({type(exc).__name__}).") from exc


def read_result_bundle(
    path: Path,
    max_uncompressed_bytes: int = 200 * 1024 * 1024,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    with tempfile.TemporaryDirectory(prefix="inspection-bundle-") as temp_dir:
        manifest, inspection_run, artifact_paths = extract_result_bundle(
            path, Path(temp_dir), max_uncompressed_bytes)
        artifacts = {name: artifact_path.read_bytes()
                     for name, artifact_path in artifact_paths.items()}
    return manifest, inspection_run, artifacts
