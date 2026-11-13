#!/usr/bin/env python3
"""Validate the v35 product demo using the established v34 contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("LOCAL_DEMO_RUN_ID", "RUN-V35-PREMIUM-INDUSTRIAL-REALISM")
os.environ.setdefault("LOCAL_DEMO_DIR", str(ROOT / "outputs/local-demo-v35-final"))
os.environ.setdefault("LOCAL_DEMO_PREBUILT_SCENE_DIR", str(ROOT / "outputs/industrial-v35-premium-1280"))
os.environ.setdefault("LOCAL_DEMO_HEALTH_URL", "http://127.0.0.1:8015/healthz")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_local_demo_v34 as baseline  # noqa: E402


def main() -> int:
    scene_dir = Path(os.environ["LOCAL_DEMO_PREBUILT_SCENE_DIR"])
    manifest = json.loads((scene_dir / "factory_camera_manifest.json").read_text(encoding="utf-8"))
    detail_level = manifest.get("scene_detail_level", "")
    if not detail_level.startswith("factory_environment_v35_"):
        raise RuntimeError(f"unexpected scene detail level: {detail_level}")
    result = baseline.main()
    print("V35_PREMIUM_SCENE_VALIDATION=PASS")
    print(f"scene_detail_level={detail_level}")
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V35_PREMIUM_SCENE_VALIDATION=FAIL: {exc}") from exc
