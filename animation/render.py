"""
render.py — Orchestrates the DesiMapper Blender animation render.

Defaults: 7680×4320 (8K UHD) @ 60fps on macOS with Metal GPU acceleration.
The M-series / AMD GPU in the MacBook is used via Cycles Metal backend.

Usage (headless):
    blender --background --python animation/render.py -- \
        --parquet data/processed/all_galaxies.parquet \
        --output renders/frames/

    # Test at 1080p first (much faster):
    blender --background --python animation/render.py -- \
        --resolution 1920x1080 --samples 32 --max-points 200000

    # Full 8K production render:
    blender --background --python animation/render.py -- \
        --resolution 7680x4320 --samples 128 --max-points 2000000

The -- separates Blender args from script args.

Storage estimate:
    8K PNG frame = ~50 MB → 13,500 frames (7.5 min @ 60fps) = ~675 GB
    Ensure renders/ has sufficient space or use --start-frame/--end-frame
    to render in batches.
"""

import sys
import argparse
from pathlib import Path


# ─── Parse script arguments (after --) ──────────────────────────────────────

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="DesiMapper Blender renderer")
    parser.add_argument(
        "--parquet",
        default="data/processed/all_galaxies.parquet",
        help="Path to combined galaxy Parquet file",
    )
    parser.add_argument(
        "--output",
        default="renders/frames/",
        help="Output directory for PNG frames",
    )
    parser.add_argument(
        "--samples", type=int, default=128,
        help="Cycles render samples per frame (default: 128 for 8K)",
    )
    parser.add_argument(
        "--resolution", default="7680x4320",
        help="Output resolution WxH (default: 7680x4320 = 8K UHD)",
    )
    parser.add_argument(
        "--fps", type=int, default=60,
        help="Frames per second (default: 60)",
    )
    parser.add_argument(
        "--start-frame", type=int, default=1,
        help="First frame to render",
    )
    parser.add_argument(
        "--end-frame", type=int, default=None,
        help="Last frame to render (default: all)",
    )
    parser.add_argument(
        "--max-points", type=int, default=2_000_000,
        help="Max galaxy points in scene (default: 2M for 8K detail)",
    )
    parser.add_argument(
        "--device", default="auto",
        choices=["auto", "GPU", "CPU"],
        help="Render device (default: auto-detect Metal on macOS)",
    )
    parser.add_argument(
        "--no-denoising", action="store_true",
        help="Disable OptiX/Metal denoising (use if causing artefacts)",
    )
    return parser.parse_args(argv)


def configure_metal_gpu(scene):
    """
    Enable Metal GPU rendering on macOS (Apple Silicon or AMD).
    Blender 4.x supports Metal via Cycles backend.
    Falls back to CPU automatically if Metal is unavailable.
    """
    import bpy

    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.refresh_devices()

    # Try Metal first (macOS), then CUDA/HIP, then CPU
    for device_type in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
        prefs.compute_device_type = device_type
        prefs.refresh_devices()
        devices = prefs.get_devices_for_type(device_type)
        if devices:
            for d in devices:
                d.use = True
            print(f"  GPU backend: {device_type}")
            print(f"  Devices: {[d.name for d in devices if d.use]}")
            scene.cycles.device = "GPU"
            return

    print("  No GPU found — falling back to CPU")
    scene.cycles.device = "CPU"


def configure_render_quality_8k(scene, samples: int, use_denoising: bool):
    """
    Apply quality settings optimised for 8K Cycles output.
    Higher tile size benefits GPU VRAM throughput at large resolutions.
    """
    import bpy

    cycles = scene.cycles

    # Adaptive sampling — reduces samples in dark regions automatically
    cycles.use_adaptive_sampling = True
    cycles.adaptive_threshold = 0.01  # Tight threshold for 8K quality
    cycles.samples = samples
    cycles.adaptive_min_samples = max(samples // 4, 32)

    # Denoising (Intel Open Image Denoise — CPU-based, works everywhere)
    cycles.use_denoising = use_denoising
    if use_denoising:
        cycles.denoiser = "OPENIMAGEDENOISE"
        cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"

    # Light path — galaxy scene only needs emission, no GI bounces
    cycles.max_bounces = 2
    cycles.diffuse_bounces = 1
    cycles.glossy_bounces = 1
    cycles.transmission_bounces = 0
    cycles.transparent_max_bounces = 8

    # Tile size: larger tiles are faster on GPU with big VRAM
    # Blender 3.x+: auto tile size handled internally
    scene.render.use_persistent_data = True  # Reuse BVH across frames


def main():
    args = parse_args()

    import bpy
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from animation.scene import build_scene
    from animation.camera_path import create_camera, apply_keyframes, TOTAL_SECONDS

    parquet_path = Path(args.parquet)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    w, h = args.resolution.split("x")
    fps = args.fps

    # ─── Build scene ────────────────────────────────────────────────────────
    print("=" * 60)
    print("DesiMapper — Blender Animation Renderer")
    print(f"  Resolution : {w}×{h} ({args.resolution})")
    print(f"  FPS        : {fps}")
    print(f"  Samples    : {args.samples}")
    print(f"  Max points : {args.max_points:,}")
    print(f"  Output     : {output_dir}/")
    print("=" * 60)

    build_scene(parquet_path, max_points=args.max_points)

    cam = create_camera()
    # Update camera path for 60fps (more keyframes for smoothness)
    apply_keyframes(cam, fps=fps)

    # ─── Render settings ────────────────────────────────────────────────────
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.fps = fps
    scene.render.fps_base = 1

    # Resolution
    scene.render.resolution_x = int(w)
    scene.render.resolution_y = int(h)
    scene.render.resolution_percentage = 100

    # Output format — EXR for 8K to preserve HDR range before colour grade
    # Switch to PNG if disk space is a concern
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "16"
    scene.render.image_settings.exr_codec = "ZIPS"  # Fast lossless EXR

    # Colour management — filmic for natural star/galaxy look
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "High Contrast"
    scene.view_settings.exposure = 0.5
    scene.view_settings.gamma = 1.0

    # GPU setup
    if args.device == "auto":
        configure_metal_gpu(scene)
    else:
        scene.cycles.device = args.device

    configure_render_quality_8k(scene, args.samples, not args.no_denoising)

    scene.frame_start = args.start_frame
    scene.frame_end = args.end_frame or int(TOTAL_SECONDS * fps)
    # Zero-pad frame numbers for correct sort order
    scene.render.filepath = str(output_dir / "frame_####")

    total_frames = (scene.frame_end - scene.frame_start) + 1
    storage_gb = total_frames * 50 / 1024  # ~50 MB per 8K EXR
    print(f"\nRendering {total_frames} frames")
    print(f"Estimated storage: ~{storage_gb:.0f} GB")
    print(f"Output: {output_dir}/frame_####.exr\n")

    # ─── Render ─────────────────────────────────────────────────────────────
    bpy.ops.render.render(animation=True)
    print("\nRender complete!")
    print(f"Next step: bash scripts/encode_video.sh {output_dir} renders/desimapper_8k.mp4")


if __name__ == "__main__":
    main()
