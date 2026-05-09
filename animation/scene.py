"""
scene.py — Blender Python scene definition for DesiMapper animation.

Run via: blender --background --python animation/render.py
Requires Blender 4.3 with bpy available.

Rendering approach (confirmed working with Metal/GPU on macOS Blender 4.3):
  MeshToPoints → InstanceOnPoints → RealizeInstances
  Cycles native PointCloud rendering is broken on Metal; instanced icospheres work.
"""

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


def get_or_create_template_collection() -> bpy.types.Collection:
    """Return (creating if needed) a collection that is excluded from render.

    Template icospheres are placed here so Blender 5.x never renders them
    even if hide_render alone isn't honoured by the ObjectInfo geo-node.
    """
    name = "Templates_NoRender"
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    # Exclude from the view layer so nothing in it renders.
    # Also set holdout + indirect_only as belt-and-suspenders.
    layer_col = bpy.context.view_layer.layer_collection.children.get(name)
    if layer_col is not None:
        layer_col.exclude      = True
        layer_col.holdout      = True
        layer_col.indirect_only = True
    bpy.context.view_layer.update()
    return col


def clear_scene():
    """Remove all default objects from the scene."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)
    for ng in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(ng)


def setup_world():
    """Pure deep-space background."""
    world = bpy.data.worlds.get("World")
    if world is None:
        world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    bg = nodes.get("Background")
    if bg is None:
        bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.004, 1.0)
    bg.inputs["Strength"].default_value = 1.0


def load_galaxy_data(parquet_path: Path) -> dict:
    """
    Load galaxy XYZ + tracer from Parquet using pyarrow (Blender's Python).
    Returns numpy arrays.
    """
    import pyarrow.parquet as pq
    print(f"  Reading Parquet: {parquet_path}")
    table = pq.read_table(
        parquet_path,
        columns=["x", "y", "z_cart", "tracer"],
    )
    return {
        "x":      table["x"].to_pylist(),
        "y":      table["y"].to_pylist(),
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
    Create a Blender mesh with one vertex per galaxy.
    Scale: 1 Mpc = 0.001 BU → survey spans ~0–6.5 BU.
    Uses fast foreach_set for bulk vertex assignment.
    Stores per-vertex TracerID attribute for color lookup.
    """
    n = len(x)
    mesh = bpy.data.meshes.new(name)

    # Interleave XYZ into flat array for foreach_set
    coords = np.empty((n, 3), dtype=np.float32)
    coords[:, 0] = x * scale
    coords[:, 1] = y * scale
    coords[:, 2] = z * scale

    mesh.vertices.add(n)
    mesh.vertices.foreach_set("co", coords.ravel())
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    # Assign a fully transparent material so the host mesh vertices don't render
    # as grey geometry alongside the geo-nodes icosphere instances.
    invis = bpy.data.materials.new(f"{name}_Invisible")
    invis.use_nodes = True
    invis.blend_method = "CLIP"
    nt = invis.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    nt.links.new(trans.outputs["BSDF"], out.inputs["Surface"])
    mesh.materials.append(invis)

    # Store tracer type as INT attribute on vertices
    tracer_attr = mesh.attributes.new(name="tracer_id", type="INT", domain="POINT")
    tracer_attr.data.foreach_set("value", tracer_ids.astype(np.int32))

    return obj


def create_tracer_material(tracer_id: int) -> bpy.types.Material:
    """Single-colour emission material for one tracer type."""
    color = TRACER_COLORS[tracer_id]
    name  = TRACER_NAMES[tracer_id]
    mat   = bpy.data.materials.new(f"Mat_{name}")
    mat.use_nodes = True
    tree  = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    em  = tree.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value    = color
    em.inputs["Strength"].default_value = 6.0
    tree.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def create_instance_template(tracer_id: int, radius: float) -> bpy.types.Object:
    """
    Tiny icosphere used as instance template for one tracer type.
    Placed in the Templates_NoRender collection (excluded from render) so
    Blender 5.x never renders it, even via ObjectInfo in geo-nodes.
    """
    name = TRACER_NAMES[tracer_id]
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius)
    ico = bpy.context.active_object
    ico.name = f"Template_{name}"
    mat = create_tracer_material(tracer_id)
    ico.data.materials.append(mat)
    # Extract radius and material before deleting the scene object.
    # The geo-nodes tree uses GeometryNodeMeshIcoSphere inline, so the
    # physical icosphere object is only needed for these two values.
    # We delete it immediately because Blender 5.1 ignores hide_render,
    # visible_camera, and collection exclusion in background renders.
    radius   = ico.data.vertices[0].co.length
    material = ico.data.materials[0]
    ico_mesh = ico.data
    bpy.data.objects.remove(ico, do_unlink=True)
    bpy.data.meshes.remove(ico_mesh)
    return {"radius": radius, "material": material}


