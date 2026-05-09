"""
diag6.py - Same as diag5 but with GPU, then GeoNodes MeshToPoints, then instances.
Step by step to isolate the rendering issue.
"""
import bpy
import numpy as np
import mathutils

def clear_all():
    for obj in list(bpy.data.objects): bpy.data.objects.remove(obj, do_unlink=True)
    for m in list(bpy.data.meshes):    bpy.data.meshes.remove(m)
    for ng in list(bpy.data.node_groups): bpy.data.node_groups.remove(ng)
    for mat in list(bpy.data.materials):  bpy.data.materials.remove(mat)

# ════════════════════════════════════════
# TEST 1: Single icosphere on GPU
# ════════════════════════════════════════
clear_all()

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.5, location=(0, 0, 0))
sphere = bpy.context.active_object
mat = bpy.data.materials.new("BrightMat")
mat.use_nodes = True
mat.node_tree.nodes.clear()
out = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
em  = mat.node_tree.nodes.new("ShaderNodeEmission")
em.inputs["Color"].default_value    = (1.0, 0.2, 0.0, 1.0)
em.inputs["Strength"].default_value = 10.0
mat.node_tree.links.new(em.outputs["Emission"], out.inputs["Surface"])
sphere.data.materials.append(mat)

bpy.ops.object.camera_add(location=(0, 0, 5))
cam = bpy.context.active_object
cam.rotation_euler = mathutils.Euler((0, 0, 0), "XYZ")
cam.data.clip_end = 100.0
bpy.context.scene.camera = cam

world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.cycles.device  = "GPU"   # Metal
scene.render.resolution_x = 480
scene.render.resolution_y = 270
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.frame_start = scene.frame_end = 1
scene.render.filepath = "renders/test/diag6a_"
bpy.ops.render.render(animation=True)
print("TEST 1 (GPU sphere) done → diag6a_0001.png")

# ════════════════════════════════════════
# TEST 2: Mesh vertices + MeshToPoints on GPU
# ════════════════════════════════════════
clear_all()

n = 16
coords = np.array([[(i%4)*1.0-1.5, (i//4)*1.0-1.5, 0] for i in range(n)], dtype=np.float32)
mesh = bpy.data.meshes.new("GalMesh")
mesh.vertices.add(n)
mesh.vertices.foreach_set("co", coords.ravel())
mesh.update()
obj = bpy.data.objects.new("Galaxies", mesh)
bpy.context.scene.collection.objects.link(obj)

mat2 = bpy.data.materials.new("PointMat")
mat2.use_nodes = True
mat2.node_tree.nodes.clear()
out2 = mat2.node_tree.nodes.new("ShaderNodeOutputMaterial")
em2  = mat2.node_tree.nodes.new("ShaderNodeEmission")
em2.inputs["Color"].default_value    = (0.0, 0.5, 1.0, 1.0)
em2.inputs["Strength"].default_value = 8.0
mat2.node_tree.links.new(em2.outputs["Emission"], out2.inputs["Surface"])
obj.data.materials.append(mat2)

mod = obj.modifiers.new("GN", "NODES")
ng  = bpy.data.node_groups.new("PointsNG", "GeometryNodeTree")
mod.node_group = ng
ng.interface.new_socket("Geometry", in_out="INPUT",  socket_type="NodeSocketGeometry")
ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
gi  = ng.nodes.new("NodeGroupInput")
go  = ng.nodes.new("NodeGroupOutput")
m2p = ng.nodes.new("GeometryNodeMeshToPoints")
m2p.mode = "VERTICES"
m2p.inputs[3].default_value = 0.3  # radius
ng.links.new(gi.outputs[0], m2p.inputs[0])
ng.links.new(m2p.outputs["Points"], go.inputs[0])

bpy.ops.object.camera_add(location=(0, 0, 8))
cam2 = bpy.context.active_object
cam2.rotation_euler = mathutils.Euler((0, 0, 0), "XYZ")
cam2.data.clip_end = 200.0
bpy.context.scene.camera = cam2

world2 = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world2
world2.use_nodes = True
world2.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0

scene.render.filepath = "renders/test/diag6b_"
bpy.ops.render.render(animation=True)
print("TEST 2 (GPU GeoNodes MeshToPoints) done → diag6b_0001.png")
