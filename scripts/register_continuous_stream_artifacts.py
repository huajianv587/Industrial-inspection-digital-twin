#!/usr/bin/env python3
"""Register generated continuous video streams in an existing local demo run."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from inspection_system.platform.artifact_storage import LocalArtifactStorage
from inspection_system.platform.artifact_store import store_artifact_file
from inspection_system.platform.db import create_database
from inspection_system.platform.entities import ArtifactRecord


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene_dir", type=Path)
    parser.add_argument("demo_dir", type=Path)
    parser.add_argument("run_id")
    args = parser.parse_args()

    scene_dir = args.scene_dir.resolve()
    demo_dir = args.demo_dir.resolve()
    db_path = demo_dir / "inspection.db"
    artifact_dir = demo_dir / "artifacts"
    files = [
        scene_dir / "continuous_video_manifest.json",
        scene_dir / "robot_head_stream.mp4",
        scene_dir / "warehouse_cctv_stream.mp4",
    ]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise SystemExit(f"missing continuous stream artifacts: {missing}")

    engine, session_factory = create_database(
        f"sqlite:///{db_path}", environment="local_demo",
    )
    storage = LocalArtifactStorage(artifact_dir, max_bytes=200 * 1024 * 1024)
    storage.initialize()
    try:
        with session_factory() as session:
            for path in files:
                digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
                existing = session.scalar(select(ArtifactRecord).where(
                    ArtifactRecord.run_id == args.run_id,
                    ArtifactRecord.name == path.name,
                ))
                if existing:
                    if existing.sha256 != digest or existing.size_bytes != path.stat().st_size:
                        raise RuntimeError(f"immutable artifact conflict: {path.name}")
                    print(f"EXISTS {path.name}")
                    continue
                with path.open("rb") as stream:
                    record = store_artifact_file(
                        session,
                        storage,
                        args.run_id,
                        path.name,
                        stream,
                        digest,
                        path.stat().st_size,
                        "synthetic_simulation",
                    )
                print(f"REGISTERED {record.name} {record.size_bytes} bytes")
            session.commit()
    finally:
        engine.dispose()
    print("CONTINUOUS_ARTIFACT_REGISTRATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