def add_instance_on_points_geonodes(
    obj: bpy.types.Object,
    templates: dict,           # tracer_id → icosphere Object
) -> None:
    """
    Geometry Nodes modifier that:
      1. Splits mesh vertices by tracer_id attribute
      2. For each tracer: MeshToPoints → InstanceOnPoints using that tracer's template
      3. Joins all instances and outputs
    Works with Cycles + Metal on macOS Blender 4.3.
    """
    mod = obj.modifiers.new("GN_Galaxies", "NODES")
    ng  = bpy.data.node_groups.new("GalaxyInstances", "GeometryNodeTree")
    mod.node_group = ng

    ng.interface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    nodes = ng.nodes
    links = ng.links

    gi  = nodes.new("NodeGroupInput")
    go  = nodes.new("NodeGroupOutput")

    # Position nodes in a readable layout
    gi.location = (-600, 0)
    go.location = (1000, 0)

    join = nodes.new("GeometryNodeJoinGeometry")
    join.location = (800, 0)
    links.new(join.outputs["Geometry"], go.inputs[0])

    y_offset = 300
    for tid, ico_obj in sorted(templates.items()):
        y = y_offset - tid * 250

        # Compare: tracer_id attribute == tid
        compare = nodes.new("FunctionNodeCompare")
        compare.data_type = "INT"
        compare.operation = "EQUAL"
        compare.inputs[3].default_value = tid   # index 3 = B (INT)
        compare.location = (-300, y)

        # Read tracer_id attribute per vertex
        attr = nodes.new("GeometryNodeInputNamedAttribute")
        attr.data_type = "INT"
        attr.inputs["Name"].default_value = "tracer_id"
        attr.location = (-500, y - 60)
        links.new(attr.outputs[0], compare.inputs[2])  # Attribute → A (INT, index 2)

        # MeshToPoints with selection mask
        m2p = nodes.new("GeometryNodeMeshToPoints")
        m2p.mode = "VERTICES"
        m2p.inputs[3].default_value = 0.005  # radius (visual only, not used for inst)
        m2p.location = (-100, y)
        links.new(gi.outputs[0],          m2p.inputs["Mesh"])
        links.new(compare.outputs["Result"], m2p.inputs["Selection"])

        # IcoSphere node — self-contained geometry, no scene object reference needed.
        # Avoids the Blender 5.x bug where ObjectInfo leaks the template mesh.
        ico_node = nodes.new("GeometryNodeMeshIcoSphere")
        ico_node.inputs["Radius"].default_value = ico_obj["radius"]
        ico_node.inputs["Subdivisions"].default_value = 1
        ico_node.location = (-100, y - 120)

        # Set material on the realized geometry via a SetMaterial node
        set_mat = nodes.new("GeometryNodeSetMaterial")
        set_mat.inputs["Material"].default_value = ico_obj["material"]
        set_mat.location = (100, y - 120)
        links.new(ico_node.outputs["Mesh"], set_mat.inputs["Geometry"])

        # InstanceOnPoints
        iop = nodes.new("GeometryNodeInstanceOnPoints")
        iop.location = (300, y)
        links.new(m2p.outputs["Points"],      iop.inputs["Points"])
        links.new(set_mat.outputs["Geometry"], iop.inputs["Instance"])

        # RealizeInstances (required so Cycles sees real geometry)
        ri = nodes.new("GeometryNodeRealizeInstances")
        ri.location = (560, y)
        links.new(iop.outputs["Instances"],  ri.inputs["Geometry"])
        links.new(ri.outputs["Geometry"],    join.inputs["Geometry"])


