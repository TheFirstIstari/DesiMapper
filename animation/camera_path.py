"""
camera_path.py — Cinematic camera trajectory for the DESI universe animation.

Defines keyframe sequences for a ~4 minute fly-through of the galaxy survey.
Designed for 30fps output. All positions in Blender units (1 BU = 1000 Mpc).
"""

import math
from dataclasses import dataclass
from typing import List, Tuple

import bpy

DEFAULT_FPS = 60  # 8K production default


@dataclass
class CameraKeyframe:
    """A single camera keyframe."""
    frame: int
    location: Tuple[float, float, float]
    look_at: Tuple[float, float, float]
    lens_mm: float = 35.0


def frame(seconds: float, fps: int = DEFAULT_FPS) -> int:
    return int(seconds * fps)


# ─── Camera Path Definition ─────────────────────────────────────────────────
#
# Defined in (seconds, location, look_at, lens_mm) — converted to frames
# dynamically based on the target FPS at apply time.
#
# Scene scale: 1 BU = 1000 Mpc
# BGS shell (z~0.3): r ~ 1.2 BU
# LRG shell (z~0.7): r ~ 2.0 BU
# ELG shell (z~1.2): r ~ 3.0 BU
# QSO shell (z~1.5): r ~ 3.5 BU
#
# DESI survey geometry: The cone opens primarily toward -Y (Dec),
# with data spanning X=(-6.9,6.6), Y=(-6.7,0.1), Z=(-1.4,6.3).
# Centre of mass ≈ (-0.7, -1.6, 0.8). The camera must stay within
# the cone's opening (negative Y hemisphere) to see the full volume.
#
# Focus point: Slightly offset from origin toward the data centre of mass.
#
# Total duration: ~4 minutes at 60fps
#

# Focal point — offset from origin toward the survey's centre of mass
FOCUS = (-0.5, -1.0, 0.5)

# (seconds, location, look_at, lens_mm)
KEYFRAME_DEFS: List[Tuple[float, Tuple, Tuple, float]] = [
    # Segment 1: Opening — wide shot from above/outside the cone
    (0.0,   (2.0,  2.0,   8.0),   FOCUS, 22),
    (5.0,   (2.0,  2.0,   8.0),   FOCUS, 22),

    # Segment 2: Slow arc — reveal the full cone shape
    (5.0,   (2.0,  2.0,   8.0),   FOCUS, 22),
    (25.0,  (-3.0, -3.0,  7.0),   FOCUS, 20),

    # Segment 3: Sweep alongside the QSO shell (blue-violet, outermost)
    (25.0,  (-3.0, -3.0,  7.0),   FOCUS, 20),
    (50.0,  (4.0,  -5.0,  4.0),   FOCUS, 22),

    # Segment 4: Dive into the ELG shell (teal, z~1.2)
    (50.0,  (4.0,  -5.0,  4.0),   FOCUS, 22),
    (80.0,  (-2.0, -4.0,  3.5),   FOCUS, 24),

    # Segment 5: Through the LRG shell (deep red, z~0.7)
    (80.0,  (-2.0, -4.0,  3.5),   FOCUS, 24),
    (110.0, (1.5,  -2.5,  2.5),   FOCUS, 28),

    # Segment 6: Orbit within BGS (orange, nearest — cosmic web detail)
    # Stay far enough out to see structure, not a wall of points.
    (110.0, (1.5,  -2.5,  2.5),   FOCUS, 28),
    (135.0, (-1.5, -2.0,  2.5),   FOCUS, 28),
    (160.0, (1.5,  -2.5,  3.0),   FOCUS, 26),

    # Segment 7: Pull back out — grand reveal of full volume
    (160.0, (1.0,  -2.0,  2.0),   FOCUS, 24),
    (185.0, (-4.0, -5.0,  6.0),   FOCUS, 20),
    (210.0, (4.0,  -3.0,  7.0),   FOCUS, 20),

    # Segment 8: Final sweep + fade — drift upward and away
    (210.0, (4.0,  -3.0,  7.0),   FOCUS, 20),
    (235.0, (0.0,  1.0,   9.0),   FOCUS, 18),
    (240.0, (0.0,  2.0,  10.0),   FOCUS, 18),
]

TOTAL_SECONDS = 240.0


def build_keyframes(fps: int) -> List[CameraKeyframe]:
    """Convert second-based definitions to frame-based keyframes."""
    return [
        CameraKeyframe(
            frame=int(t * fps),
            location=loc,
            look_at=look,
            lens_mm=lens,
        )
        for t, loc, look, lens in KEYFRAME_DEFS
    ]


def apply_keyframes(camera_obj: bpy.types.Object, fps: int = DEFAULT_FPS) -> None:
    """Apply keyframes to a Blender camera object at the given FPS."""
    import mathutils

    cam = camera_obj.data
    scene = bpy.context.scene
    keyframes = build_keyframes(fps)
    total_frames = int(TOTAL_SECONDS * fps) + 1
    scene.frame_end = total_frames

    for kf in keyframes:
        scene.frame_set(kf.frame)
        camera_obj.location = kf.location
        camera_obj.keyframe_insert(data_path="location", frame=kf.frame)

        # Compute look-at rotation
        lx, ly, lz = kf.location
        tx, ty, tz = kf.look_at
        dx, dy, dz = tx - lx, ty - ly, tz - lz
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist > 0:
            direction = mathutils.Vector((dx, dy, dz)).normalized()
            rot_quat = direction.to_track_quat("-Z", "Y")
            camera_obj.rotation_mode = "QUATERNION"
            camera_obj.rotation_quaternion = rot_quat
            camera_obj.keyframe_insert(data_path="rotation_quaternion", frame=kf.frame)

        cam.lens = kf.lens_mm
        cam.keyframe_insert(data_path="lens", frame=kf.frame)

    # Smooth bezier interpolation on all curves.
    # Blender 5.0+ redesigned the Action system: fcurves are now accessed via
    # action.layers[].strips[].channelbag(slot).fcurves rather than action.fcurves.
    for action in bpy.data.actions:
        if hasattr(action, "fcurves"):
            # Blender 4.x legacy path
            fcurve_iter = action.fcurves
        else:
            # Blender 5.0+ layered Action path
            fcurve_iter = []
            for layer in action.layers:
                for strip in layer.strips:
                    for slot in action.slots:
                        try:
                            cb = strip.channelbag(slot)
                            fcurve_iter = list(cb.fcurves)
                        except Exception:
                            pass
        for fcurve in fcurve_iter:
            for kfp in fcurve.keyframe_points:
                kfp.interpolation = "BEZIER"
                kfp.easing = "AUTO"

    duration_min = TOTAL_SECONDS / 60
    print(f"Applied {len(keyframes)} keyframes → {total_frames} frames @ {fps}fps ({duration_min:.1f} min)")


def create_camera() -> bpy.types.Object:
    """Create and return a camera object."""
    bpy.ops.object.camera_add(location=(5.0, 3.0, 4.0))
    cam_obj = bpy.context.active_object
    cam_obj.name = "DesiCamera"
    cam_obj.data.name = "DesiCamera"
    cam_obj.data.clip_end = 50.0
    cam_obj.data.clip_start = 0.001
    bpy.context.scene.camera = cam_obj
    return cam_obj
