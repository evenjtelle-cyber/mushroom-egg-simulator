"""
GenerateChoppers.py  -  Blender 4.x
"+1 Chop Mushrooms for Eggs": every chopper (weapon) after the starter axe

Weapons are SMOOTH and CARTOONY, never blocky (master brief 4d): soft
subdivided shapes with a hand-painted look baked into one texture per part,
built with the same pipeline as the Mossbark Hatchet (GenerateStarterSet.py).

  #  Chopper             Tier       Type      Look
  1  Mossbark Hatchet    Wood       Axe       (GenerateStarterSet.py)
  2  Stonebark Hatchet   Wood       Axe       knapped stone head lashed to a bent branch
  3  Fernleaf Sickle     Wood       Sickle    crescent blade with a fern frond along its spine
  4  Amethyst Chopper    Crystal    Sword     broad cleaver-sword, amethyst fuller, crystal spine
  5  Magmaseam Axe       Lava       Axe       double-bitted basalt axe split by glowing magma seams
  6  Voidglass Reaver    Void       Sword     hooked void-stone reaver, bone hilt, void orb
  7  Frostroot Cleaver   Celestial  Axe       huge ice cleaver on twisted roots, rune circle
  8  Stardust Scythe     Nebula     Scythe    star-speckled nebula crescent on a long snath
  9  Sunburst Halberd    Solar      Halberd   gilded halberd with a sun disc and flame tassels
 10  Eclipse Glaive      Astral     Glaive    twin moon blades held between two eclipse rings

Parts per chopper: <Asset>_Handle (the Tool handle) and <Asset>_Head, both
baked; <Asset>_Glow (Neon) and <Asset>_Crystal (Glass) are flat-coloured
parts for the higher tiers. Sockets: Tip, TrailTop, TrailBottom.

Output: ~/Documents/Choppers/
  Choppers.glb        every chopper side by side (Studio: ChopperKit.SetupAll)
  ChopperData.lua     stats, prices, grips and part looks; paste into ReplicatedStorage.ChopperData
  Textures/           the baked colour textures (also embedded in the GLB)
  Previews/<Asset>.png and Previews/Choppers_Lineup.png
  Choppers.blend, Choppers_Manifest.json

Run: Blender Text Editor -> Run Script (Alt+P), or
     blender --background --python GenerateChoppers.py
Baking takes a while (5-15 minutes for all nine; Blender looks frozen).
Set ONLY = ["MagmaseamAxe"] to build just one.
"""

import bpy  # noqa: I001  (bpy first: bmesh/mathutils need it loaded outside Blender's UI)
import bmesh
import json
import math
import os
import random
import traceback
from mathutils import Matrix, Vector, noise

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SET_NAME = "Choppers"
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", SET_NAME)
TEXTURE_DIR = os.path.join(OUTPUT_DIR, "Textures")
PREVIEW_DIR = os.path.join(OUTPUT_DIR, "Previews")
LOG_NAME = SET_NAME + "_Log"

ONLY = []  # e.g. ["MagmaseamAxe"]; empty = every chopper
RENDER_PREVIEWS = True
PREVIEW_SAMPLES = 24
PREVIEW_W, PREVIEW_H = 600, 900
BAKE_SIZE = 1024  # one baked colour texture per part (brief: max 1024)
BAKE_SAMPLES = 16
FACE_POSITIVE_Y = False
SEED = 31

MAX_TRIS_PER_PART = 20000

# Flat Glow/Crystal part colours, filled in while building (export_material reads them).
PALETTE = {}
GLOW_PARTS = set()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_lines = []


def log(message):
    print("[%s] %s" % (SET_NAME, message))
    _log_lines.append(message)


def flush_log():
    text = bpy.data.texts.get(LOG_NAME) or bpy.data.texts.new(LOG_NAME)
    text.clear()
    text.write("\n".join(_log_lines) + "\n")


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
def hex_to_srgb(hex_value):
    h = hex_value.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_rgba(hex_value, alpha=1.0):
    return tuple(srgb_to_linear(c) for c in hex_to_srgb(hex_value)) + (alpha,)


def basis(z_dir, y_hint):
    """Rotation matrix whose local Z = z_dir and local Y ~ y_hint."""
    z = Vector(z_dir).normalized()
    y = Vector(y_hint) - z * Vector(y_hint).dot(z)
    if y.length < 1e-5:
        y = z.orthogonal()
    y.normalize()
    x = y.cross(z)
    return Matrix((x, y, z)).transposed()


def euler_deg(x=0.0, y=0.0, z=0.0):
    return Matrix.Rotation(math.radians(z), 3, "Z") @ Matrix.Rotation(math.radians(y), 3, "Y") @ Matrix.Rotation(math.radians(x), 3, "X")


def basis_from_y(y_dir, up_hint):
    """Rotation whose local Y = y_dir, local Z as close to up_hint as possible."""
    y = Vector(y_dir).normalized()
    z = Vector(up_hint) - y * Vector(up_hint).dot(y)
    if z.length < 1e-5:
        z = y.orthogonal()
    z.normalize()
    x = y.cross(z)
    return Matrix((x, y, z)).transposed()


def bezier(p0, p1, p2, p3, n):
    p0, p1, p2, p3 = (Vector(p) for p in (p0, p1, p2, p3))
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append(p0 * u ** 3 + p1 * 3 * u * u * t + p2 * 3 * u * t * t + p3 * t ** 3)
    return out


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# Scene / material helpers
# ---------------------------------------------------------------------------
LEGACY_SCENES = ()


