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
        help="Cycles render samples per frame (default: 128 — adaptive sampling disabled)",
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
    Enable Metal GPU + CPU rendering on Apple Silicon (M-series).

    On M4 with unified memory, enabling BOTH the GPU and CPU device under
    Metal lets Blender use:
      - GPU cores for tile rendering
      - All CPU cores for BVH build, denoising, and CPU-side prep work
    This eliminates the intermittent CPU idle gaps seen with GPU-only mode.
    """
    import bpy
    import multiprocessing

    prefs = bpy.context.preferences.addons["cycles"].preferences

    # On macOS only Metal is available; set it directly without looping
    # through CUDA/HIP etc. (those raise TypeError on Apple Silicon)
    for device_type in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
        try:
            prefs.compute_device_type = device_type
        except TypeError:
            continue
        prefs.refresh_devices()
        devices = prefs.get_devices_for_type(device_type)
        if not devices:
            continue

        # Enable ALL devices: both GPU and CPU cores
        # On Apple Silicon, CPU device appears alongside GPU under Metal
        for d in devices:
            d.use = True
            print(f"  Enabled: {d.name!r}  ({d.type})")

        scene.cycles.device = "GPU"
        print(f"  Backend: {device_type}")
        break
    else:
        print("  No GPU — falling back to CPU")
        scene.cycles.device = "CPU"

    # Pin all CPU threads (Blender defaults to AUTO which may under-utilise)
    ncpu = multiprocessing.cpu_count()
    scene.render.threads_mode = "FIXED"
    scene.render.threads = ncpu
    print(f"  CPU threads: {ncpu} (FIXED)")


def configure_render_quality(scene, samples: int, use_denoising: bool):
    """
    Render quality settings tuned for emission-only galaxy scene.
    Works for both test (1080p) and production (8K) renders.

    Key insight: OIDN CPU denoising consumed ~75% of frame time (2.8s of 3.5s)
    with the GPU idle. Fix: run OIDN on GPU (denoising_use_gpu=True) and use
    FAST prefilter. For pure emission scenes, disabling denoising entirely and
    using more samples is often faster overall (GPU stays busy continuously).
    """
    cycles = scene.cycles

    # Adaptive sampling DISABLED — root cause of low GPU utilisation.
    # With a mostly-black frame (99% background), Cycles' adaptive convergence
    # checker runs a CPU sync barrier every few samples, bottlenecking the
    # entire pipeline. Benchmark result: adaptive ON = 10s/frame,
    # adaptive OFF = 1.3s/frame at 128spp on M4. Use fixed sample count instead.
    cycles.use_adaptive_sampling     = False
    cycles.samples                   = samples

    # Denoising disabled — emission-only point sources at 256spp have
    # essentially zero noise, so denoising adds cost with no visible benefit.
    # (CPU OIDN consumed 75% of frame time; GPU OIDN caused erratic stalls.)
    cycles.use_denoising = use_denoising
    if use_denoising:
        cycles.denoiser               = "OPENIMAGEDENOISE"
        cycles.denoising_use_gpu      = True
        cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
        cycles.denoising_prefilter    = "FAST"
        cycles.denoising_quality      = "BALANCED"

    # Light paths — pure emission scene needs no bounces
    cycles.max_bounces               = 1
    cycles.diffuse_bounces           = 0
    cycles.glossy_bounces            = 0
    cycles.transmission_bounces      = 0
    cycles.volume_bounces            = 0
    cycles.transparent_max_bounces   = 4

    # Large tiles keep the Metal GPU command buffer full between flushes.
    # Benchmarked: 8192 (2.318s) ≈ 4096 (2.337s) > 2048 (2.412s) > 1024 (2.747s)
    cycles.tile_size = 8192

    # Reuse BVH/geometry across frames — saves ~1s/frame on 10M-tri scene
    scene.render.use_persistent_data = True


def main():
    args = parse_args()

    import bpy
    # Insert both project root and animation dir so imports work
    script_dir   = Path(__file__).resolve().parent
    project_root = script_dir.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(script_dir))

    from scene import build_scene
    from camera_path import create_camera, apply_keyframes, TOTAL_SECONDS

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

    build_scene(parquet_path, max_points=args.max_points, galaxy_radius=0.005)

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

    # Output format: PNG 8-bit, compress=5
    # Benchmarked: 8-bit saves 0.1s/frame vs 16-bit; compress=5 is the
    # crossover point where CPU compression time == disk write time.
    # compress=0 is slower (larger writes); compress=15+ is slower (more CPU).
    # For an emission-only scene 8-bit has no visible quality loss vs 16-bit.
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 5

    # Colour management — Filmic with gentle contrast for space visualization
    # "High Contrast" clips emission colors; use medium contrast instead
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium Contrast"
    scene.view_settings.exposure = -0.5   # bring down to preserve tracer color hues
    scene.view_settings.gamma = 1.0

    # GPU setup
    if args.device == "auto":
        configure_metal_gpu(scene)
    else:
        scene.cycles.device = args.device

    configure_render_quality(scene, args.samples, not args.no_denoising)

    scene.frame_start = args.start_frame
    scene.frame_end = args.end_frame or int(TOTAL_SECONDS * fps)
    # Zero-pad frame numbers for correct sort order
    scene.render.filepath = str(output_dir / "frame_####")

    total_frames = (scene.frame_end - scene.frame_start) + 1
    storage_gb = total_frames * 15 / 1024  # ~15 MB per 8K PNG
    print(f"\nRendering {total_frames} frames")
    print(f"Estimated storage: ~{storage_gb:.0f} GB")
    print(f"Output: {output_dir}/frame_####.png\n")

    # ─── Render ─────────────────────────────────────────────────────────────
    bpy.ops.render.render(animation=True)
    print("\nRender complete!")
    print(f"Next step: bash scripts/encode_video.sh {output_dir} renders/desimapper_8k.mp4")


if __name__ == "__main__":
    main()
