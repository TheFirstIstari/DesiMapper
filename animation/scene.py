"""
scene.py — Blender Python scene definition for DesiMapper animation.

Run via: blender --background --python animation/render.py
Requires Blender 4.x with bpy available.

This module defines the 3D scene: galaxy point cloud, lighting, and world.
"""

import math
from pathlib import Path

import bpy
import numpy as np

# ─── Constants ──────────────────────────────────────────────────────────────

TRACER_COLORS = {
    0: (1.0, 0.549, 0.0, 1.0),    # BGS — orange
    1: (0.8, 0.133, 0.0, 1.0),    # LRG — deep red
    2: (0.0, 0.808, 0.820, 1.0),  # ELG — teal
    3: (0.533, 0.533, 1.0, 1.0),  # QSO — blue-violet
}

TRACER_NAMES = {0: "BGS", 1: "LRG", 2: "ELG", 3: "QSO"}


def clear_scene():
    """Remove all default objects."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)


def setup_world():
    """Pure black space background."""
    world = bpy.data.worlds["World"]
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.005, 1.0)
    bg.inputs["Strength"].default_value = 1.0


def load_galaxy_data(parquet_path: Path) -> dict:
    """
    Load galaxy data from Parquet. Returns dict with arrays per tracer.
    Falls back to pyarrow if polars not available.
    """
    try:
        import polars as pl
        df = pl.read_parquet(parquet_path)
        return {
            "x": df["x"].to_numpy(),
            "y": df["y"].to_numpy(),
            "z_cart": df["z_cart"].to_numpy(),
            "tracer": df["tracer"].to_numpy(),
        }
    except ImportError:
        import pyarrow.parquet as pq
        table = pq.read_table(parquet_path)
        return {
            "x": table["x"].to_pylist(),
            "y": table["y"].to_pylist(),
            "z_cart": table["z_cart"].to_pylist(),
            "tracer": table["tracer"].to_pylist(),
        }


def create_galaxy_mesh(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    tracer_ids: np.ndarray,
    name: str,
    scale: float = 0.001,
) -> bpy.types.Object:
    """
    Create a Blender mesh object with a vertex per galaxy.
    Scale converts Mpc → Blender units (default: 1 Mpc = 0.001 BU → scene spans ~10 BU).
    """
    mesh = bpy.data.meshes.new(name)
    vertices = [(x[i] * scale, y[i] * scale, z[i] * scale) for i in range(len(x))]
    mesh.from_pydata(vertices, [], [])
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    # Vertex colour by tracer for shader use
    color_layer = mesh.vertex_colors.new(name="TracerColor")
    for i, loop in enumerate(mesh.loops):
        vi = loop.vertex_index
        tid = int(tracer_ids[vi])
        color_layer.data[i].color = TRACER_COLORS.get(tid, (1, 1, 1, 1))

    return obj


def create_galaxy_material(name: str) -> bpy.types.Material:
    """Emission material that reads vertex colour."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    vcol = nodes.new("ShaderNodeVertexColor")
    vcol.layer_name = "TracerColor"

    emission.inputs["Strength"].default_value = 3.0
    links.new(vcol.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    mat.blend_method = "BLEND"
    return mat


def add_geometry_nodes_points(obj: bpy.types.Object, point_radius: float = 0.002):
    """
    Use Geometry Nodes to render vertices as spherical points.
    This is the modern Blender 4.x approach for particle-like rendering.
    """
    modifier = obj.modifiers.new("GeoNodes", "NODES")
    node_group = bpy.data.node_groups.new("GalaxyPoints", "GeometryNodeTree")
    modifier.node_group = node_group

    nodes = node_group.nodes
    links = node_group.links

    # Interface
    node_group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    node_group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    group_in = nodes.new("NodeGroupInput")
    group_out = nodes.new("NodeGroupOutput")

    mesh_to_points = nodes.new("GeometryNodeMeshToPoints")
    mesh_to_points.inputs["Radius"].default_value = point_radius

    links.new(group_in.outputs["Geometry"], mesh_to_points.inputs["Mesh"])
    links.new(mesh_to_points.outputs["Points"], group_out.inputs["Geometry"])


def build_scene(parquet_path: Path, max_points: int = 500_000, scale: float = 0.001):
    """Full scene construction pipeline."""
    clear_scene()
    setup_world()

    print(f"Loading galaxy data from {parquet_path}…")
    data = load_galaxy_data(parquet_path)

    x = np.array(data["x"], dtype=np.float32)
    y = np.array(data["y"], dtype=np.float32)
    z = np.array(data["z_cart"], dtype=np.float32)
    tracer = np.array(data["tracer"], dtype=np.uint8)

    # Downsample if needed
    n = len(x)
    if n > max_points:
        print(f"Downsampling {n:,} → {max_points:,} points for render…")
        idx = np.random.choice(n, max_points, replace=False)
        x, y, z, tracer = x[idx], y[idx], z[idx], tracer[idx]

    print(f"Creating mesh with {len(x):,} vertices…")
    obj = create_galaxy_mesh(x, y, z, tracer, name="Galaxies", scale=scale)
    mat = create_galaxy_material("GalaxyMat")
    obj.data.materials.append(mat)
    add_geometry_nodes_points(obj)

    print("Scene built successfully.")
    return obj
