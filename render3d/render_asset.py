"""
render_asset.py — Blender headless script for rendering GLB/GLTF assets.

Called by server.py via:
    blender --background --python render_asset.py -- \\
        --glb_path /path/to/model.glb \\
        --output_path /path/to/output.png \\
        --samples 128 \\
        --resolution_x 1920 \\
        --resolution_y 1080 \\
        [--hdri_path /path/to/env.hdr]

Sets up:
    - Cycles GPU render engine (CUDA/Optix)
    - Three-point lighting (key, fill, rim)
    - HDRI environment if provided
    - Centered camera with auto-framing
    - Transparent background
"""

import argparse
import sys
import math
from pathlib import Path

import bpy


def clear_scene():
    """Remove all existing objects, meshes, lights, and cameras."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    # Remove all data blocks
    for block in bpy.data.meshes:
        bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        bpy.data.materials.remove(block)
    for block in bpy.data.textures:
        bpy.data.textures.remove(block)
    for block in bpy.data.images:
        bpy.data.images.remove(block)
    for block in bpy.data.lights:
        bpy.data.lights.remove(block)
    for block in bpy.data.cameras:
        bpy.data.cameras.remove(block)
    for block in bpy.data.worlds:
        bpy.data.worlds.remove(block)


def setup_cycles(samples: int, resolution_x: int, resolution_y: int):
    """Configure Cycles render engine with GPU acceleration."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    # Cycles settings
    cycles = scene.cycles
    cycles.samples = samples
    cycles.use_adaptive_sampling = True
    cycles.adaptive_threshold = 0.01
    cycles.max_bounces = 8
    cycles.diffuse_bounces = 4
    cycles.glossy_bounces = 4
    cycles.transmission_bounces = 4
    cycles.volume_bounces = 2
    cycles.caustics_reflective = False
    cycles.caustics_refractive = False

    # GPU compute device
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    for device in prefs.devices:
        device.use = True
        print(f"  Using device: {device.name} ({device.type})")

    scene.cycles.device = "GPU"


def setup_hdri(hdri_path: str):
    """Load an HDRI environment map for lighting."""
    world = bpy.data.worlds.new("HDRI World")
    world.use_nodes = True
    tree = world.node_tree

    # Clear existing nodes
    for node in tree.nodes:
        tree.nodes.remove(node)

    # Environment texture node
    env_tex = tree.nodes.new(type="ShaderNodeTexEnvironment")
    env_tex.image = bpy.data.images.load(hdri_path)

    # Background shader
    bg = tree.nodes.new(type="ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 1.0

    # Output
    output = tree.nodes.new(type="ShaderNodeOutputWorld")

    # Connect
    tree.links.new(env_tex.outputs["Color"], bg.inputs["Color"])
    tree.links.new(bg.outputs["Background"], output.inputs["Surface"])

    bpy.context.scene.world = world
    print(f"  Loaded HDRI: {hdri_path}")


def setup_lighting():
    """Create a three-point lighting setup."""
    # Key light (warm, strong)
    key = bpy.data.lights.new(name="Key", type="AREA")
    key.energy = 800
    key.color = (1.0, 0.95, 0.85)
    key_obj = bpy.data.objects.new(name="Key", object_data=key)
    bpy.context.collection.objects.link(key_obj)
    key_obj.location = (3.0, -3.0, 4.0)
    key_obj.rotation_euler = (math.radians(60), 0, math.radians(45))

    # Fill light (cool, softer)
    fill = bpy.data.lights.new(name="Fill", type="AREA")
    fill.energy = 300
    fill.color = (0.85, 0.90, 1.0)
    fill_obj = bpy.data.objects.new(name="Fill", object_data=fill)
    bpy.context.collection.objects.link(fill_obj)
    fill_obj.location = (-3.0, -2.0, 2.0)
    fill_obj.rotation_euler = (math.radians(30), 0, math.radians(-45))

    # Rim light (back, strong)
    rim = bpy.data.lights.new(name="Rim", type="AREA")
    rim.energy = 500
    rim.color = (1.0, 1.0, 1.0)
    rim_obj = bpy.data.objects.new(name="Rim", object_data=rim)
    bpy.context.collection.objects.link(rim_obj)
    rim_obj.location = (0.0, 4.0, 3.0)
    rim_obj.rotation_euler = (math.radians(30), 0, math.radians(180))


def import_glb(glb_path: str):
    """Import a GLB/GLTF file into the scene."""
    if not Path(glb_path).exists():
        raise FileNotFoundError(f"GLB file not found: {glb_path}")

    ext = Path(glb_path).suffix.lower()
    if ext == ".glb":
        bpy.ops.import_scene.gltf(filepath=glb_path)
    elif ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=glb_path)
    else:
        raise ValueError(f"Unsupported format: {ext}")

    print(f"  Imported: {glb_path}")