def add_background_stars(n: int = 3000, spread: float = 8.0, ico_radius: float = 0.002):
    """Faint background star field using same InstanceOnPoints approach."""
    np.random.seed(42)
    mesh = bpy.data.meshes.new("Stars")
    coords = (np.random.rand(n, 3) - 0.5) * spread
    mesh.vertices.add(n)
    mesh.vertices.foreach_set("co", coords.astype(np.float32).ravel())
    mesh.update()

    obj = bpy.data.objects.new("Stars", mesh)
    bpy.context.scene.collection.objects.link(obj)

    # Invisible material for the host mesh vertices (same fix as galaxy host mesh)
    invis = bpy.data.materials.new("Stars_Invisible")
    invis.use_nodes = True
    invis.blend_method = "CLIP"
    nt = invis.node_tree
    nt.nodes.clear()
    out_i = nt.nodes.new("ShaderNodeOutputMaterial")
    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    nt.links.new(trans.outputs["BSDF"], out_i.inputs["Surface"])
    mesh.materials.append(invis)

    # Star material
    mat = bpy.data.materials.new("StarMat")
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    out = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    em  = mat.node_tree.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value    = (0.7, 0.8, 1.0, 1.0)
    em.inputs["Strength"].default_value = 0.8
    mat.node_tree.links.new(em.outputs["Emission"], out.inputs["Surface"])

    # No template object needed — geo-nodes uses GeometryNodeMeshIcoSphere inline.

    # GeoNodes: MeshToPoints → IcoSphere (inline) → InstanceOnPoints → RealizeInstances
    # Using GeometryNodeMeshIcoSphere instead of ObjectInfo avoids the Blender 5.x
    # bug where the referenced object's mesh leaks into the render.
    mod = obj.modifiers.new("StarGeo", "NODES")
    ng  = bpy.data.node_groups.new("StarPoints", "GeometryNodeTree")
    mod.node_group = ng
    ng.interface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi   = ng.nodes.new("NodeGroupInput")
    go   = ng.nodes.new("NodeGroupOutput")
    m2p  = ng.nodes.new("GeometryNodeMeshToPoints")
    m2p.mode = "VERTICES"
    ico_n = ng.nodes.new("GeometryNodeMeshIcoSphere")
    ico_n.inputs["Radius"].default_value = ico_radius
    ico_n.inputs["Subdivisions"].default_value = 1
    sm   = ng.nodes.new("GeometryNodeSetMaterial")
    sm.inputs["Material"].default_value = mat
    iop  = ng.nodes.new("GeometryNodeInstanceOnPoints")
    ri   = ng.nodes.new("GeometryNodeRealizeInstances")
    ng.links.new(gi.outputs[0],         m2p.inputs["Mesh"])
    ng.links.new(ico_n.outputs["Mesh"], sm.inputs["Geometry"])
    ng.links.new(sm.outputs["Geometry"], iop.inputs["Instance"])
    ng.links.new(m2p.outputs["Points"], iop.inputs["Points"])
    ng.links.new(iop.outputs["Instances"], ri.inputs["Geometry"])
    ng.links.new(ri.outputs["Geometry"], go.inputs[0])


def build_scene(
    parquet_path: Path,
    max_points: int = 1_400_000,
    scale: float = 0.001,
    galaxy_radius: float = 0.008,
) -> bpy.types.Object:
    """Full scene construction — data load, mesh, per-tracer instancing, stars."""
    np.random.seed(42)

    clear_scene()
    setup_world()

    print(f"Loading galaxy data from {parquet_path}…")
    data = load_galaxy_data(parquet_path)

    x      = np.asarray(data["x"],      dtype=np.float32)
    y      = np.asarray(data["y"],      dtype=np.float32)
    z      = np.asarray(data["z_cart"], dtype=np.float32)
    tracer = np.asarray(data["tracer"], dtype=np.int32)

    n = len(x)
    if n > max_points:
        print(f"  Downsampling {n:,} → {max_points:,} points…")
        idx = np.random.choice(n, max_points, replace=False)
        x, y, z, tracer = x[idx], y[idx], z[idx], tracer[idx]

    present_tracers = np.unique(tracer).tolist()
    print(f"  Tracer types present: {[TRACER_NAMES.get(t, t) for t in present_tracers]}")
    print(f"  Building mesh with {len(x):,} vertices…")
    obj = create_galaxy_mesh(x, y, z, tracer, name="Galaxies", scale=scale)

    # Create one icosphere template per tracer type
    templates = {}
    for tid in present_tracers:
        templates[tid] = create_instance_template(tid, radius=galaxy_radius)

    add_instance_on_points_geonodes(obj, templates)

    add_background_stars()

    print("  Scene built successfully.")
    return obj
