"""
test_scene.py — Quick smoke test of build_scene() with real galaxy data.
Uses a subsample (50k points) and renders 1 frame at 960×540 on GPU.
"""
import sys
from pathlib import Path

# Find the project root (2 levels up from this script)
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent

import bpy
import mathutils
import numpy as np

# Add animation dir to path so we can import scene
sys.path.insert(0, str(script_dir))
from scene import build_scene

# ── Build scene with 50k point subsample ────────────────────────────────────
parquet = project_root / "data" / "processed" / "all_galaxies.parquet"
if not parquet.exists():
    print(f"ERROR: Parquet not found at {parquet}")
    sys.exit(1)

obj = build_scene(
    parquet_path=parquet,
    max_points=50_000,
    scale=0.001,
    galaxy_radius=0.008,
)

# ── Camera: orbit position looking at survey center ─────────────────────────
# Survey center is roughly (3000, 0, 500) Mpc * 0.001 = (3.0, 0, 0.5) BU
cx, cy, cz = 3.0, 0.0, 0.5

bpy.ops.object.camera_add(location=(cx - 4, cy - 6, cz + 2))
cam = bpy.context.active_object
cam.name = "Camera"
# Point camera at survey center
direction = mathutils.Vector((cx, cy, cz)) - mathutils.Vector(cam.location)
rot_quat  = direction.to_track_quat("-Z", "Y")
cam.rotation_euler = rot_quat.to_euler()
cam.data.lens = 35
cam.data.clip_start = 0.01
cam.data.clip_end   = 50.0
bpy.context.scene.camera = cam

print(f"Camera at {cam.location[:]}")
print(f"Camera rotation (euler): {[round(r,3) for r in cam.rotation_euler[:]]}")

# ── Render settings ──────────────────────────────────────────────────────────
scene = bpy.context.scene
scene.render.engine          = "CYCLES"
scene.cycles.samples         = 64
scene.cycles.device          = "GPU"
scene.render.resolution_x    = 960
scene.render.resolution_y    = 540
scene.render.image_settings.file_format = "PNG"
scene.render.filepath        = str(project_root / "renders" / "test" / "galaxy_test_")
scene.frame_start            = 1
scene.frame_end              = 1
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma    = 1.0

print("Starting render (50k galaxies, 64 samples, GPU)…")
bpy.ops.render.render(animation=True)
print("✓ Test render complete → renders/test/galaxy_test_0001.png")
