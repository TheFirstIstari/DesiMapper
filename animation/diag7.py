"""
diag7.py - InstanceOnPoints via GeoNodes, GPU (Metal).
The instance sphere must NOT be linked to scene collection directly
(or it should be hidden from render) to avoid double rendering.
"""
import bpy
import numpy as np
import mathutils

def clear_all():
    for obj in list(bpy.data.objects): bpy.data.objects.remove(obj, do_unlink=True)
    for m in list(bpy.data.meshes):    bpy.data.meshes.remove(m)
    for ng in list(bpy.data.node_groups): bpy.data.node_groups.remove(ng)
    for mat in list(bpy.data.materials):  bpy.data.materials.remove(mat)

clear_all()

# ── Galaxy positions (4x4 grid) ───────────────────────────────────────────────
n = 16
coords = np.array([[(i%4)*1.2-1.8, (i//4)*1.2-1.8, 0] for i in range(n)], dtype=np.float32)
mesh = bpy.data.meshes.new("GalMesh")
mesh.vertices.add(n)
mesh.vertices.foreach_set("co", coords.ravel())
mesh.update()
obj = bpy.data.objects.new("Galaxies", mesh)
bpy.context.scene.collection.objects.link(obj)

# ── Material for instance spheres ─────────────────────────────────────────────
mat = bpy.data.materials.new("GalMat")
mat.use_nodes = True
mat.node_tree.nodes.clear()
out = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
em  = mat.node_tree.nodes.new("ShaderNodeEmission")
em.inputs["Color"].default_value    = (0.0, 0.6, 1.0, 1.0)
em.inputs["Strength"].default_value = 8.0
mat.node_tree.links.new(em.outputs["Emission"], out.inputs["Surface"])

# ── Tiny icosphere (instance template) ───────────────────────────────────────
# Create via primitive, then move to hidden collection
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.08)
ico = bpy.context.active_object
ico.name = "GalTemplate"
ico.data.materials.append(mat)
# Hide from render so it doesn't appear at its own origin
ico.hide_render = True
ico.hide_viewport = True

# ── Geometry Nodes: MeshToPoints → InstanceOnPoints ─────────────────────────
mod = obj.modifiers.new("GN", "NODES")
ng  = bpy.data.node_groups.new("GalInst", "GeometryNodeTree")
mod.node_group = ng

ng.interface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

gi    = ng.nodes.new("NodeGroupInput")
go    = ng.nodes.new("NodeGroupOutput")
m2p   = ng.nodes.new("GeometryNodeMeshToPoints")
m2p.mode = "VERTICES"
iop   = ng.nodes.new("GeometryNodeInstanceOnPoints")
obj_n = ng.nodes.new("GeometryNodeObjectInfo")
obj_n.inputs["Object"].default_value = ico
obj_n.transform_space = "RELATIVE"
ri    = ng.nodes.new("GeometryNodeRealizeInstances")

# Wire it up
ng.links.new(gi.outputs[0],              m2p.inputs["Mesh"])
ng.links.new(obj_n.outputs["Geometry"],  iop.inputs["Instance"])
ng.links.new(m2p.outputs["Points"],      iop.inputs["Points"])
ng.links.new(iop.outputs["Instances"],   ri.inputs["Geometry"])
ng.links.new(ri.outputs["Geometry"],     go.inputs[0])

# ── Camera looking at the grid ────────────────────────────────────────────────
bpy.ops.object.camera_add(location=(0, 0, 8))
cam = bpy.context.active_object
cam.rotation_euler = mathutils.Euler((0, 0, 0), "XYZ")
cam.data.lens = 35
cam.data.clip_start = 0.01
cam.data.clip_end   = 200.0
bpy.context.scene.camera = cam

print(f"Camera at {cam.location[:]}, looking toward origin (Z-down)")
print(f"Galaxies obj at {obj.location[:]}")

# ── World ─────────────────────────────────────────────────────────────────────
world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0

# ── Render ────────────────────────────────────────────────────────────────────
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.cycles.device  = "GPU"
scene.render.resolution_x = 480
scene.render.resolution_y = 270
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = "renders/test/diag7_"
scene.frame_start = scene.frame_end = 1
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma    = 1.0

bpy.ops.render.render(animation=True)
print("✓ diag7 done → renders/test/diag7_0001.png")