def purge_orphans():
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights, bpy.data.worlds):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def purge_collection(name):
    coll = bpy.data.collections.get(name)
    if coll is not None:
        for obj in list(coll.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(coll)


def work_scene():
    """The one scene the whole set is built in, with one collection per asset.

    A single scene is deliberate. Blender 4.2's glTF exporter switches the
    window to the scene it exports and can crash Blender once it has done that
    for a second scene. The script also never deletes the scene you're looking
    at, which crashes Blender too."""
    if bpy.app.background:
        return bpy.context.scene  # the stub window can't switch scenes headless
    scene = bpy.data.scenes.get(SET_NAME) or bpy.data.scenes.new(SET_NAME)
    window = bpy.context.window
    if window is not None and window.scene != scene:
        window.scene = scene
    shown = {w.scene for w in bpy.context.window_manager.windows}
    for legacy in LEGACY_SCENES:
        old = bpy.data.scenes.get(legacy)
        if old is not None and old != scene and old not in shown:
            for obj in list(old.collection.all_objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            for child in list(old.collection.children_recursive):
                bpy.data.collections.remove(child)
            bpy.data.scenes.remove(old)
    return scene


def set_collection_visible(scene, coll, visible):
    coll.hide_render = not visible
    layer = scene.view_layers[0].layer_collection.children.get(coll.name)
    if layer is not None:
        layer.hide_viewport = not visible


def make_scene(name):
    """Fresh collection `<name>_Parts` in the work scene; every other asset's
    collection is hidden so previews show one asset at a time."""
    scene = work_scene()
    purge_collection(name + "_Parts")
    purge_orphans()
    coll = bpy.data.collections.new(name + "_Parts")
    scene.collection.children.link(coll)
    for child in scene.collection.children:
        set_collection_visible(scene, child, child is coll)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.view_settings.view_transform = "Standard"
    scene.unit_settings.scale_length = 1.0
    return scene, coll


def tri_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def check_budget(objects, label):
    total = 0
    for part, obj in sorted(objects.items()):
        tris = tri_count(obj)
        total += tris
        if tris > MAX_TRIS_PER_PART:
            log("  !! %s/%s has %d tris (> %d): decimating" % (label, part, tris, MAX_TRIS_PER_PART))
            mod = obj.modifiers.new("Decimate", "DECIMATE")
            mod.ratio = MAX_TRIS_PER_PART / tris * 0.98
    log("%s: %d parts, %d tris total" % (label, len(objects), total))
    return total


def add_socket(collection, name, location):
    """Tiny tetra marker. Studio turns it into an Attachment (FrostmaneVFX.lua / StarterSet.lua)."""
    bm = bmesh.new()
    s = 0.12
    pts = [Vector((s, s, s)), Vector((-s, -s, s)), Vector((-s, s, -s)), Vector((s, -s, -s))]
    v = [bm.verts.new(Vector(location) + p) for p in pts]
    for f in ((0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)):
        bm.faces.new([v[i] for i in f])
    mesh = bpy.data.meshes.new("Socket_" + name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Socket_" + name, mesh)
    obj.hide_render = True
    obj["IsSocket"] = True
    collection.objects.link(obj)
    return obj


def export_material(part):
    """Flat material for the GLB's Glow/Crystal parts (Handle and Head keep their baked texture)."""
    name = "CX_" + part
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        color = linear_rgba(PALETTE.get(part, "#FFFFFF"))
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.3
        if part in GLOW_PARTS:
            bsdf.inputs["Emission Color"].default_value = color
            bsdf.inputs["Emission Strength"].default_value = 1.0
    return mat


def export_glb(scene, objects, filepath):
    view_layer = scene.view_layers[0]
    swapped = []
    for obj in objects:
        if obj.data.materials and not obj.get("IsSocket") and not obj.get("KeepMaterial"):
            original = obj.data.materials[0]
            obj.data.materials[0] = export_material(obj.get("PaletteKey", original.name[3:]))
            swapped.append((obj, original))
    for obj in view_layer.objects:
        obj.select_set(False, view_layer=view_layer)
    for obj in objects:
        obj.select_set(True, view_layer=view_layer)
    view_layer.objects.active = objects[0]
    rotated = []
    if FACE_POSITIVE_Y:
        for obj in objects:
            obj.matrix_world = Matrix.Rotation(math.pi, 4, "Z") @ obj.matrix_world
            rotated.append(obj)
    with bpy.context.temp_override(scene=scene, view_layer=view_layer, active_object=objects[0],
                                   selected_objects=objects):
        bpy.ops.export_scene.gltf(
            filepath=filepath,
            export_format="GLB",
            use_selection=True,
            export_apply=True,
            export_yup=True,
            export_materials="EXPORT",
            export_texcoords=True,
            export_normals=True,
        )
    for obj in rotated:
        obj.matrix_world = Matrix.Rotation(-math.pi, 4, "Z") @ obj.matrix_world
    for obj, original in swapped:
        obj.data.materials[0] = original
    log("Exported %s (%d objects)" % (filepath, len(objects)))


def setup_preview(scene, coll, target, distance, height, angle_deg, lens=50, ground=True, size=(1100, 820), background="#BFE3FF"):
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.cycles.samples = PREVIEW_SAMPLES
    scene.cycles.use_denoising = True
    # Stacked translucent ice tiles need deep transparency/transmission paths,
    # otherwise overlaps render black.
    scene.cycles.transparent_max_bounces = 64
    scene.cycles.transmission_bounces = 32
    scene.cycles.max_bounces = 32
    scene.render.film_transparent = False
    world_name = coll.name.replace("_Parts", "") + "_World"
    world = bpy.data.worlds.get(world_name) or bpy.data.worlds.new(world_name)
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = linear_rgba(background)
    bg.inputs["Strength"].default_value = 0.9
    scene.world = world

    sun_data = bpy.data.lights.new(coll.name.replace("_Parts", "") + "_Sun", "SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(8)
    sun = bpy.data.objects.new(coll.name.replace("_Parts", "") + "_Sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(-12), math.radians(-35))
    coll.objects.link(sun)

    if ground:
        bm = bmesh.new()
        bm.loops.layers.uv.new("UVMap")
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=60)
        uv = bm.loops.layers.uv.active
        for face in bm.faces:
            for loop in face.loops:
                loop[uv].uv = (loop.vert.co.x, loop.vert.co.y)
        mesh = bpy.data.meshes.new(coll.name.replace("_Parts", "") + "_Ground")
        bm.to_mesh(mesh)
        bm.free()
        ground_obj = bpy.data.objects.new(coll.name.replace("_Parts", "") + "_Ground", mesh)
        ground_obj.data.materials.append(flat_material("PreviewGrass", "#5FC23A", "Plastic"))
        coll.objects.link(ground_obj)

    cam_data = bpy.data.cameras.new(coll.name.replace("_Parts", "") + "_Cam")
    cam_data.lens = lens
    cam = bpy.data.objects.new(coll.name.replace("_Parts", "") + "_Cam", cam_data)
    a = math.radians(angle_deg)
    target = Vector(target)
    cam.location = target + Vector((math.sin(a) * distance, -math.cos(a) * distance, height))
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    coll.objects.link(cam)
    scene.camera = cam
    return cam


def render_preview(scene, filename):
    if not RENDER_PREVIEWS:
        return
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    scene.render.filepath = os.path.join(PREVIEW_DIR, filename)
    scene.render.image_settings.file_format = "PNG"
    with bpy.context.temp_override(scene=scene):
        bpy.ops.render.render(write_still=True, scene=scene.name)
    log("Rendered preview %s" % filename)


def orbit_camera(scene, target, distance, height, angle_deg):
    cam = scene.camera
    a = math.radians(angle_deg)
    target = Vector(target)
    cam.location = target + Vector((math.sin(a) * distance, -math.cos(a) * distance, height))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()


def save_rgba(name, rgba):
    """rgba: numpy float array (h, w, 4), row 0 = TOP of the image."""
    import numpy as np
    h, w = rgba.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.colorspace_settings.name = "sRGB"
    flipped = np.ascontiguousarray(rgba[::-1].astype(np.float32))  # Blender stores bottom row first
    img.pixels.foreach_set(flipped.ravel())
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    path = os.path.join(TEXTURE_DIR, name + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return path


# ---------------------------------------------------------------------------
# Smooth weapon pipeline (shared with GenerateStarterSet.py)
# ---------------------------------------------------------------------------
# Mask channels tell the paint shader which procedural detail to add:
# R = hammered steel, G = wood grain, B = leather, A = brass.
M_STEEL, M_WOOD, M_LEATHER, M_BRASS = (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)


class SmoothBuilder:
    """Organic geometry for hero assets: tubes along curves, a Coons-patch
    blade, spheres. Every face corner carries a painted base colour ("Col")
    and a detail mask ("Mask") for the bake shader."""

    def __init__(self):
        self.bm = bmesh.new()
        self.col = self.bm.loops.layers.float_color.new("Col")
        self.mask = self.bm.loops.layers.float_color.new("Mask")

    def paint(self, face, color, mask):
        for loop in face.loops:
            loop[self.col] = color
            loop[self.mask] = mask

    def tube(self, points, radii, sides=14, color=None, mask=M_WOOD, cap_start=True, cap_end=True,
             closed=False, ups=None, aspect=None, color_fn=None):
        """Generalised tube. radii[i] is a float or a function(angle)->radius
        (lets wood bulge). `ups` gives per-point cross-section orientation
        (for ribbons), `aspect` per-point (x_scale, y_scale)."""
        n = len(points)
        pts = [Vector(p) for p in points]
        tangents = []
        for i in range(n):
            if closed:
                t = pts[(i + 1) % n] - pts[i - 1]
            else:
                t = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]
            tangents.append(t.normalized())
        # Parallel-transport frames so the cross-section never twists.
        normal = tangents[0].orthogonal().normalized()
        rings = []
        for i in range(n):
            t = tangents[i]
            if ups is not None:
                normal = Vector(ups[i])
            normal = (normal - t * normal.dot(t)).normalized()
            binormal = t.cross(normal)
            sx, sy = aspect[i] if aspect is not None else (1.0, 1.0)
            ring = []
            for j in range(sides):
                a = 2 * math.pi * j / sides
                r = radii[i](a) if callable(radii[i]) else radii[i]
                offset = normal * (math.cos(a) * r * sx) + binormal * (math.sin(a) * r * sy)
                ring.append(self.bm.verts.new(pts[i] + offset))
            rings.append(ring)
        last = n if closed else n - 1
        for i in range(last):
            a_ring, b_ring = rings[i], rings[(i + 1) % n]
            for j in range(sides):
                k = (j + 1) % sides
                face = self.bm.faces.new((a_ring[j], a_ring[k], b_ring[k], b_ring[j]))
                c = color_fn(i / max(1, n - 1), j / sides) if color_fn else color
                self.paint(face, linear_rgba(c), mask)
        if not closed:
            for ring, flip in ((rings[0], True), (rings[-1], False)):
                if (flip and not cap_start) or (not flip and not cap_end):
                    continue
                centre = self.bm.verts.new(sum((v.co for v in ring), Vector()) / sides)
                for j in range(sides):
                    k = (j + 1) % sides
                    tri = (centre, ring[k], ring[j]) if flip else (centre, ring[j], ring[k])
                    face = self.bm.faces.new(tri)
                    c = color_fn(0.0 if flip else 1.0, j / sides) if color_fn else color
                    self.paint(face, linear_rgba(c), mask)

    def sphere(self, centre, radius, color, mask, scale=(1, 1, 1), segments=(10, 7)):
        result = bmesh.ops.create_uvsphere(self.bm, u_segments=segments[0], v_segments=segments[1], radius=radius,
                                           matrix=Matrix.Translation(centre) @ Matrix.Diagonal((*scale, 1.0)))
        faces = {f for v in result["verts"] for f in v.link_faces}
        for face in faces:
            self.paint(face, linear_rgba(color), mask)

    def to_object(self, collection, name):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts[:], dist=1e-5)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        return obj


def mix_hex(a, b, t):
    ca, cb = hex_to_srgb(a), hex_to_srgb(b)
    t = min(max(t, 0.0), 1.0)
    return "#%02X%02X%02X" % tuple(int(round((x + (y - x) * t) * 255)) for x, y in zip(ca, cb))


def wood_radius(base, z, seed):
    """Wood haft radius with gentle knots and an oval cross-section."""
    def fn(a):
        bump = 0.012 * noise.noise(Vector((math.cos(a) * 2, math.sin(a) * 2, z * 3.0 + seed)))
        knot = 0.03 * math.exp(-((z - 2.35) / 0.08) ** 2) * max(0.0, math.cos(a - 0.6)) ** 4
        return base * (1.0 + 0.07 * math.cos(2 * a)) + bump + knot
    return fn


def paint_material(name):
    """Hand-painted look: painted vertex colours x procedural detail (hammered
    steel facets, wood grain streaks, leather grain, brass speckle) x ambient
    occlusion x a bright rim on convex edges. Baked to a texture afterwards."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes.get("Principled BSDF")

    def node(kind, **props):
        n = nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def math_node(op, a=None, b=None, clamp=False):
        n = node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for idx, v in ((0, a), (1, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[idx].default_value = v
            else:
                links.new(v, n.inputs[idx])
        return n.outputs[0]

    def remap(value, a, b, c, d):
        n = node("ShaderNodeMapRange", clamp=True)
        links.new(value, n.inputs["Value"])
        n.inputs["From Min"].default_value, n.inputs["From Max"].default_value = a, b
        n.inputs["To Min"].default_value, n.inputs["To Max"].default_value = c, d
        return n.outputs["Result"]

    col = node("ShaderNodeVertexColor", layer_name="Col")
    mask = node("ShaderNodeVertexColor", layer_name="Mask")
    sep = node("ShaderNodeSeparateColor")
    links.new(mask.outputs["Color"], sep.inputs["Color"])
    coord = node("ShaderNodeTexCoord")

    # Hammered steel: broad soft dents (darker dent centres, lighter ridges
    # between them) with a gentle per-dent tone shift.
    vor_cells = node("ShaderNodeTexVoronoi", feature="F1")
    vor_cells.inputs["Scale"].default_value = 3.2
    links.new(coord.outputs["Object"], vor_cells.inputs["Vector"])
    vor_edge = node("ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE")
    vor_edge.inputs["Scale"].default_value = 3.2
    links.new(coord.outputs["Object"], vor_edge.inputs["Vector"])
    cell_tone = node("ShaderNodeRGBToBW")
    links.new(vor_cells.outputs["Color"], cell_tone.inputs["Color"])
    dents = math_node("MULTIPLY", remap(vor_cells.outputs["Distance"], 0.0, 0.45, 0.9, 1.05),
                      remap(vor_edge.outputs["Distance"], 0.0, 0.05, 1.08, 1.0))
    steel_f = math_node("MULTIPLY", dents, remap(cell_tone.outputs["Val"], 0.0, 1.0, 0.95, 1.05))

    # Wood: long grain streaks along the haft (object Z).
    mapping = node("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (16.0, 16.0, 1.3)
    links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    grain = node("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 3.0
    grain.inputs["Detail"].default_value = 6.0
    links.new(mapping.outputs["Vector"], grain.inputs["Vector"])
    wood_f = remap(grain.outputs["Fac"], 0.3, 0.7, 0.76, 1.12)

    leather_n = node("ShaderNodeTexNoise")
    leather_n.inputs["Scale"].default_value = 40.0
    links.new(coord.outputs["Object"], leather_n.inputs["Vector"])
    leather_f = remap(leather_n.outputs["Fac"], 0.3, 0.7, 0.88, 1.06)

    brass_n = node("ShaderNodeTexNoise")
    brass_n.inputs["Scale"].default_value = 25.0
    links.new(coord.outputs["Object"], brass_n.inputs["Vector"])
    brass_f = remap(brass_n.outputs["Fac"], 0.3, 0.7, 0.9, 1.08)

    # detail = 1 + R*(steel-1) + G*(wood-1) + B*(leather-1) + A*(brass-1)
    def weighted(channel, factor):
        return math_node("MULTIPLY", channel, math_node("SUBTRACT", factor, 1.0))

    alpha = node("ShaderNodeAttribute", attribute_name="Mask", attribute_type="GEOMETRY")
    detail = math_node("ADD", 1.0, weighted(sep.outputs["Red"], steel_f))
    detail = math_node("ADD", detail, weighted(sep.outputs["Green"], wood_f))
    detail = math_node("ADD", detail, weighted(sep.outputs["Blue"], leather_f))
    detail = math_node("ADD", detail, weighted(alpha.outputs["Alpha"], brass_f))

    ao = node("ShaderNodeAmbientOcclusion", samples=16)
    ao.inputs["Distance"].default_value = 0.25
    ao_f = remap(ao.outputs["AO"], 0.0, 1.0, 0.62, 1.0)
    geo = node("ShaderNodeNewGeometry")
    rim_f = remap(geo.outputs["Pointiness"], 0.5, 0.58, 1.0, 1.22)

    scale = math_node("MULTIPLY", math_node("MULTIPLY", detail, ao_f), rim_f)
    shade = node("ShaderNodeVectorMath", operation="SCALE")
    links.new(col.outputs["Color"], shade.inputs[0])
    links.new(scale, shade.inputs["Scale"])
    links.new(shade.outputs["Vector"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.6
    return mat


def smooth_and_bake(scene, obj, texture_name):
    """Subdivide (applied), Smart UV Project, bake the painted colour into a
    BAKE_SIZE texture, then swap to a plain textured material and drop the
    vertex colours (brief 6.2)."""
    view_layer = scene.view_layers[0]
    sub = obj.modifiers.new("Subdivision", "SUBSURF")
    sub.levels = sub.render_levels = 1  # base meshes are dense enough; keeps each part well under 20k tris
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    new_mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
    old_mesh = obj.data
    obj.modifiers.clear()
    obj.data = new_mesh
    bpy.data.meshes.remove(old_mesh)
    new_mesh.name = obj.name

    for o in view_layer.objects:
        o.select_set(False, view_layer=view_layer)
    obj.select_set(True, view_layer=view_layer)
    view_layer.objects.active = obj
    override = dict(scene=scene, view_layer=view_layer, active_object=obj, object=obj,
                    selected_objects=[obj], selected_editable_objects=[obj])
    with bpy.context.temp_override(**override):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.012)
        bpy.ops.object.mode_set(mode="OBJECT")

    paint = paint_material(texture_name + "_Paint")
    obj.data.materials.clear()
    obj.data.materials.append(paint)
    old = bpy.data.images.get(texture_name)
    if old is not None:  # from a previous run; keeps the name free of ".001"
        bpy.data.images.remove(old)
    image = bpy.data.images.new(texture_name, BAKE_SIZE, BAKE_SIZE, alpha=False)
    target = paint.node_tree.nodes.new("ShaderNodeTexImage")
    target.image = image
    paint.node_tree.nodes.active = target

    scene.render.engine = "CYCLES"
    scene.cycles.samples = BAKE_SAMPLES
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.margin = 8
    with bpy.context.temp_override(**override):
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=8, use_clear=True)
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    image.filepath_raw = os.path.join(TEXTURE_DIR, texture_name + ".png")
    image.file_format = "PNG"
    image.save()

    final = bpy.data.materials.new(texture_name)
    final.use_nodes = True
    bsdf = final.node_tree.nodes.get("Principled BSDF")
    tex = final.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    final.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.55 if "Head" in texture_name else 0.7
    obj.data.materials.clear()
    obj.data.materials.append(final)
    bpy.data.materials.remove(paint)
    # Remove by name: attribute references go stale after each removal, and
    # removing through a stale one can delete the UV map instead.
    for name in [a.name for a in obj.data.color_attributes]:
        obj.data.color_attributes.remove(obj.data.color_attributes[name])
    assert obj.data.uv_layers, "UV map lost while cleaning up vertex colours"
    obj["KeepMaterial"] = True
    log("Baked %s (%d tris) -> %s.png" % (obj.name, tri_count(obj), texture_name))



# ---------------------------------------------------------------------------
# Chopper construction kit
# ---------------------------------------------------------------------------
M_NONE = (0, 0, 0, 0)


def v2(y, z):
    return Vector((y, z))


def quad(p0, p1, p2, t):
    return p0 * (1 - t) ** 2 + p1 * 2 * (1 - t) * t + p2 * t * t


def coons(top, bottom, socket, edge):
    """Mid-surface P(s, r) of an axe-style blade from four boundary curves in
    the YZ plane: top(r) and bottom(r) run socket -> edge, socket(s) and
    edge(s) run top -> bottom."""
    t0, t1, b0, b1 = top(0.0), top(1.0), bottom(0.0), bottom(1.0)

    def P(s, r):
        return (top(r) * (1 - s) + bottom(r) * s + socket(s) * (1 - r) + edge(s) * r
                - (t0 * (1 - s) * (1 - r) + t1 * (1 - s) * r + b0 * s * (1 - r) + b1 * s * r))
    return P


def curved_strip(centre, width_spine, width_edge, edge_inside=False):
    """Mid-surface for curved blades (sickles, scythes, reavers): `centre(s)`
    is the blade's centreline, r runs from the spine (0) to the edge (1). The
    edge is on the outside of the curve (scimitar) unless edge_inside (sickle, scythe)."""
    def P(s, r):
        a, b = centre(max(0.0, s - 0.01)), centre(min(1.0, s + 0.01))
        d = (b - a).normalized()
        n = v2(-d.y, d.x)  # left of the direction of travel
        if edge_inside:
            n = -n
        c = centre(s)
        spine = c + n * width_spine(s)
        edge = c - n * width_edge(s)
        return spine.lerp(edge, r)
    return P


class Blade:
    """A solid blade: mid-surface P(s, r) -> (y, z), half thickness along X
    and a painted colour, optionally mirrored to -Y / moved by `xform`."""

    def __init__(self, P, half_t, color, mask=None, ns=18, nr=10, mirror_y=False, xform=None):
        self.P, self.half_t, self.color = P, half_t, color
        self.mask = mask if mask is not None else (1, 0, 0, 0)
        self.ns, self.nr = ns, nr
        self.mirror_y = mirror_y
        self.xform = xform if xform is not None else Matrix.Identity(4)

    def point(self, s, r, side=0, lift=0.0):
        """World point on the blade: side=+1/-1 for the two faces, 0 for the mid-surface."""
        p = self.P(s, r)
        y = -p.x if self.mirror_y else p.x
        x = side * (self.half_t(s, r) + lift)
        return self.xform @ Vector((x, y, p.y))

    def build(self, sb):
        ns, nr = self.ns, self.nr
        grid = {}
        for side in (1, -1):
            for i in range(ns + 1):
                for j in range(nr + 1):
                    grid[(side, i, j)] = sb.bm.verts.new(self.point(i / ns, j / nr, side))

        def paint(face, s, r):
            sb.paint(face, linear_rgba(self.color(s, r)), self.mask)

        for side in (1, -1):
            for i in range(ns):
                for j in range(nr):
                    q = [grid[(side, i, j)], grid[(side, i, j + 1)], grid[(side, i + 1, j + 1)], grid[(side, i + 1, j)]]
                    paint(sb.bm.faces.new(q if side > 0 else list(reversed(q))), (i + 0.5) / ns, (j + 0.5) / nr)
        for i in range(ns):
            for j_fixed in (0, nr):
                a, b = grid[(1, i, j_fixed)], grid[(1, i + 1, j_fixed)]
                c, d = grid[(-1, i + 1, j_fixed)], grid[(-1, i, j_fixed)]
                paint(sb.bm.faces.new((a, d, c, b) if j_fixed == 0 else (a, b, c, d)), (i + 0.5) / ns, j_fixed / nr)
        for j in range(nr):
            for i_fixed in (0, ns):
                a, b = grid[(1, i_fixed, j)], grid[(1, i_fixed, j + 1)]
                c, d = grid[(-1, i_fixed, j + 1)], grid[(-1, i_fixed, j)]
                paint(sb.bm.faces.new((a, b, c, d) if i_fixed == 0 else (a, d, c, b)), i_fixed / ns, (j + 0.5) / nr)
        return self


def taper(t0, t1, power=0.85, floor=0.018):
    """Half thickness: t0 at the spine/socket (r=0) thinning to t1 at the edge."""
    return lambda s, r: (t0 - t1) * (1 - r) ** power + t1 + floor


def edge_ramp(dark, mid, edge, start=0.82):
    """Steel-style colour across the blade: dark -> mid, then a bright sharpened edge."""
    def fn(s, r):
        if r > start:
            return mix_hex(mid, edge, (r - start) / (1 - start))
        return mix_hex(dark, mid, r / start)
    return fn


def crystal(sb, base, direction, length, radius, color):
    """Faceted crystal: hex prism with a pointed tip (built into a flat-shaded Glass part)."""
    d = Vector(direction).normalized()
    b = Vector(base)
    sb.tube([b, b + d * length * 0.68, b + d * length], [radius, radius * 1.08, 0.004], sides=6, color=color, mask=M_NONE)


def ring_tube(sb, centre, radius, thickness, normal, color, mask=M_NONE, sides=8, count=24):
    n = Vector(normal).normalized()
    u = n.orthogonal().normalized()
    v = n.cross(u)
    pts = [Vector(centre) + (u * math.cos(2 * math.pi * k / count) + v * math.sin(2 * math.pi * k / count)) * radius
           for k in range(count)]
    sb.tube(pts, [thickness] * count, sides=sides, closed=True, color=color, mask=mask)


def collar(sb, z0, z1, radius, color, mask, rim=None, y=0.0):
    sb.tube([Vector((0, y, z0)), Vector((0, y, z0 + 0.03)), Vector((0, y, z1 - 0.03)), Vector((0, y, z1))],
            [radius * 0.92, radius, radius, radius * 0.92], sides=16, color=color, mask=mask)
    if rim:
        for z in (z0 + 0.02, z1 - 0.02):
            sb.tube([Vector((0, y, z - 0.03)), Vector((0, y, z + 0.03))], [radius * 1.06] * 2, sides=16, color=rim, mask=mask)


def wraps(sb, z0, z1, radius, colors, mask, turns=2.4, width=0.09, crossed=True, centre=lambda z: Vector((0, 0))):
    """Crossed leather (or cloth/rope) wraps around a straight-ish haft."""
    for k, hand in enumerate((1, -1) if crossed else (1,)):
        pts, ups, aspect = [], [], []
        steps = int(13 * turns)
        for i in range(steps + 1):
            u = i / steps
            z = lerp(z0, z1, u)
            c = centre(z)
            a = hand * u * turns * 2 * math.pi
            radial = Vector((math.cos(a), math.sin(a), 0))
            pts.append(Vector((c.x, c.y, z)) + radial * radius)
            ups.append(radial)
            aspect.append((0.3, 1.0))
        sb.tube(pts, [width] * len(pts), sides=6, ups=ups, aspect=aspect, color=colors[k % len(colors)], mask=mask)


def leaf_blob(sb, base, direction, length, width, color, mask=M_NONE):
    d = Vector(direction).normalized()
    sb.tube([Vector(base), Vector(base) + d * length * 0.45, Vector(base) + d * length],
            [width * 0.25, width, 0.01], sides=8, color=color, mask=mask, aspect=[(1.0, 0.25)] * 3)


def staff(sb, z0, z1, radius, color_fn, mask, bend=0.0, sides=14, n=24):
    """Long straight-ish pole (scythe snath, halberd shaft). bend pushes the middle along -Y."""
    pts = [Vector((0, -bend * math.sin(math.pi * i / n), lerp(z0, z1, i / n))) for i in range(n + 1)]
    sb.tube(pts, [radius] * len(pts), sides=sides, mask=mask, color_fn=color_fn)
    return pts


class Chopper:
    """Builders for one chopper's parts. Handle and Head are smooth, painted and
    baked; Glow (Neon) and Crystal (Glass) are flat-coloured parts."""

    def __init__(self, spec):
        self.spec = spec
        self.handle = SmoothBuilder()
        self.head = SmoothBuilder()
        self.glow = SmoothBuilder()
        self.crystal = SmoothBuilder()
        self.rng = random.Random(SEED + sum(map(ord, spec["asset"])))
        self.sockets = {}

    def socket(self, name, p):
        self.sockets[name] = Vector(p)

    def trail(self, top, bottom, tip):
        self.socket("TrailTop", top)
        self.socket("TrailBottom", bottom)
        self.socket("Tip", tip)


# ---------------------------------------------------------------------------
# The choppers (blade faces -Y, handle along +Z, bottom of the handle at z=0)
# ---------------------------------------------------------------------------
def stonebark_hatchet(c):
    """Wood tier: a knapped stone head lashed with rope to a bent branch."""
    STONE = ("#55504B", "#837C73", "#C9C2B6")
    BARK, BARK_LIGHT = "#5B3A22", "#8A5C36"
    ROPE, ROPE_DARK = "#C9A66B", "#9C7C48"
    LEAF, LEAF_DARK = "#7CC242", "#4F8A2E"
    path = bezier((0, 0.05, 0.1), (0, 0.18, 1.5), (0, -0.12, 2.9), (0, 0.0, 4.35), 28)

    def centre(z):
        p = min(path, key=lambda q: abs(q.z - z))
        return Vector((p.x, p.y))

    radii = [wood_radius(0.15 + 0.03 * math.exp(-((p.z - 0.3) / 0.3) ** 2), p.z, 1.7) for p in path]
    c.handle.tube(path, radii, sides=14, mask=M_WOOD,
                  color_fn=lambda t, a: mix_hex(BARK, BARK_LIGHT, 0.5 + 0.5 * math.sin(a * 5 + t * 23)))
    c.handle.sphere(Vector((0, 0.05, 0.08)), 0.19, BARK, M_WOOD, scale=(1, 1, 0.8))
    # A snapped-off twig with two leaves.
    twig = [Vector((0, 0.16, 1.95)), Vector((0, 0.38, 2.15)), Vector((0, 0.5, 2.38))]
    c.handle.tube(twig, [0.07, 0.05, 0.035], sides=8, color=BARK_LIGHT, mask=M_WOOD)
    leaf_blob(c.handle, twig[-1], (0.2, 0.5, 0.7), 0.42, 0.16, LEAF)
    leaf_blob(c.handle, twig[-1], (-0.25, 0.7, 0.2), 0.36, 0.14, LEAF_DARK)
    wraps(c.handle, 0.7, 1.75, 0.165, (ROPE, ROPE_DARK), M_LEATHER, turns=3.0, width=0.08, centre=centre)

    def socket(s):
        return v2(-0.12, 4.35).lerp(v2(-0.12, 3.35), s)

    def edge(s):
        p = quad(v2(-1.05, 4.75), v2(-1.95, 3.9), v2(-1.0, 2.85), s)
        p.x += 0.07 * abs(math.sin(s * math.pi * 6))  # knapped scallops
        return p

    def stone(s, r):
        # Knapped flakes: patches of lighter and darker stone, a pale worked edge.
        flake = math.sin(s * 17 + r * 6) + math.sin(s * 5 - r * 13 + 1.3)
        base = mix_hex(STONE[0], STONE[1], 0.5 + 0.25 * flake)
        return mix_hex(base, STONE[2], max(0.0, (r - 0.78) / 0.22))

    blade = Blade(coons(lambda r: v2(-0.12, 4.35).lerp(v2(-1.05, 4.75), r) + v2(0, 0.08 * math.sin(math.pi * r)),
                        lambda r: quad(v2(-0.12, 3.35), v2(-0.45, 3.1), v2(-1.0, 2.85), r), socket, edge),
                  taper(0.26, 0.04, 0.6), stone, mask=(1, 0, 0, 0), ns=20, nr=12).build(c.head)
    c.head.sphere(Vector((0, 0.32, 3.9)), 0.3, STONE[0], (1, 0, 0, 0), scale=(0.85, 1.1, 1.25))
    wraps(c.head, 3.3, 4.4, 0.22, (ROPE, ROPE_DARK), M_LEATHER, turns=2.6, width=0.1, centre=centre)
    for k in range(5):
        a = k * 1.3
        c.head.sphere(Vector((0.2 * math.cos(a), 0.2 * math.sin(a), 4.32 + 0.04 * (k % 2))), 0.09 + 0.02 * (k % 3),
                      LEAF_DARK if k % 2 else LEAF, M_NONE)
    leaf_blob(c.head, Vector((0, 0.1, 4.4)), (0.1, 0.4, 1.0), 0.5, 0.18, LEAF)
    c.trail(blade.point(0, 1), blade.point(1, 1), blade.point(0.5, 0.97))


def fernleaf_sickle(c):
    """Wood tier: a crescent sickle with a fern frond curling along its spine."""
    WOOD = ("#6B3E1F", "#9A5A2C")
    LEATHER, LEATHER_DARK = "#4E9A3A", "#356F28"
    BRASS, BRASS_DARK = "#B9822B", "#7A4E18"
    FERN, FERN_LIGHT = "#3E8E3A", "#7CC242"
    c.handle.tube([Vector((0, 0, 0.15)), Vector((0, 0.02, 1.0)), Vector((0, 0, 1.85))], [0.15, 0.14, 0.13], sides=14,
                  mask=M_WOOD, color_fn=lambda t, a: mix_hex(WOOD[0], WOOD[1], 0.5 + 0.5 * math.sin(a * 2 + t * 11)))
    wraps(c.handle, 0.45, 1.55, 0.15, (LEATHER, LEATHER_DARK), M_LEATHER, turns=2.4)
    c.handle.sphere(Vector((0, 0, 0.12)), 0.2, BRASS, M_BRASS, scale=(1, 1, 0.9))
    c.handle.tube([Vector((0, 0, -0.02)), Vector((0, 0, -0.16)), Vector((0, 0, -0.26))], [0.12, 0.08, 0.01], sides=10,
                  color=BRASS_DARK, mask=M_BRASS)
    collar(c.head, 1.82, 2.05, 0.17, BRASS, M_BRASS, rim=BRASS_DARK)

    centre_c, radius = v2(-0.95, 2.55), 1.15
    a0 = math.atan2(2.02 - 2.55, 0.0 + 0.95)
    a1 = math.radians(205)

    def centre(s):
        a = lerp(a0, a1, s)
        return centre_c + v2(math.cos(a), math.sin(a)) * radius

    blade = Blade(curved_strip(centre, lambda s: 0.06 * (1 - s) + 0.01, lambda s: 0.36 * (1 - s) ** 0.7 + 0.02,
                               edge_inside=True),
                  taper(0.09, 0.012, 0.8),
                  lambda s, r: mix_hex("#5E7A55", "#C8D3CF", r / 0.8) if r < 0.8 else mix_hex("#C8D3CF", "#F2F7F4", (r - 0.8) / 0.2),
                  ns=24, nr=8).build(c.head)
    # Fern frond: leaflets along the spine, shrinking to the tip.
    for k in range(13):
        s = 0.04 + k * 0.065
        base = blade.point(s, 0.0)
        out = (blade.point(s, 0.0) - blade.point(s, 0.3)).normalized()
        for side in (1, -1):
            leaf_blob(c.head, base + Vector((side * 0.04, 0, 0)), out + Vector((side * 0.35, 0, 0)),
                      0.46 * (1 - s * 0.55), 0.15 * (1 - s * 0.45), FERN_LIGHT if (k + side) % 2 else FERN)
    for k in (0.1, 0.22):
        for side in (1, -1):
            c.head.sphere(blade.point(k, 0.35, side, 0.01), 0.05, BRASS, M_BRASS, scale=(0.5, 1, 1))
    c.trail(blade.point(0.15, 1), blade.point(0.95, 1), blade.point(0.55, 1))


def amethyst_chopper(c):
    """Crystal tier: a broad cleaver-sword with an inlaid amethyst fuller and
    crystals growing out of its spine."""
    BIRCH, GOLD, GOLD_DARK = "#E8E2D4", "#E2B84A", "#9C7424"
    LILAC, DEEP = "#C9B3FF", "#7B5CD6"
    CRYSTAL = c.spec["crystal"]
    c.handle.tube([Vector((0, 0, 0.18)), Vector((0, 0, 0.7)), Vector((0, 0, 1.3))], [0.14, 0.15, 0.14], sides=14,
                  color=BIRCH, mask=M_LEATHER)
    wraps(c.handle, 0.25, 1.25, 0.145, (LILAC, DEEP), M_LEATHER, turns=2.2, width=0.08)
    c.handle.tube([Vector((0, 0, 0.0)), Vector((0, 0, 0.1)), Vector((0, 0, 0.22))], [0.16, 0.22, 0.17], sides=16,
                  color=GOLD, mask=M_BRASS)
    crystal(c.crystal, Vector((0, 0, 0.05)), (0, 0, -1), 0.42, 0.13, CRYSTAL)
    guard = bezier((0, 0.62, 1.58), (0, 0.3, 1.36), (0, -0.4, 1.36), (0, -0.82, 1.6), 14)
    c.head.tube(guard, [0.12] * len(guard), sides=12, color=GOLD, mask=M_BRASS)
    c.head.sphere(Vector((0, -0.08, 1.42)), 0.24, GOLD_DARK, M_BRASS, scale=(0.9, 1.4, 0.7))
    for end in (guard[0], guard[-1]):
        crystal(c.crystal, end, (0, end.y * 0.6, 1), 0.36, 0.09, CRYSTAL)

    def P(s, r):
        z0, ztop = 1.48, 4.75 + 0.45 * r ** 1.3
        spine, edge = 0.34 - 0.04 * math.sin(math.pi * s), -0.6 - 0.2 * s
        return v2(lerp(spine, edge, r), lerp(z0, ztop, s))

    def color(s, r):
        if 0.1 < r < 0.32 and s < 0.85:
            return DEEP if 0.14 < r < 0.28 else LILAC  # inlaid amethyst fuller
        return edge_ramp("#8C93A3", "#C7CCDA", "#F6F2FF", 0.84)(s, r)

    blade = Blade(P, lambda s, r: (0.15 * (1 - r) ** 0.9 + 0.018) * (1 - 0.25 * s), color, ns=20, nr=12).build(c.head)
    for k, s in enumerate((0.12, 0.3, 0.5, 0.68)):
        crystal(c.crystal, blade.point(s, 0.0) + Vector((0, -0.05, 0)), (0, 1, 0.55), 0.55 - k * 0.08, 0.13 - k * 0.015,
                CRYSTAL)
    c.trail(blade.point(1, 1), blade.point(0.1, 1), blade.point(0.75, 1))


def magmaseam_axe(c):
    """Lava tier: a double-bitted basalt battle axe split by glowing magma seams."""
    BASALT, CHAR, ASH, EMBER = "#2B2422", "#4A3A33", "#7A6E68", "#C2461B"
    WRAP, WRAP_DARK = "#C2461B", "#7A2E10"
    GLOW = c.spec["glow"]
    c.handle.tube([Vector((0, 0, 0.0)), Vector((0, 0, 2.5)), Vector((0, 0, 5.0))], [0.16, 0.15, 0.17], sides=14,
                  mask=(1, 0, 0, 0), color_fn=lambda t, a: mix_hex(BASALT, CHAR, 0.5 + 0.5 * math.sin(a * 3 + t * 17)))
    wraps(c.handle, 1.1, 2.6, 0.165, (WRAP, WRAP_DARK), M_LEATHER, turns=3.0)
    collar(c.handle, 0.0, 0.35, 0.21, ASH, (1, 0, 0, 0), rim=CHAR)
    c.handle.tube([Vector((0, 0, 0.02)), Vector((0, 0, -0.25)), Vector((0, 0, -0.5))], [0.16, 0.1, 0.01], sides=8,
                  color=CHAR, mask=(1, 0, 0, 0))
    collar(c.head, 3.95, 5.0, 0.3, CHAR, (1, 0, 0, 0), rim=ASH)
    c.head.tube([Vector((0, 0, 4.98)), Vector((0, 0, 5.3)), Vector((0, 0, 5.75))], [0.2, 0.13, 0.01], sides=8, color=BASALT,
                mask=(1, 0, 0, 0))
    ring_tube(c.glow, (0, 0, 4.47), 0.31, 0.05, (0, 0, 1), GLOW)

    surface = coons(lambda r: v2(-0.22, 4.95).lerp(v2(-1.3, 5.6), r) + v2(0, 0.1 * math.sin(math.pi * r)),
                    lambda r: quad(v2(-0.22, 4.0), v2(-0.6, 3.75), v2(-1.3, 3.3), r),
                    lambda q: v2(-0.22, 4.95).lerp(v2(-0.22, 4.0), q),
                    lambda q: quad(v2(-1.3, 5.6), v2(-1.95, 4.45), v2(-1.3, 3.3), q))
    blades = [Blade(surface, taper(0.2, 0.03, 0.8), edge_ramp(BASALT, CHAR, EMBER, 0.8), mirror_y=m).build(c.head)
              for m in (False, True)]
    # Magma seams on both faces of both bits, plus a glowing rim along each edge.
    for blade in blades:
        for side in (1, -1):
            for k in range(3):
                s0 = 0.2 + 0.3 * k + c.rng.uniform(-0.05, 0.05)
                pts = [blade.point(min(0.97, max(0.03, s0 + c.rng.uniform(-0.08, 0.08))), r, side, 0.012)
                       for r in (0.08, 0.3, 0.52, 0.72)]
                c.glow.tube(pts, [0.04, 0.035, 0.03, 0.02], sides=6, color=GLOW, mask=M_NONE)
            rim = [blade.point(i / 12, 0.93, side, 0.008) for i in range(13)]
            c.glow.tube(rim, [0.025] * 13, sides=6, color=GLOW, mask=M_NONE)
    b = blades[0]
    c.trail(b.point(0, 1), b.point(1, 1), b.point(0.5, 1))



def voidglass_reaver(c):
    """Void tier: a hooked reaver blade of void-stone with a glassy edge, a
    bone hilt with horned guard and a void orb pommel."""
    VOID, DUSK, PLUM, EDGE = "#1E1630", "#3B2A5E", "#8E5CE0", "#F0E2FF"
    BONE, BONE_DARK = "#E6E0D2", "#B8AE98"
    GLOW, CRYSTAL = c.spec["glow"], c.spec["crystal"]
    grip = [Vector((0, 0, 0.18 + 0.05 * i)) for i in range(23)]
    c.handle.tube(grip, [0.13 + 0.025 * max(0.0, math.sin(p.z * 26)) for p in grip], sides=14, color=BONE, mask=M_WOOD)
    wraps(c.handle, 0.3, 1.2, 0.15, (DUSK, PLUM), M_LEATHER, turns=1.6, width=0.07)
    for side in (1, -1):
        claw = bezier((0, 0, 0.2), (0, side * 0.2, 0.1), (0, side * 0.25, -0.1), (0, side * 0.12, -0.28), 6)
        c.handle.tube(claw, [0.07 * (1 - i / 7) + 0.01 for i in range(7)], sides=8, color=BONE_DARK, mask=M_WOOD)
    c.crystal.sphere(Vector((0, 0, -0.08)), 0.17, CRYSTAL, M_NONE, segments=(8, 6))
    collar(c.head, 1.22, 1.42, 0.2, DUSK, (1, 0, 0, 0), rim=PLUM)
    for side in (1, -1):
        horn = bezier((0, 0, 1.36), (0, side * 0.45, 1.3), (0, side * 0.7, 1.55), (0, side * 0.62, 1.95), 10)
        c.head.tube(horn, [0.11 * (1 - i / 11) + 0.015 for i in range(11)], sides=10, color=BONE, mask=M_WOOD)

    def centre(s):
        return quad(v2(0.0, 1.4), v2(0.05, 3.9), v2(-1.4, 4.85), s) if s < 0.82 else \
            quad(v2(0.0, 1.4), v2(0.05, 3.9), v2(-1.4, 4.85), 0.82).lerp(v2(-1.25, 4.35), (s - 0.82) / 0.18)

    blade = Blade(curved_strip(centre, lambda s: 0.24 * (1 - s) ** 0.5 + 0.02,
                               lambda s: (0.38 + 0.3 * math.sin(math.pi * min(1.0, s * 1.2))) * (1 - s) ** 0.35 + 0.02),
                  taper(0.12, 0.014, 0.8),
                  lambda s, r: mix_hex(VOID, DUSK, r / 0.6) if r < 0.6 else mix_hex(PLUM, EDGE, ((r - 0.6) / 0.4) ** 0.8),
                  ns=26, nr=10).build(c.head)
    for side in (1, -1):
        for k in range(6):
            c.glow.sphere(blade.point(0.1 + k * 0.12, 0.35, side, 0.0), 0.05, GLOW, M_NONE, scale=(0.5, 1, 1),
                          segments=(8, 6))
    for k, s in enumerate((0.15, 0.32, 0.5)):
        crystal(c.crystal, blade.point(s, 0.0), (0, 0.8, 0.6), 0.5 - k * 0.1, 0.11 - k * 0.02, CRYSTAL)
    ring_tube(c.glow, blade.point(0.02, 0.5), 0.42, 0.03, (0, 0, 1), GLOW)
    c.trail(blade.point(0.2, 1), blade.point(0.85, 1), blade.point(0.6, 1))


def frostroot_cleaver(c):
    """Celestial tier: a huge ice cleaver on a haft of twisted roots, with a
    frost fur cuff, crystal crest and a glowing rune circle."""
    ROOT, ROOT_DARK = "#8A5A3B", "#5A3B22"
    SAPPHIRE, ICE, WHITE, FUR = "#23489E", "#A9D3FF", "#F4FBFF", "#EEF5FF"
    WRAP, WRAP_DARK = "#4C8FE6", "#1C3F8F"
    GLOW, CRYSTAL = c.spec["glow"], c.spec["crystal"]
    for k in range(2):
        pts = []
        for i in range(31):
            z = 0.1 + 4.6 * i / 30
            a = k * math.pi + z * 2.2
            pts.append(Vector((0.07 * math.cos(a), 0.07 * math.sin(a), z)))
        c.handle.tube(pts, [wood_radius(0.11, p.z, 2.0 + k) for p in pts], sides=12, mask=M_WOOD,
                      color_fn=lambda t, a, k=k: mix_hex(ROOT_DARK, ROOT, 0.4 + 0.4 * math.sin(a * 3 + t * 13 + k)))
    wraps(c.handle, 1.0, 2.2, 0.2, (WRAP, WRAP_DARK), M_LEATHER, turns=2.4)
    cuff = [Vector((0, 0, 2.55 + 0.05 * i)) for i in range(9)]
    c.handle.tube(cuff, [lambda a, i=i: (0.22 + 0.07 * math.sin(math.pi * i / 8)) * (1 + 0.12 * math.sin(a * 7 + i))
                         for i in range(9)], sides=16, color=FUR, mask=M_LEATHER)
    crystal(c.crystal, Vector((0, 0, 0.15)), (0, 0, -1), 0.5, 0.15, CRYSTAL)
    for k in range(3):
        a = 2 * math.pi * k / 3
        root = bezier((0, 0, 4.6), (0.12 * math.cos(a), 0.12 * math.sin(a), 4.95), (0.3 * math.cos(a), 0.25 + 0.2 * math.sin(a), 5.2),
                      (0.22 * math.cos(a), 0.45, 5.05 - 0.2 * k), 8)
        c.head.tube(root, [0.08 * (1 - i / 9) + 0.02 for i in range(9)], sides=8, color=ROOT, mask=M_WOOD)
    collar(c.head, 3.0, 4.95, 0.24, ROOT_DARK, M_WOOD, rim=ROOT)

    surface = coons(lambda r: v2(-0.2, 4.9).lerp(v2(-2.0, 5.1), r),
                    lambda r: v2(-0.2, 3.0).lerp(v2(-1.9, 2.7), r) + v2(0, -0.08 * math.sin(math.pi * r)),
                    lambda s: v2(-0.2, 4.9).lerp(v2(-0.2, 3.0), s),
                    lambda s: quad(v2(-2.0, 5.1), v2(-2.25, 3.9), v2(-1.9, 2.7), s))
    blade = Blade(surface, taper(0.2, 0.03, 0.75), edge_ramp(SAPPHIRE, ICE, WHITE, 0.8), ns=18, nr=12).build(c.head)
    for side in (1, -1):
        ring_tube(c.glow, blade.point(0.5, 0.42, side, 0.005), 0.36, 0.035, (1, 0, 0), GLOW)
        for k in range(4):
            c.glow.sphere(blade.point(0.5 + 0.17 * math.cos(k * math.pi / 2), 0.42 + 0.14 * math.sin(k * math.pi / 2), side, 0.0),
                          0.05, GLOW, M_NONE, scale=(0.5, 1, 1), segments=(8, 6))
    for k, r in enumerate((0.15, 0.38, 0.6, 0.82)):
        crystal(c.crystal, blade.point(0.0, r), (0, -0.2, 1), 0.6 - 0.08 * abs(k - 1.5), 0.13, CRYSTAL)
    crystal(c.crystal, Vector((0, 0.32, 4.4)), (0, 1, 0.3), 0.6, 0.15, CRYSTAL)
    c.trail(blade.point(0, 1), blade.point(1, 1), blade.point(0.5, 1))


def stardust_scythe(c):
    """Nebula tier: a long scythe whose crescent blade fades from deep space to
    nebula pink, scattered with stars."""
    NAVY, PLUM, PINK, MAGENTA, EDGE = "#1B1446", "#4B2A80", "#FF8FE0", "#C04CD8", "#FFE1F6"
    SILVER, SILVER_DARK = "#D8DCEB", "#8E93A8"
    GLOW, CRYSTAL = c.spec["glow"], c.spec["crystal"]
    staff(c.handle, 0.0, 6.5, 0.12, lambda t, a: mix_hex(NAVY, PLUM, t * 0.8 + 0.1 * math.sin(a * 2)), (1, 0, 0, 0),
          bend=0.12)
    for z in (0.2, 3.3, 6.25):
        collar(c.handle, z - 0.1, z + 0.1, 0.15, SILVER, M_BRASS, rim=SILVER_DARK)
    for z in (2.4, 4.3):
        nib = [Vector((0, -0.05, z)), Vector((0, -0.35, z + 0.05)), Vector((0, -0.55, z + 0.15))]
        c.handle.tube(nib, [0.08, 0.075, 0.07], sides=10, color=SILVER, mask=M_BRASS)
        wraps(c.handle, z - 0.35, z + 0.35, 0.125, (PINK, MAGENTA), M_LEATHER, turns=1.4, width=0.06)
    c.glow.sphere(Vector((0, 0, -0.05)), 0.14, GLOW, M_NONE, segments=(8, 6))
    collar(c.head, 6.4, 6.7, 0.17, SILVER, M_BRASS, rim=SILVER_DARK)
    c.head.tube([Vector((0, 0.05, 6.55)), Vector((0, 0.35, 6.65)), Vector((0, 0.6, 6.5))], [0.09, 0.07, 0.01], sides=8,
                color=SILVER_DARK, mask=M_BRASS)

    def centre(s):
        return bezier_point((0.0, 6.6), (-1.0, 7.05), (-2.3, 6.95), (-3.1, 5.7), s)

    blade = Blade(curved_strip(centre, lambda s: 0.12 * (1 - s) + 0.01, lambda s: 0.5 * (1 - s) ** 0.6 + 0.02,
                               edge_inside=True),
                  taper(0.11, 0.014, 0.8),
                  lambda s, r: mix_hex(mix_hex(NAVY, MAGENTA, s), mix_hex(PLUM, PINK, s), r / 0.8) if r < 0.8
                  else mix_hex(PINK, EDGE, (r - 0.8) / 0.2), ns=28, nr=10).build(c.head)
    for side in (1, -1):
        for k in range(9):
            s, r = c.rng.uniform(0.05, 0.85), c.rng.uniform(0.15, 0.7)
            c.glow.sphere(blade.point(s, r, side, -0.01), 0.04 + 0.03 * (k % 3 == 0), GLOW, M_NONE, scale=(0.5, 1, 1),
                          segments=(8, 6))
        c.crystal.sphere(blade.point(0.05, 0.35, side, 0.02), 0.13, CRYSTAL, M_NONE, scale=(0.6, 1, 1), segments=(6, 4))
    crystal(c.crystal, Vector((0, 0, 6.72)), (0, 0.1, 1), 0.5, 0.12, CRYSTAL)
    c.trail(blade.point(0.1, 1), blade.point(0.95, 1), blade.point(0.6, 1))


def sunburst_halberd(c):
    """Solar tier: a gilded halberd with a sun disc between its axe blade and
    spear point, flame tassels and a white-gold shaft."""
    GOLD, GOLD_DARK, WHITE_GOLD, FLARE_EDGE = "#FFC93C", "#B8732A", "#FFE7A8", "#FFF6D0"
    RED, RED_DARK = "#E8452C", "#A8301C"
    GLOW = c.spec["glow"]
    staff(c.handle, 0.0, 6.4, 0.13, lambda t, a: mix_hex(WHITE_GOLD, GOLD, 0.3 + 0.3 * math.sin(a * 2 + t * 6)), M_BRASS)
    for z0, z1 in ((1.6, 3.2), (4.0, 4.8)):
        wraps(c.handle, z0, z1, 0.135, (RED, RED_DARK), M_LEATHER, turns=2.6 * (z1 - z0), width=0.07, crossed=False)
    collar(c.handle, 0.0, 0.3, 0.17, GOLD, M_BRASS, rim=GOLD_DARK)
    c.handle.tube([Vector((0, 0, 0.02)), Vector((0, 0, -0.3)), Vector((0, 0, -0.55))], [0.13, 0.08, 0.01], sides=8,
                  color=GOLD_DARK, mask=M_BRASS)
    collar(c.head, 5.1, 7.15, 0.18, GOLD, M_BRASS, rim=GOLD_DARK)
    for k in range(7):  # flame tassels
        a = 2 * math.pi * k / 7
        top = Vector((0.16 * math.cos(a), 0.16 * math.sin(a), 5.1))
        c.head.tube([top, top + Vector((0.08 * math.cos(a), 0.08 * math.sin(a), -0.35)),
                     top + Vector((0.1 * math.cos(a), 0.1 * math.sin(a), -0.75))], [0.05, 0.045, 0.01], sides=6,
                    color=RED if k % 2 else RED_DARK, mask=M_LEATHER)
    axe = Blade(coons(lambda r: v2(-0.18, 6.6).lerp(v2(-1.45, 7.05), r),
                      lambda r: quad(v2(-0.18, 5.55), v2(-0.6, 5.35), v2(-1.35, 4.95), r),
                      lambda s: v2(-0.18, 6.6).lerp(v2(-0.18, 5.55), s),
                      lambda s: quad(v2(-1.45, 7.05), v2(-1.95, 6.0), v2(-1.35, 4.95), s)),
                taper(0.15, 0.022, 0.8), edge_ramp(GOLD_DARK, GOLD, FLARE_EDGE, 0.8)).build(c.head)
    Blade(lambda s, r: v2(lerp(0.32, -0.32, r) * max(0.04, (math.sin(math.pi * min(1.0, 0.25 + s * 0.9)) + 0.05) * (1 - s ** 3)),
                                 lerp(7.1, 8.6, s)),
                  lambda s, r: 0.13 * (1 - abs(2 * r - 1)) ** 0.8 * (1 - 0.7 * s) + 0.016,
                  lambda s, r: mix_hex(GOLD, FLARE_EDGE, abs(2 * r - 1) ** 2), ns=16, nr=10).build(c.head)
    hook = bezier((0, 0.15, 6.1), (0, 0.6, 6.15), (0, 0.85, 6.45), (0, 0.8, 6.85), 10)
    c.head.tube(hook, [0.12 * (1 - i / 11) + 0.012 for i in range(11)], sides=10, color=GOLD, mask=M_BRASS)
    disc = Vector((0, 0, 6.1))
    c.head.tube([disc + Vector((-0.14, 0, 0)), disc + Vector((0.14, 0, 0))], [0.55, 0.55], sides=24, color=GOLD_DARK,
                mask=M_BRASS)
    for k in range(12):
        a = 2 * math.pi * k / 12 + 0.26
        d = Vector((0, math.cos(a), math.sin(a)))
        c.head.tube([disc + d * 0.52, disc + d * (1.0 if k % 2 else 0.78)], [0.08, 0.008], sides=6, color=GOLD,
                    mask=M_BRASS)
    for side in (1, -1):
        c.glow.sphere(disc + Vector((side * 0.13, 0, 0)), 0.44, GLOW, M_NONE, scale=(0.3, 1, 1), segments=(16, 8))
    c.trail(axe.point(0, 1), axe.point(1, 1), axe.point(0.5, 1))


def eclipse_glaive(c):
    """Astral tier: a twin glaive, crescent moon blades at both ends of a
    midnight staff, held at the middle between two eclipse rings."""
    MIDNIGHT, INDIGO, VIOLET, MOON = "#120E2E", "#2A2370", "#6B4FD8", "#FFF1B8"
    GOLD, GOLD_DARK = "#F3C64A", "#9C7424"
    WRAP, WRAP_DARK = "#9C8CFF", "#4B3AA0"
    GLOW, CRYSTAL = c.spec["glow"], c.spec["crystal"]
    staff(c.handle, 0.0, 6.0, 0.12, lambda t, a: mix_hex(MIDNIGHT, INDIGO, 0.5 + 0.5 * math.sin(t * 30 + a)), (1, 0, 0, 0))
    wraps(c.handle, 2.45, 3.55, 0.13, (WRAP, WRAP_DARK), M_LEATHER, turns=2.2)
    for z in (0.9, 1.6, 4.4, 5.1):
        collar(c.handle, z - 0.06, z + 0.06, 0.145, GOLD, M_BRASS)
    for z in (2.2, 3.8):
        c.head.tube([Vector((-0.1, 0, z)), Vector((0.1, 0, z))], [0.34, 0.34], sides=24, color=MIDNIGHT, mask=M_NONE)
        ring_tube(c.glow, (0, 0, z), 0.4, 0.05, (1, 0, 0), GLOW)
        for k in range(8):
            a = 2 * math.pi * k / 8
            d = Vector((0, math.cos(a), math.sin(a)))
            crystal(c.crystal, Vector((0, 0, z)) + d * 0.42, d, 0.22 if k % 2 else 0.32, 0.05, CRYSTAL)

    def centre(s):
        return bezier_point((0.0, 5.95), (-0.1, 7.0), (-1.0, 7.75), (-1.9, 7.55), s)

    def color(s, r):
        if r < 0.78:
            return mix_hex(INDIGO, VIOLET, r / 0.78 * (0.5 + 0.5 * s))
        return mix_hex(VIOLET, MOON, (r - 0.78) / 0.22)

    flip = Matrix.Translation((0, 0, 6.0)) @ Matrix.Rotation(math.pi, 4, "X")  # point mirror through the grip
    blades = []
    for xf in (Matrix.Identity(4), flip):
        blade = Blade(curved_strip(centre, lambda s: 0.1 * (1 - s) + 0.01,
                                   lambda s: (0.35 + 0.2 * math.sin(math.pi * s)) * (1 - s) ** 0.5 + 0.02),
                      taper(0.11, 0.014, 0.8), color, ns=24, nr=10, xform=xf).build(c.head)
        blades.append(blade)
        for side in (1, -1):
            for k in range(4):
                c.glow.sphere(blade.point(0.15 + 0.17 * k, 0.4, side, -0.005), 0.045, GLOW, M_NONE, scale=(0.5, 1, 1),
                              segments=(8, 6))
        base = xf @ Vector((0, 0, 5.95))
        crystal(c.crystal, base, xf.to_3x3() @ Vector((0, 0.6, 1)), 0.45, 0.1, CRYSTAL)
        c.head.sphere(base, 0.17, GOLD, M_BRASS)
        c.head.sphere(base + xf.to_3x3() @ Vector((0, 0, -0.1)), 0.15, GOLD_DARK, M_BRASS)
    b = blades[0]
    c.trail(b.point(0.15, 1), b.point(0.95, 1), b.point(0.6, 1))


def bezier_point(p0, p1, p2, p3, t):
    p0, p1, p2, p3 = (Vector(p) for p in (p0, p1, p2, p3))
    u = 1 - t
    return p0 * u ** 3 + p1 * 3 * u * u * t + p2 * 3 * u * t * t + p3 * t ** 3


# ---------------------------------------------------------------------------
# The chopper list (shop order). Strength per hit, Cash and Robux prices are
# your numbers; rows marked "new" fill the list up to 10 and are placeholders.
# grip_z: where the hand holds the handle, in Blender Z (studs).
# ---------------------------------------------------------------------------
def C(order, asset, display, tier, weapon_type, strength, cash, robux, builder=None, glow=None, crystal=None,
      grip_z=1.0, trail="#FFFFFF", source="Choppers"):
    return dict(order=order, asset=asset, display=display, tier=tier, type=weapon_type, strength=strength, cash=cash,
                robux=robux, builder=builder, glow=glow, crystal=crystal, grip_z=grip_z, trail=trail, source=source)


CHOPPERS = [
    C(1, "MossbarkHatchet", "Mossbark Hatchet", "Wood", "Axe", 1, 0, 0, source="StarterSet", trail="#C8F0AA"),
    C(2, "StonebarkHatchet", "Stonebark Hatchet", "Wood", "Axe", 5, 500, 15, stonebark_hatchet, grip_z=1.2,
      trail="#E3DED4"),
    C(3, "FernleafSickle", "Fernleaf Sickle", "Wood", "Sickle", 20, 15000, 29, fernleaf_sickle, grip_z=1.0,
      trail="#B5E36A"),  # new
    C(4, "AmethystChopper", "Amethyst Chopper", "Crystal", "Sword", 60, 250000, 49, amethyst_chopper,
      crystal="#B48CFF", grip_z=0.75, trail="#D9C8FF"),
    C(5, "MagmaseamAxe", "Magmaseam Axe", "Lava", "Axe", 600, 50e6, 99, magmaseam_axe, glow="#FF7A1A", grip_z=1.6,
      trail="#FFB04A"),
    C(6, "VoidglassReaver", "Voidglass Reaver", "Void", "Sword", 5000, 10e9, 199, voidglass_reaver, glow="#D7B8FF",
      crystal="#9B5CFF", grip_z=0.75, trail="#B98CFF"),
    C(7, "FrostrootCleaver", "Frostroot Cleaver", "Celestial", "Axe", 25000, 1e12, 399, frostroot_cleaver,
      glow="#5FF4FF", crystal="#7FEAFF", grip_z=1.5, trail="#A9E8FF"),
    C(8, "StardustScythe", "Stardust Scythe", "Nebula", "Scythe", 150000, 80e12, 599, stardust_scythe,
      glow="#FFF6D6", crystal="#FF8FE0", grip_z=2.6, trail="#FF9FE6"),  # new
    C(9, "SunburstHalberd", "Sunburst Halberd", "Solar", "Halberd", 900000, 5e15, 799, sunburst_halberd,
      glow="#FFE45A", grip_z=2.4, trail="#FFD84A"),  # new
    C(10, "EclipseGlaive", "Eclipse Glaive", "Astral", "Glaive", 5000000, 300e15, 999, eclipse_glaive,
      glow="#FFE7A0", crystal="#9C8CFF", grip_z=3.0, trail="#C9BCFF"),  # new
]


# ---------------------------------------------------------------------------
# Pipeline: build, bake, preview, export, data module
# ---------------------------------------------------------------------------
def flat_material(key, hex_value, look):
    """Preview material for the flat Glow (Neon) and Crystal (Glass) parts."""
    mat = bpy.data.materials.get("CF_" + key) or bpy.data.materials.new("CF_" + key)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    color = linear_rgba(hex_value)
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Emission Color"].default_value = color
    bsdf.inputs["Emission Strength"].default_value = 0.0
    if look == "Neon":
        bsdf.inputs["Emission Strength"].default_value = 4.0
    elif look == "Glass":
        bsdf.inputs["Roughness"].default_value = 0.08
        bsdf.inputs["Emission Strength"].default_value = 0.5
        bsdf.inputs["Transmission Weight"].default_value = 0.6
    return mat


def world_bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
            hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
    return lo, hi


def build_chopper(spec):
    scene, coll = make_scene(spec["asset"])
    c = Chopper(spec)
    spec["builder"](c)
    objects = {}
    for role in ("Handle", "Head", "Glow", "Crystal"):
        sb = getattr(c, role.lower())
        if not sb.bm.faces:
            sb.bm.free()
            continue
        obj = sb.to_object(coll, spec["asset"] + "_" + role)
        if role in ("Glow", "Crystal"):
            look = "Neon" if role == "Glow" else "Glass"
            hex_value = spec["glow"] if role == "Glow" else spec["crystal"]
            if role == "Crystal":
                for poly in obj.data.polygons:
                    poly.use_smooth = False  # crystals keep their facets
            PALETTE[obj.name] = hex_value
            if role == "Glow":
                GLOW_PARTS.add(obj.name)
            obj["PaletteKey"] = obj.name
            obj["Look"] = look
            obj.data.materials.append(flat_material(obj.name, hex_value, look))
            for name in [a.name for a in obj.data.color_attributes]:
                obj.data.color_attributes.remove(obj.data.color_attributes[name])
        else:
            smooth_and_bake(scene, obj, obj.name)
            obj["Look"] = "Baked"
        objects[role] = obj
    sockets = []
    for name, p in c.sockets.items():
        s = add_socket(coll, name, p)
        s.name = s.data.name = "%s_Socket_%s" % (spec["asset"], name)
        sockets.append(s)
    handle_bottom = min((objects["Handle"].matrix_world @ v.co).z for v in objects["Handle"].data.vertices)
    check_budget(objects, spec["asset"])
    return dict(spec=spec, scene=scene, coll=coll, objects=objects, sockets=sockets,
                grip_from_bottom=round(spec["grip_z"] - handle_bottom, 3))


def render_chopper(built):
    scene, coll = built["scene"], built["coll"]
    for child in scene.collection.children:
        set_collection_visible(scene, child, child is coll)
    lo, hi = world_bounds(list(built["objects"].values()))
    centre = (lo + hi) / 2
    size = hi - lo
    distance = max(size.z * 1.55, size.y * 2.1, 6.0)
    setup_preview(scene, coll, target=centre, distance=distance, height=distance * 0.12, angle_deg=-55, ground=False,
                  size=(PREVIEW_W, PREVIEW_H), background="#6E7480")
    render_preview(scene, built["spec"]["asset"] + ".png")
    return os.path.join(PREVIEW_DIR, built["spec"]["asset"] + ".png")


def contact_sheet(paths, out_name, columns=5):
    import numpy as np
    tiles = []
    for p in paths:
        img = bpy.data.images.load(p)
        w, h = img.size
        tiles.append(np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1])
        bpy.data.images.remove(img)
    if not tiles:
        return
    th, tw = tiles[0].shape[:2]
    rows = (len(tiles) + columns - 1) // columns
    sheet = np.ones((rows * th, columns * tw, 4), dtype=np.float32)
    sheet[..., :3] = 0.43
    for i, t in enumerate(tiles):
        r, col = divmod(i, columns)
        sheet[r * th:(r + 1) * th, col * tw:(col + 1) * tw] = t
    save_rgba(out_name, sheet)
    os.replace(os.path.join(TEXTURE_DIR, out_name + ".png"), os.path.join(PREVIEW_DIR, out_name + ".png"))


def lua(value, indent=1):
    pad = "\t" * indent
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(round(value, 6)) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return '"' + value.replace('"', '\\"') + '"'
    if isinstance(value, (list, tuple)):
        return "{ " + ", ".join(lua(v, indent + 1) for v in value) + " }"
    items = []
    for k in sorted(value):
        key = k if k.isidentifier() else '["%s"]' % k
        items.append("%s%s = %s," % (pad, key, lua(value[k], indent + 1)))
    return "{\n" + "\n".join(items) + "\n" + "\t" * (indent - 1) + "}"


def write_data_module(built_list):
    entries = {}
    built_by_asset = {b["spec"]["asset"]: b for b in built_list}
    for spec in CHOPPERS:
        e = dict(Order=spec["order"], DisplayName=spec["display"], Tier=spec["tier"], WeaponType=spec["type"],
                 StrengthPerClick=spec["strength"], CashPrice=spec["cash"], RobuxPrice=spec["robux"],
                 TrailColor=spec["trail"], Source=spec["source"])
        b = built_by_asset.get(spec["asset"])
        if b:
            e["GripFromBottom"] = b["grip_from_bottom"]
            e["Parts"] = {obj.name: dict(Role=role, Look=obj["Look"], Color=PALETTE.get(obj.name, "#FFFFFF"))
                          for role, obj in b["objects"].items()}
            e["Sockets"] = sorted(s.name.split("_Socket_")[1] for s in b["sockets"])
        entries[spec["asset"]] = e
    text = ("-- ChopperData (ModuleScript) - GENERATED by blender/GenerateChoppers.py. Do not edit by hand:\n"
            "-- change CHOPPERS in the generator and re-run it. Location: ReplicatedStorage.ChopperData\n"
            "-- Every chopper in shop order: stats (StrengthPerClick = Strength per hit), prices, grip and parts.\n"
            "-- Source = \"StarterSet\" means the model comes from GenerateStarterSet.py (StarterSet.MakeTool).\n"
            "return {\n\tChoppers = " + lua(entries, 2) + ",\n}\n")
    path = os.path.join(OUTPUT_DIR, "ChopperData.lua")
    with open(path, "w") as handle:
        handle.write(text)
    log("Wrote %s" % path)


def main():
    log("Blender %s - building %s" % (bpy.app.version_string, SET_NAME))
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    scene = work_scene()
    built = []
    previews = []
    for spec in CHOPPERS:
        if spec["builder"] is None or (ONLY and spec["asset"] not in ONLY):
            continue
        b = build_chopper(spec)
        built.append(b)
        if RENDER_PREVIEWS:
            previews.append(render_chopper(b))
    if RENDER_PREVIEWS and len(previews) > 1:
        contact_sheet(previews, "Choppers_Lineup")
    # Side by side (along X, the blades' thin axis) so one GLB holds them all.
    for i, b in enumerate(built):
        for obj in list(b["objects"].values()) + b["sockets"]:
            obj.location.x += i * 2.5
    for child in scene.collection.children:
        set_collection_visible(scene, child, True)
    export = [o for b in built for o in list(b["objects"].values()) + b["sockets"]]
    if export:
        export_glb(scene, export, os.path.join(OUTPUT_DIR, "Choppers.glb"))
    write_data_module(built)
    manifest = {b["spec"]["asset"]: dict(parts={r: tri_count(o) for r, o in b["objects"].items()},
                                         grip_from_bottom=b["grip_from_bottom"]) for b in built}
    with open(os.path.join(OUTPUT_DIR, SET_NAME + "_Manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=2)
    flush_log()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUTPUT_DIR, SET_NAME + ".blend"), copy=True)
    log("Done. Output: %s" % OUTPUT_DIR)


try:
    main()
except Exception:
    log("FAILED:\n" + traceback.format_exc())
    raise
finally:
    flush_log()
