#!/usr/bin/env python3
"""Encode Blender-rendered inspection frames as continuous browser video streams.

The source PNGs remain the auditable frame evidence. This command adds an
audio-free H.264 stream for smooth playback in Chrome and records the exact
frame-time mapping in ``continuous_video_manifest.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


STREAMS = {
    "robot": ("robot_head_stream.mp4", "robot_rgb_stream__F%04d.png"),
    "cctv": ("warehouse_cctv_stream.mp4", "warehouse_cctv_stream__F%04d.png"),
}


def _run(command: list[str]) -> None:
    print("$", " ".join(command))
    subprocess.run(command, check=True)


def _probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_frames",
            "-show_entries", "format=duration", "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    stream = (payload.get("streams") or [{}])[0]
    return {
        "codec": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "fps": stream.get("avg_frame_rate"),
        "frame_count": stream.get("nb_frames"),
        "duration_s": float((payload.get("format") or {}).get("duration") or 0),
    }


def _encode(scene_dir: Path, output: Path, source_fps: float) -> None:
    output.unlink(missing_ok=True)
    # ``minterpolate`` turns the sparse, route-indexed Blender captures into a
    # 30 FPS media timeline. It keeps the original capture order and avoids the
    # hard visual cuts caused by replacing PNGs from a JavaScript timer.
    video_filter = (
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
        "format=yuv420p"
    )
    encoder = "h264_videotoolbox"
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to encode the continuous streams")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-framerate", f"{source_fps:.8f}", "-start_number", "1",
        "-i", str(scene_dir / "{pattern}"),
        "-vf", video_filter,
        "-an", "-c:v", encoder, "-b:v", "3M", "-maxrate", "4M",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ]
    # The input pattern is substituted by the caller. Hardware encoding is
    # preferred on macOS; libx264 is a deterministic fallback elsewhere.
    try:
        _run(command)
    except subprocess.CalledProcessError:
        command[command.index("-c:v") + 1] = "libx264"
        command[command.index("-b:v") + 1] = "2500k"
        command[command.index("-maxrate") + 1] = "3500k"
        _run(command)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene_dir", type=Path)
    parser.add_argument("--output-width", type=int, default=0,
                        help="Optional presentation width; source evidence stays unchanged.")
    parser.add_argument("--output-fps", type=int, default=60,
                        help="Encoded playback FPS. 60 preserves smooth motion at 0.5x.")
    parser.add_argument("--video-bitrate", default="3M",
                        help="Target video bitrate passed to the hardware encoder.")
    args = parser.parse_args()
    scene_dir = args.scene_dir.resolve()
    manifest_path = scene_dir / "synchronized_video_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing synchronized manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frame_duration = float(manifest.get("frame_duration_s") or 0.36)
    if frame_duration <= 0:
        raise SystemExit("frame_duration_s must be positive")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or len(frames) < 2:
        raise SystemExit("synchronized manifest must contain at least two frames")

    source_fps = 1.0 / frame_duration
    output_fps = max(24, int(args.output_fps))
    output_width = max(0, int(args.output_width))
    if output_width and output_width % 2:
        raise SystemExit("--output-width must be even")
    video_streams: dict[str, dict[str, object]] = {}
    for kind, (filename, pattern) in STREAMS.items():
        first_frame = scene_dir / pattern.replace("%04d", "0001")
        if not first_frame.is_file():
            raise SystemExit(f"missing Blender render frame: {first_frame}")
        output = scene_dir / filename
        command_pattern = str(scene_dir / pattern)
        # Keep the command construction in one place while passing the actual
        # ffmpeg input pattern to the encoder.
        output.unlink(missing_ok=True)
        scale_filter = (
            f"scale={output_width}:-2:flags=lanczos" if output_width
            else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        )
        video_filter = (
            f"{scale_filter},"
            f"minterpolate=fps={output_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
            "format=yuv420p"
        )
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-framerate", f"{source_fps:.8f}", "-start_number", "1",
            "-i", command_pattern, "-vf", video_filter, "-an",
            "-c:v", "h264_videotoolbox", "-b:v", args.video_bitrate,
            "-maxrate", args.video_bitrate,
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
        ]
        try:
            _run(command)
        except subprocess.CalledProcessError:
            command[command.index("-c:v") + 1] = "libx264"
            command[command.index("-b:v") + 1] = args.video_bitrate
            command[command.index("-maxrate") + 1] = args.video_bitrate
            _run(command)
        probe = _probe(output)
        video_streams[kind] = {
            "artifact": filename,
            "media_type": "video/mp4",
            "source": "Blender_EEVEE_rendered_frames",
            "codec": probe["codec"],
            "fps": output_fps,
            "duration_s": round(float(probe["duration_s"]), 3),
            "width": probe["width"],
            "height": probe["height"],
            "frame_count": probe["frame_count"],
            "source_frame_count": len(frames),
            "source_frame_duration_s": frame_duration,
            "presentation_upscaled": bool(output_width),
        }

    continuous_manifest = {
        "schema_version": 1,
        "stream_type": "blender_rendered_continuous_video",
        "engine": "Blender EEVEE",
        "timeline": "synchronized_route_time",
        "frame_count": len(frames),
        "route_frame_count": manifest.get("route_frame_count", len(frames)),
        "frame_duration_s": frame_duration,
        "recommended_playback_speed": manifest.get("recommended_playback_speed", 0.5),
        "resolution": manifest.get("resolution"),
        "presentation_resolution": {
            "width": video_streams["robot"]["width"],
            "height": video_streams["robot"]["height"],
        },
        "presentation_fps": output_fps,
        "presentation_profile": "HQ_BROWSER_STREAM" if output_width else "STANDARD_BROWSER_STREAM",
        "video_streams": video_streams,
        "frames": frames,
        "limitations": [
            "Video is encoded from local Blender render frames; it is not a live sensor transport.",
            "The interpolation step creates a smooth presentation timeline and does not add new field measurements.",
            "The PNG frames remain the authoritative visual evidence artifacts.",
        ],
    }
    (scene_dir / "continuous_video_manifest.json").write_text(
        json.dumps(continuous_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Keep the original manifest backward-compatible while advertising the
    # preferred continuous stream to older consumers that only read this file.
    manifest["stream_type"] = "blender_rendered_frame_and_video_stream"
    manifest["continuous_manifest"] = "continuous_video_manifest.json"
    manifest["video_streams"] = video_streams
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"CONTINUOUS_STREAMS=PASS scene={scene_dir}")
    for kind, stream in video_streams.items():
        print(f"{kind}: {stream['artifact']} {stream['duration_s']}s @ {stream['fps']}fps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
