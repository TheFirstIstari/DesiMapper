"""
diag5.py - Absolute minimal Cycles render test.
Single icosphere, bright emission, camera looking at it.
If this is black, the issue is in Cycles/GPU setup, not our code.
"""
import bpy
import mathutils

# Clear default objects
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

# Single icosphere at origin
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.5, location=(0, 0, 0))
sphere = bpy.context.active_object
sphere.name = "TestSphere"

# Bright emission material
mat = bpy.data.materials.new("BrightMat")
mat.use_nodes = True
tree = mat.node_tree
tree.nodes.clear()
out = tree.nodes.new("ShaderNodeOutputMaterial")
em  = tree.nodes.new("ShaderNodeEmission")
em.inputs["Color"].default_value    = (1.0, 0.2, 0.0, 1.0)
em.inputs["Strength"].default_value = 10.0
tree.links.new(em.outputs["Emission"], out.inputs["Surface"])
sphere.data.materials.append(mat)

# Camera at Z=5, looking straight down
bpy.ops.object.camera_add(location=(0, 0, 5))
cam = bpy.context.active_object
cam.rotation_euler = mathutils.Euler((0, 0, 0), "XYZ")
cam.data.lens = 50
cam.data.clip_start = 0.01
cam.data.clip_end = 100.0
bpy.context.scene.camera = cam

print("Camera location:", cam.location[:])
print("Camera rotation:", cam.rotation_euler[:])
print("Sphere location:", sphere.location[:])

# World: pure black
world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs["Strength"].default_value = 0.0

# Render
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.cycles.device  = "CPU"   # Use CPU to eliminate GPU/Metal issues
scene.render.resolution_x = 480
scene.render.resolution_y = 270
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = "renders/test/diag5_"
scene.frame_start = 1
scene.frame_end   = 1
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma    = 1.0

print("Rendering on CPU with 16 samples...")
bpy.ops.render.render(animation=True)
print("Done. Check renders/test/diag5_0001.png")
