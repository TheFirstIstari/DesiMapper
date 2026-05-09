import bpy
import numpy as np

# In Blender 4.x, PointCloud points are sized by setting the position attribute
# The correct pattern uses foreach_set on the 'position' built-in attribute

pc = bpy.data.pointclouds.new("Test")

n = 9
positions = np.array([
    [-1, -1, 0], [0, -1, 0], [1, -1, 0],
    [-1,  0, 0], [0,  0, 0], [1,  0, 0],
    [-1,  1, 0], [0,  1, 0], [1,  1, 0],
], dtype=np.float32)

# Check if "position" attribute already exists (it does by default)
pos_attr = pc.attributes.get("position")
print("position attr exists:", pos_attr)
print("points count before:", len(pc.points))

# Try setting positions directly with foreach_set (requires points to exist first)
# In Blender 4.3, we resize via the attribute data
# The actual size is set by the number of elements we push in

# Approach: use the attribute API to set the data array
# For PointCloud, we need to first set the count
# Blender 4.3 uses bpy.ops or the C API for this, but from Python...

# Check if there's a count/resize
print("pc attributes:", [(a.name, a.data_type, a.domain) for a in pc.attributes])

# Try creating position attribute with specific count
# Actually in Blender 4.3 PointCloud, the geometry is sized via bmesh or numpy bridge
# Let's try the approach via a MESH + Geometry Nodes that outputs PointCloud

# Alternative: check if foreach_set can directly set n elements on a fresh pointcloud
try:
    pc.points.foreach_set("position", positions.ravel())
    print("foreach_set worked, count:", len(pc.points))
except Exception as e:
    print("foreach_set failed:", e)

# Alternative 2: Use the attribute domain to set n points
# In Blender 4.3 PointCloud, setting the attribute count creates points
try:
    attr = pc.attributes.new("radius", type="FLOAT", domain="POINT")
    print("After creating radius attr, points:", len(pc.points))
    radii = np.full(n, 0.1, dtype=np.float32)
    attr.data.foreach_set("value", radii)
    print("Set radii, points now:", len(pc.points))
except Exception as e:
    print("radius attr failed:", e)
