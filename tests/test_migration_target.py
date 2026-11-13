from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


class MigrationTargetTests(unittest.TestCase):
    def test_alembic_rejects_owner_url_for_a_different_project_before_connecting(self):
        root = Path(__file__).parents[1]
        environment = {
            "APP_ENV": "production",
            "PYTHONPATH": str(root / "src"),
            "PATH": os.environ.get("PATH", ""),
            "SUPABASE_DB_URL": (
                "postgresql://postgres:test-only@db.other-ref.supabase.co/postgres"
            ),
            "SUPABASE_URL": "https://project-ref.supabase.co",
        }
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must target the project identified by SUPABASE_URL", output)
        self.assertNotIn("test-only", output)

    def test_storage_metadata_validator_rejects_wrong_project_before_connecting(self):
        root = Path(__file__).parents[1]
        environment = {
            "APP_ENV": "production",
            "PYTHONPATH": str(root / "src"),
            "PATH": os.environ.get("PATH", ""),
            "SUPABASE_DB_URL": (
                "postgresql://postgres:test-only@db.other-ref.supabase.co/postgres"
            ),
            "SUPABASE_URL": "https://project-ref.supabase.co",
        }
        completed = subprocess.run(
            [sys.executable, "scripts/validate_supabase_storage.py"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must target the project identified by SUPABASE_URL", output)
        self.assertNotIn("test-only", output)


if __name__ == "__main__":
    unittest.main()