def auto_frame_camera():
    """Position camera to frame the imported object with padding."""
    # Find all mesh objects
    mesh_objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if not mesh_objects:
        print("  Warning: No mesh objects found, using default camera")
        return

    # Compute bounding box center and size
    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objects[0]

    # Get bounding box
    min_corner = [float("inf")] * 3
    max_corner = [float("-inf")] * 3
    for obj in mesh_objects:
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ mathutils.Vector(corner)
            for i in range(3):
                min_corner[i] = min(min_corner[i], world_corner[i])
                max_corner[i] = max(max_corner[i], world_corner[i])

    center = mathutils.Vector([
        (min_corner[0] + max_corner[0]) / 2,
        (min_corner[1] + max_corner[1]) / 2,
        (min_corner[2] + max_corner[2]) / 2,
    ])
    size = max(max_corner[i] - min_corner[i] for i in range(3))

    # Create camera
    cam_data = bpy.data.cameras.new("RenderCam")
    cam = bpy.data.objects.new("RenderCam", cam_data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    # Position camera at 45-degree angle with distance based on object size
    distance = size * 2.5 + 2.0
    cam.location = (
        center.x + distance * 0.7,
        center.y - distance * 0.7,
        center.z + distance * 0.5,
    )

    # Look at center
    direction = center - cam.location
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam.rotation_euler = rot_quat.to_euler()

    print(f"  Camera positioned: distance={distance:.2f}, center=({center.x:.2f}, {center.y:.2f}, {center.z:.2f})")


def render(output_path: str):
    """Render the scene to the output file."""
    bpy.context.scene.render.filepath = output_path
    print(f"  Rendering to: {output_path}")
    bpy.ops.render.render(write_still=True)
    print(f"  Render complete: {output_path}")


def main():
    """Parse arguments and run the render pipeline."""
    # We need mathutils for vector math in auto_frame_camera
    import mathutils  # noqa: F401 — used in auto_frame_camera

    parser = argparse.ArgumentParser(description="Blender GLB renderer")
    parser.add_argument("--glb_path", required=True, help="Path to GLB/GLTF file")
    parser.add_argument("--output_path", required=True, help="Output image path")
    parser.add_argument("--samples", type=int, default=128, help="Cycles samples")
    parser.add_argument("--resolution_x", type=int, default=1920, help="Output width")
    parser.add_argument("--resolution_y", type=int, default=1080, help="Output height")
    parser.add_argument("--hdri_path", default=None, help="Path to HDRI environment map")

    # Blender passes its own args before '--', so we need to skip them
    if "--" in sys.argv:
        idx = sys.argv.index("--")
        args = parser.parse_args(sys.argv[idx + 1:])
    else:
        args = parser.parse_args()

    print("=== render_asset.py ===")
    print(f"  GLB: {args.glb_path}")
    print(f"  Output: {args.output_path}")
    print(f"  Samples: {args.samples}")
    print(f"  Resolution: {args.resolution_x}x{args.resolution_y}")
    print(f"  HDRI: {args.hdri_path or 'none'}")

    # Run pipeline
    clear_scene()
    setup_cycles(args.samples, args.resolution_x, args.resolution_y)
    if args.hdri_path:
        setup_hdri(args.hdri_path)
    setup_lighting()
    import_glb(args.glb_path)
    auto_frame_camera()
    render(args.output_path)

    print("=== Done ===")


if __name__ == "__main__":
    main()
