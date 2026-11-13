from __future__ import annotations

import hashlib
import json
import sys

from inspection_system.platform.artifact_storage import (
    ArtifactStorageError,
    SupabaseS3ArtifactStorage,
)
from inspection_system.platform.settings import Settings


SMOKE_RUN_ID = "storage-smoke-v1"
SMOKE_CONTENT = b"inspection-storage-smoke-v1\n"


def run_smoke() -> dict[str, str]:
    settings = Settings.from_env()
    settings.validate_database()
    settings.validate_supabase_project_binding(required=True)
    settings.validate_artifact_storage()

    storage = SupabaseS3ArtifactStorage(settings)
    storage.initialize()
    digest = hashlib.sha256(SMOKE_CONTENT).hexdigest()
    reference = storage.put_bytes(SMOKE_RUN_ID, digest, SMOKE_CONTENT)
    repeated_reference = storage.put_bytes(SMOKE_RUN_ID, digest, SMOKE_CONTENT)
    if repeated_reference != reference:
        raise ArtifactStorageError("Repeated smoke upload returned a different object reference.")
    if storage.read_bytes(reference) != SMOKE_CONTENT:
        raise ArtifactStorageError("Storage smoke download did not match the uploaded content.")
    if not storage.verify_artifact(reference, SMOKE_RUN_ID, digest, len(SMOKE_CONTENT)):
        raise ArtifactStorageError("Storage smoke object failed its SHA-256 verification.")

    return {
        "storage_smoke": "passed",
        "bucket": settings.storage_bucket,
        "marker_run_id": SMOKE_RUN_ID,
        "sha256": digest,
        "idempotent_reuse": "verified",
    }


def main() -> int:
    try:
        print(json.dumps(run_smoke(), sort_keys=True))
    except (ArtifactStorageError, ValueError, OSError) as exc:
        print(f"Supabase Storage smoke failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
