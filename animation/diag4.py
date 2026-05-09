"""
diag4.py - Test multiple rendering approaches to find what works in Blender 4.3 Cycles
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

# ── Approach: Instance tiny icospheres on mesh vertices via GeoNodes ──────────
# This is guaranteed to work in Cycles because each instance IS a real mesh
n = 25
coords = np.zeros((n, 3), dtype=np.float32)
for i in range(n):
    coords[i] = [(i % 5) * 0.8 - 1.6,
                 (i // 5) * 0.8 - 1.6,
                 0.0]

# Source mesh (vertices only)
mesh = bpy.data.meshes.new("GalMesh")
mesh.vertices.add(n)
mesh.vertices.foreach_set("co", coords.ravel())
mesh.update()
obj = bpy.data.objects.new("Galaxies", mesh)
bpy.context.scene.collection.objects.link(obj)

# Instance object: tiny icosphere
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.06, location=(100, 100, 100))
ico = bpy.context.active_object
ico.name = "GalaxyBall"

# Bright emission material on the icosphere
mat = bpy.data.materials.new("GalMat")
mat.use_nodes = True
mat.node_tree.nodes.clear()
out = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
em  = mat.node_tree.nodes.new("ShaderNodeEmission")
em.inputs["Color"].default_value    = (1.0, 0.5, 0.1, 1.0)
em.inputs["Strength"].default_value = 8.0
mat.node_tree.links.new(em.outputs["Emission"], out.inputs["Surface"])
ico.data.materials.append(mat)

# GeoNodes on obj: InstanceOnPoints using the icosphere
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
obj_n.inputs[0].default_value = ico
obj_n.transform_space = "RELATIVE"

# Wire: GroupIn.Geo → MeshToPoints.Mesh
ng.links.new(gi.outputs[0], m2p.inputs[0])
# Wire: ObjectInfo.Geometry → InstanceOnPoints.Instance
ng.links.new(obj_n.outputs["Geometry"], iop.inputs["Instance"])
# Wire: MeshToPoints.Points → InstanceOnPoints.Points
ng.links.new(m2p.outputs["Points"], iop.inputs["Points"])
# Wire: InstanceOnPoints.Instances → GroupOut.Geo
ng.links.new(iop.outputs["Instances"], go.inputs[0])

# ── Camera ───────────────────────────────────────────────────────────────────
bpy.ops.object.camera_add(location=(0, -7, 0))
cam = bpy.context.active_object
cam.rotation_euler = mathutils.Euler((1.5708, 0, 0), "XYZ")
cam.data.lens = 35
cam.data.clip_start = 0.01
cam.data.clip_end   = 200.0
bpy.context.scene.camera = cam

# ── World ────────────────────────────────────────────────────────────────────
world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.0, 0.0, 0.05, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0

# ── Render ───────────────────────────────────────────────────────────────────
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.cycles.device  = "GPU"
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = "renders/test/diag4_"
scene.frame_start = 1
scene.frame_end   = 1
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma    = 1.0

bpy.ops.render.render(animation=True)
print("✓ diag4 render complete → renders/test/diag4_0001.png")
