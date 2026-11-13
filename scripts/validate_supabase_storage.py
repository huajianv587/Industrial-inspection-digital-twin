from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from inspection_system.platform.settings import Settings


EXPECTED_POLICIES = {
    "inspection_artifacts_service_select": "SELECT",
    "inspection_artifacts_service_insert": "INSERT",
    "inspection_artifacts_service_update": "UPDATE",
}
EXPECTED_LIMIT = 200 * 1024 * 1024
STORAGE_MIGRATION_REVISION = "20261020_0004"


def migration_is_applied(current_revision: str | None) -> bool:
    if not current_revision:
        return False

    migrations_path = Path(__file__).resolve().parents[1] / "migrations"
    scripts = ScriptDirectory(str(migrations_path))
    pending = [current_revision]
    visited: set[str] = set()
    while pending:
        revision_id = pending.pop()
        if revision_id in visited:
            continue
        visited.add(revision_id)
        if revision_id == STORAGE_MIGRATION_REVISION:
            return True
        revision = scripts.get_revision(revision_id)
        if revision is None:
            return False
        parents = revision.down_revision
        if isinstance(parents, str):
            pending.append(parents)
        elif parents:
            pending.extend(parents)
    return False


def verify() -> dict[str, object]:
    supabase_url = os.getenv("SUPABASE_URL", "")
    settings = Settings(
        database_url=os.getenv("SUPABASE_DB_URL", ""),
        environment=os.getenv("APP_ENV", "production").lower(),
        supabase_url=supabase_url,
    )
    settings.validate_database()
    settings.validate_supabase_project_binding(required=True)
    project_host = urlparse(supabase_url).hostname or ""
    project_ref = project_host.removesuffix(".supabase.co")
    if not project_ref or project_host != f"{project_ref}.supabase.co":
        raise RuntimeError("SUPABASE_URL does not identify a standard project ref.")

    engine = create_engine(settings.sqlalchemy_database_url(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text(
                "SELECT version_num FROM alembic_version"))
            bucket = connection.execute(text("""
                SELECT id, public, file_size_limit, allowed_mime_types
                FROM storage.buckets
                WHERE id = 'inspection-artifacts'
            """)).mappings().one_or_none()
            policies = connection.execute(text("""
                SELECT policyname, cmd, roles, qual, with_check
                FROM pg_policies
                WHERE schemaname = 'storage'
                  AND tablename = 'objects'
                  AND policyname LIKE 'inspection_artifacts_service_%'
            """)).mappings().all()
    finally:
        engine.dispose()

    if not migration_is_applied(revision):
        raise RuntimeError(
            f"Expected migration {STORAGE_MIGRATION_REVISION} in the current schema history; "
            f"found {revision!r}.")
    if (bucket is None or bucket["public"] is not False
            or bucket["file_size_limit"] != EXPECTED_LIMIT
            or "application/octet-stream" not in (bucket["allowed_mime_types"] or [])):
        raise RuntimeError("The artifact bucket configuration does not match policy.")

    found = {item["policyname"]: item for item in policies}
    if set(found) != set(EXPECTED_POLICIES):
        raise RuntimeError("The expected artifact storage policies are incomplete or duplicated.")
    for name, command in EXPECTED_POLICIES.items():
        policy = found[name]
        if policy["cmd"] != command or set(policy["roles"]) != {"authenticated"}:
            raise RuntimeError(f"Storage policy {name} has unexpected command or roles.")
        clauses = [policy["qual"], policy["with_check"]]
        required_scope = ("bucket_id", "inspection-artifacts", "inspection_storage", "service")
        applicable_clauses = [clause.lower() for clause in clauses if clause]
        if not applicable_clauses or any(
                not all(token in clause for token in required_scope)
                for clause in applicable_clauses):
            raise RuntimeError(f"Storage policy {name} has an unexpected scope.")

    return {
        "project_ref": project_ref,
        "migration": revision,
        "bucket": bucket["id"],
        "private": not bucket["public"],
        "file_size_limit": bucket["file_size_limit"],
        "policies": sorted(found),
        "policy_scope": "verified",
    }


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), sort_keys=True))
    except Exception as exc:
        print(f"Supabase Storage validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
