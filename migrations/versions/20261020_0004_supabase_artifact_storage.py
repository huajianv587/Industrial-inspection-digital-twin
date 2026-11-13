"""Provision a private Supabase Storage bucket and scoped service policies."""
from __future__ import annotations

from alembic import op


revision = "20261020_0004"
down_revision = "20261020_0003"
branch_labels = None
depends_on = None


_POLICIES = (
    ("inspection_artifacts_service_select", "SELECT",
     "USING (bucket_id = 'inspection-artifacts' AND "
     "(auth.jwt() -> 'app_metadata' ->> 'inspection_storage') = 'service')"),
    ("inspection_artifacts_service_insert", "INSERT",
     "WITH CHECK (bucket_id = 'inspection-artifacts' AND "
     "(auth.jwt() -> 'app_metadata' ->> 'inspection_storage') = 'service')"),
    ("inspection_artifacts_service_update", "UPDATE",
     "USING (bucket_id = 'inspection-artifacts' AND "
     "(auth.jwt() -> 'app_metadata' ->> 'inspection_storage') = 'service') "
     "WITH CHECK (bucket_id = 'inspection-artifacts' AND "
     "(auth.jwt() -> 'app_metadata' ->> 'inspection_storage') = 'service')"),
)


def upgrade() -> None:
    op.execute("""
        INSERT INTO storage.buckets
            (id, name, public, file_size_limit, allowed_mime_types)
        VALUES
            ('inspection-artifacts', 'inspection-artifacts', false,
             209715200, ARRAY['application/octet-stream']::text[])
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        DO $bucket_check$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM storage.buckets
                WHERE id = 'inspection-artifacts'
                  AND public = false
                  AND (file_size_limit IS NULL OR file_size_limit >= 209715200)
                  AND (allowed_mime_types IS NULL OR
                       'application/octet-stream' = ANY(allowed_mime_types))
            ) THEN
                RAISE EXCEPTION
                    'inspection-artifacts must be private and allow 200 MiB octet-stream objects';
            END IF;
        END
        $bucket_check$
    """)
    for name, command, clause in _POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {name} ON storage.objects")
        op.execute(f"""
            CREATE POLICY {name} ON storage.objects
            FOR {command} TO authenticated {clause}
        """)


def downgrade() -> None:
    for name, _command, _clause in _POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {name} ON storage.objects")
    # Keep the bucket and its objects: rollback must not delete user artifacts.
