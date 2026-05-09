"""
Definitive working diagnostic: Geometry Nodes MeshToPoints → Cycles render.
Blender 4.3 confirmed pattern.
"""
import bpy
import numpy as np
import mathutils

# ── Clear ───────────────────────────────────────────────────────────────────
for obj in list(bpy.data.objects): bpy.data.objects.remove(obj, do_unlink=True)
for m in list(bpy.data.meshes):    bpy.data.meshes.remove(m)
for ng in list(bpy.data.node_groups): bpy.data.node_groups.remove(ng)
for mat in list(bpy.data.materials):  bpy.data.materials.remove(mat)

# ── Build mesh (10x10 grid) ─────────────────────────────────────────────────
n = 100
coords = np.zeros((n, 3), dtype=np.float32)
for i in range(n):
    coords[i] = [(i % 10) * 0.4 - 2.0,
                 (i // 10) * 0.4 - 2.0,
                 0.0]

mesh = bpy.data.meshes.new("GalMesh")
mesh.vertices.add(n)
mesh.vertices.foreach_set("co", coords.ravel())
mesh.update()

obj = bpy.data.objects.new("Galaxies", mesh)
bpy.context.scene.collection.objects.link(obj)

# ── Bright emission material ─────────────────────────────────────────────────
mat = bpy.data.materials.new("GalMat")
mat.use_nodes = True
mat.node_tree.nodes.clear()
out = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
em  = mat.node_tree.nodes.new("ShaderNodeEmission")
em.inputs["Color"].default_value    = (1.0, 0.4, 0.0, 1.0)  # orange
em.inputs["Strength"].default_value = 5.0
mat.node_tree.links.new(em.outputs["Emission"], out.inputs["Surface"])

# Assign material SLOT on the object (not just on mesh.materials)
obj.data.materials.append(mat)

# ── Geometry Nodes: vertices → large points ──────────────────────────────────
mod = obj.modifiers.new("GN", "NODES")
ng  = bpy.data.node_groups.new("GalPoints", "GeometryNodeTree")
mod.node_group = ng

# Blender 4.x: create interface sockets first
ng.interface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

gi  = ng.nodes.new("NodeGroupInput")
go  = ng.nodes.new("NodeGroupOutput")
m2p = ng.nodes.new("GeometryNodeMeshToPoints")
m2p.mode = "VERTICES"

# In Blender 4.3, MeshToPoints input sockets: 0=Mesh, 1=Selection, 2=Position, 3=Radius
m2p.inputs[3].default_value = 0.12   # large radius so points are clearly visible

# Connect: GroupInput.Geometry → MeshToPoints.Mesh → GroupOutput.Geometry
ng.links.new(gi.outputs[0],          m2p.inputs[0])   # Geometry → Mesh
ng.links.new(m2p.outputs["Points"],  go.inputs[0])    # Points → Geometry

# ── Camera ───────────────────────────────────────────────────────────────────
bpy.ops.object.camera_add(location=(0, -6, 3))
cam = bpy.context.active_object
cam.rotation_euler = mathutils.Euler((1.1, 0, 0), "XYZ")
cam.data.lens = 35
cam.data.clip_start = 0.01
cam.data.clip_end   = 100.0
bpy.context.scene.camera = cam

# ── World ────────────────────────────────────────────────────────────────────
world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0.03, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0

# ── Render settings ──────────────────────────────────────────────────────────
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.cycles.device  = "GPU"   # Metal on macOS
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = "renders/test/diag3_"
scene.frame_start = 1
scene.frame_end   = 1
# Standard transform (no filmic crushing)
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma = 1.0

bpy.ops.render.render(animation=True)
print("✓ Diagnostic render complete → renders/test/diag3_0001.png")
