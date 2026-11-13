"""Vercel serverless entrypoint for the FastAPI backend.

The application package lives in ``src/`` (src-layout), so add it to
``sys.path`` for the import below. The app itself is the factory
``inspection_system.platform.api:create_app`` used by the Docker image
(``uvicorn inspection_system.platform.api:create_app --factory``).

Runtime note: on Vercel the app must run in ``local_demo`` mode
(APP_ENV=local_demo, INSPECTION_EXECUTOR=offline,
SLURM_RESULT_SOURCE=synthetic_simulation,
INSPECTION_AUTH_MODE=development, ARTIFACT_STORAGE_BACKEND=local,
LOCAL_DATABASE_URL=sqlite:////tmp/inspection.db,
ARTIFACT_DIR=/tmp/artifacts). Production mode requires Slurm +
Isaac Sim + Supabase PostgreSQL, which a serverless deployment
cannot provide.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from inspection_system.platform.api import create_app

app = create_app()
