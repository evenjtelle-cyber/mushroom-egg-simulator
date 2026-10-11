"""
GenerateStarterSet.py  -  Blender 4.x
"+1 Chop Mushrooms for Eggs": Wood-tier starter set

Builds three assets in one scene, "StarterSet", one collection per asset:

  MossbarkHatchet  The starter axe (Wood, Common). Unlike the creatures, weapons
                   are SMOOTH and CARTOONY: soft subdivided shapes and a
                   hand-painted look baked into one texture per part. It has a
                   bearded steel head with hammered facets and a few edge chips,
                   a slightly curved wooden haft with crossed green leather
                   wraps, brass collars and rivets, a chain ring on the poll and
                   a small pommel spike. About 4.6 studs long. Parts: Handle
                   (the Tool handle) and Head.
  MossbarkEgg      The most common egg (Wood, Common). Blocky stud style: a
                   bark-brown banded shell, a draping moss-leaf cap, a sprout on
                   top and a tiny red mushroom on its side. No nest: it sits
                   straight on the ground (pivot at the base). About 4.8 studs tall.
  MosscapToad      The first Common monster from that egg. Blocky stud style,
                   simple (Common on the complexity ladder): a chubby moss-green
                   toad with big eyes, blushing cheeks, moss tufts and a red
                   Amanita cap with white warts. About 4.5 studs tall.

Also writes this set's VFX textures (Spore, LeafBit, DustPuff, SwingStreak; white
RGB with alpha), StudOverlay, and the egg's hatch shell shards.

Output: ~/Documents/StarterSet/  (GLBs, Textures/, Previews/, .blend, manifest)
Run: Blender Text Editor -> Run Script (Alt+P), or
     blender --background --python GenerateStarterSet.py
Blender looks frozen while it bakes and renders (1-4 minutes). That's normal.
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
SET_NAME = "StarterSet"
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", SET_NAME)
TEXTURE_DIR = os.path.join(OUTPUT_DIR, "Textures")
PREVIEW_DIR = os.path.join(OUTPUT_DIR, "Previews")
LOG_NAME = SET_NAME + "_Log"

BUILD_AXE = True
BUILD_EGG = True
BUILD_MONSTER = True
RENDER_PREVIEWS = True
PREVIEW_SAMPLES = 24
BAKE_SIZE = 1024  # one baked colour texture per axe part (brief: max 1024)
BAKE_SAMPLES = 16
FACE_POSITIVE_Y = False
SEED = 11

MAX_TRIS_PER_PART = 20000
STUD_TILE_PX = 128
STUDS_PER_UNIT = 2.0

# sRGB hex palette for the blocky parts. Mirrored in src/ReplicatedStorage/StarterSet.lua.
PALETTE = {
    # Mossbark Egg
    "EggShell": "#7A5230",
    "EggShellLight": "#9A6B3F",
    "EggMoss": "#4F8A2E",
    "EggLeaf": "#7CC242",
    "EggLeafLight": "#B5E36A",
    "EggSprout": "#5FA83A",
    "EggShroom": "#E5402F",
    "EggShroomSpots": "#FFF7EC",
    # Mosscap Toad
    "ToadBody": "#6DBE45",
    "ToadBelly": "#F1E7C2",
    "ToadMoss": "#4F8A2E",
    "ToadToes": "#8ED160",
    "ToadCap": "#E5402F",
    "ToadSpots": "#FFF7EC",
    "ToadEyes": "#FFFFFF",
    "ToadPupils": "#1B1B1B",
    "ToadMouth": "#3A1F14",
    "ToadCheeks": "#FF8FA3",
}

GLOW_PARTS = set()  # Common tier: nothing glows
NO_STUD_PARTS = {"ToadPupils", "ToadMouth", "ToadEyes"}


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


# ---------------------------------------------------------------------------
# Geometry builder: one bmesh per colour part, boxes with per-slab stud UVs
# ---------------------------------------------------------------------------
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


class PartBuilder:
    def __init__(self):
        self.meshes = {}

    def _bm(self, part):
        if part not in self.meshes:
            bm = bmesh.new()
            bm.loops.layers.uv.new("UVMap")
            self.meshes[part] = bm
        return self.meshes[part]

    def box(self, part, center, size, rot=None, taper=(1.0, 1.0)):
        """Box centred at `center` with `size` (x, y, z) in its local frame.
        `rot` is a 3x3 matrix. `taper` scales the +Y end in local (x, z), so
        plates, horns and claws can narrow toward their tips."""
        bm = self._bm(part)
        uv = bm.loops.layers.uv.active
        rot = rot if rot is not None else Matrix.Identity(3)
        c = Vector(center)
        hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
        local = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    tx, tz = (taper if sy > 0 else (1.0, 1.0))
                    local.append(Vector((sx * hx * tx, sy * hy, sz * hz * tz)))
        verts = [bm.verts.new(c + rot @ p) for p in local]

        def idx(sx, sy, sz):
            return ((sx > 0) * 4) + ((sy > 0) * 2) + (sz > 0)

        faces = [
            ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),
            ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)),
            ((-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)),
            ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)),
            ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)),
            ((-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)),
        ]
        for corners in faces:
            face = bm.faces.new([verts[idx(*k)] for k in corners])
            # Box-project in the slab's own frame: one UV unit = one stud.
            normal_axis = 0 if all(k[0] == corners[0][0] for k in corners) else (1 if all(k[1] == corners[0][1] for k in corners) else 2)
            for loop, k in zip(face.loops, corners):
                p = Vector((k[0] * hx, k[1] * hy, k[2] * hz))
                if normal_axis == 0:
                    u, v = p.y + hy, p.z + hz
                elif normal_axis == 1:
                    u, v = p.x + hx, p.z + hz
                else:
                    u, v = p.x + hx, p.y + hy
                loop[uv].uv = (u * STUDS_PER_UNIT, v * STUDS_PER_UNIT)

    def blob(self, part, center, radii, step=1.0, rot=None, profile=None):
        """Rounded mass from stacked cross-slab layers along local Y.
        radii = (rx, ry, rz). Each slice is three overlapping slabs (wide-flat,
        narrow-tall, square-ish), giving a stepped, rounded blocky silhouette."""
        rot = rot if rot is not None else Matrix.Identity(3)
        rx, ry, rz = radii
        n = max(2, int(round(2 * ry / step)))
        thickness = 2 * ry / n
        for i in range(n):
            t = -1.0 + (i + 0.5) * (2.0 / n)
            k = math.sqrt(max(0.0, 1.0 - t * t)) if profile is None else profile(t)
            if k <= 0.05:
                continue
            ax, az = rx * k, rz * k
            offset = rot @ Vector((0.0, t * ry, 0.0))
            # Each slab gets its own depth so no two end faces are coplanar
            # (coplanar overlaps self-shadow black in Cycles and z-fight in Roblox).
            for wx, wz, depth in ((1.9, 1.2, 1.06), (1.2, 1.9, 0.9), (1.62, 1.62, 0.76)):
                self.box(part, Vector(center) + offset, (ax * wx, thickness * depth, az * wz), rot)

    def chain(self, part, points, sizes, roll_hint=(0, 0, 1), overlap=1.18, taper_last=None):
        """Segment boxes along a polyline: tusks, horns, wing spars, tails."""
        for i in range(len(points) - 1):
            a, b = Vector(points[i]), Vector(points[i + 1])
            d = b - a
            if d.length < 1e-4:
                continue
            rot = basis_from_y(d, roll_hint)
            s = sizes[i]
            taper = (1.0, 1.0)
            if taper_last and i == len(points) - 2:
                taper = taper_last
            self.box(part, (a + b) / 2, (s, d.length * overlap, s), rot, taper)

    def crystal(self, part, base, direction, length, radius, sides=6, twist=0.0):
        """Faceted crystal: hex prism that swells slightly, then a pointed tip."""
        bm = self._bm(part)
        uv = bm.loops.layers.uv.active
        rot = basis_from_y(Vector(direction), Vector((0.3, 0.1, 1.0)))
        base = Vector(base)

        def ring(h, r):
            pts = []
            for j in range(sides):
                a = twist + 2 * math.pi * j / sides
                pts.append(bm.verts.new(base + rot @ Vector((math.cos(a) * r, h, math.sin(a) * r))))
            return pts

        r0 = ring(-0.15 * length, radius * 0.85)
        r1 = ring(0.62 * length, radius * 1.05)
        tip = bm.verts.new(base + rot @ Vector((0.0, length, 0.0)))
        faces = [bm.faces.new(list(reversed(r0)))]
        for j in range(sides):
            k = (j + 1) % sides
            faces.append(bm.faces.new((r0[j], r0[k], r1[k], r1[j])))
            faces.append(bm.faces.new((r1[j], r1[k], tip)))
        for face in faces:
            for loop in face.loops:
                loop[uv].uv = (0.5, 0.5)

    def to_objects(self, collection, name_prefix=""):
        objects = {}
        for part, bm in self.meshes.items():
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            name = name_prefix + part
            mesh = bpy.data.meshes.new(name)
            bm.to_mesh(mesh)
            bm.free()
            obj = bpy.data.objects.new(name, mesh)
            collection.objects.link(obj)
            obj["PaletteKey"] = part
            obj["ColorHex"] = PALETTE.get(part, "#FFFFFF")
            objects[part] = obj
        self.meshes = {}
        return objects


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


_stud_image = None


def stud_image():
    global _stud_image
    if _stud_image is None or _stud_image.name not in bpy.data.images:
        path = os.path.join(TEXTURE_DIR, "StudOverlay.png")
        if not os.path.exists(path):
            write_stud_overlay()
        _stud_image = bpy.data.images.load(path, check_existing=True)
    return _stud_image


def material_for(part):
    name = "FM_" + part
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    color = linear_rgba(PALETTE.get(part, "#FFFFFF"))
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.55
    if part in GLOW_PARTS:
        bsdf.inputs["Roughness"].default_value = 0.12
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 3.0 if part in ("Eyes", "Cracks") else 0.9
        if part not in ("Eyes", "Cracks"):
            bsdf.inputs["Transmission Weight"].default_value = 0.55
            bsdf.inputs["Alpha"].default_value = 0.85
    elif part not in NO_STUD_PARTS:
        # Plastic + stud overlay: colour = mix(base, overlay.rgb, overlay.alpha)
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = stud_image()
        tex.interpolation = "Linear"
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["A"].default_value = color
        links.new(tex.outputs["Alpha"], mix.inputs["Factor"])
        links.new(tex.outputs["Color"], mix.inputs["B"])
        links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    return mat


def assign_materials(objects):
    for part, obj in objects.items():
        obj.data.materials.append(material_for(part))


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
    """Flat palette material for the GLB: Studio picks up the colour, and the
    stud overlay / glow are added in Studio (the preview shader's texture mix
    is not something glTF can carry)."""
    name = "FMX_" + part
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        color = linear_rgba(PALETTE.get(part, "#FFFFFF"))
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.5
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
        PALETTE.setdefault("PreviewGrass", "#5FC23A")
        ground_obj.data.materials.append(material_for("PreviewGrass"))
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


# ---------------------------------------------------------------------------
# Shared motifs
# ---------------------------------------------------------------------------
FUR_PARTS = ("FurWhite", "FurIce", "FurBlue", "FurNavy")


def fur_colour(p, rng, white_bias=0.0):
    """Mammoth-style banded fur: diagonal stripes plus noise, whiter on top."""
    n = noise.noise(Vector((p.x * 0.22, p.y * 0.22, p.z * 0.22)))
    stripe = math.sin(p.y * 0.55 + p.z * 0.35 + p.x * 0.15 + n * 2.2)
    v = stripe * 0.6 + n * 0.8 + white_bias + rng.uniform(-0.25, 0.25)
    if v > 0.55:
        return "FurWhite"
    if v > 0.0:
        return "FurIce"
    if v > -0.6:
        return "FurBlue"
    return "FurNavy"


def fur_plate(builder, anchor, normal, drape, rng, width, length, part, thickness=0.32, lift=(6, 22), spin=12):
    """One shaggy slab hanging from `anchor` along `drape`, lifted off the
    surface a little so layers overlap like the mammoth's coat."""
    n = Vector(normal).normalized()
    d = Vector(drape)
    d = (d - n * d.dot(n)).normalized()
    rot = basis_from_y(d, n)
    rot = rot @ Matrix.Rotation(math.radians(rng.uniform(-spin, spin)), 3, "Z")
    rot = rot @ Matrix.Rotation(math.radians(-rng.uniform(*lift)), 3, "X")
    centre = Vector(anchor) + rot @ Vector((0.0, length * 0.5, thickness * 0.5))
    builder.box(part, centre, (width, length, thickness), rot, taper=(rng.uniform(0.6, 0.85), 1.0))
    # A notched tip on some plates gives the ragged edge of the reference fur.
    if rng.random() < 0.35:
        tip = Vector(anchor) + rot @ Vector((width * rng.uniform(-0.2, 0.2), length * 1.02, thickness * 0.5))
        builder.box(part, tip, (width * 0.38, length * 0.32, thickness * 0.9), rot)


def crystal_cluster(builder, base, up, rng, size=1.0, count=3, violet_chance=0.2, part="Crystals", violet_part="CrystalsViolet"):
    up = Vector(up).normalized()
    side = up.orthogonal().normalized()
    for i in range(count):
        if i == 0:
            direction, length, radius = up, 2.6 * size, 0.42 * size
        else:
            a = 2 * math.pi * i / max(1, count - 1) + rng.uniform(-0.4, 0.4)
            tilt = Matrix.Rotation(a, 3, up) @ side
            direction = (up + tilt * rng.uniform(0.45, 0.8)).normalized()
            length, radius = rng.uniform(1.1, 1.8) * size, rng.uniform(0.22, 0.32) * size
        p = violet_part if rng.random() < violet_chance and i > 0 else part
        builder.crystal(p, Vector(base) - up * 0.2 * size, direction, length, radius, twist=rng.uniform(0, 1))



# ---------------------------------------------------------------------------
# Texture helpers (numpy -> PNG)
# ---------------------------------------------------------------------------
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


def white_alpha(alpha):
    import numpy as np
    a = np.clip(alpha, 0.0, 1.0)
    out = np.ones(a.shape + (4,), dtype=np.float32)
    out[..., 3] = a
    return out


def grid(n):
    import numpy as np
    c = (np.arange(n) + 0.5) / n * 2 - 1
    x, y = np.meshgrid(c, -c)  # y up
    return x, y


def write_stud_overlay():
    """One stud per tile. White highlights / black shadows in RGB, strength in
    alpha. Used as a SurfaceAppearance (AlphaMode = Overlay) ColorMap, so the
    MeshPart's Color shows through and gets the stud relief on top."""
    import numpy as np
    n = STUD_TILE_PX
    x, y = grid(n)
    d = np.sqrt(x * x + y * y)
    rgba = np.zeros((n, n, 4), dtype=np.float32)
    light = (-x + y) / np.sqrt(2)  # +1 toward top-left
    # Drop shadow down-right of the stud.
    sd = np.sqrt((x - 0.09) ** 2 + (y + 0.09) ** 2)
    shadow = (sd < 0.62) & (d >= 0.58)
    rgba[shadow, 3] = 0.32
    # Stud rim: lit top-left, dark bottom-right.
    rim = (d >= 0.47) & (d < 0.58)
    lit = rim & (light > 0)
    rgba[lit, :3] = 1.0
    rgba[lit, 3] = (0.18 + 0.3 * light[lit])
    dark = rim & (light <= 0)
    rgba[dark, 3] = 0.12 + 0.3 * (-light[dark])
    # Stud top: faint sheen.
    top = d < 0.47
    rgba[top, :3] = 1.0
    rgba[top, 3] = np.clip(0.06 + 0.1 * light[top], 0, 1)
    # Faint tile seam so large slabs read as brick-built.
    seam = (np.abs(x) > 0.96) | (np.abs(y) > 0.96)
    rgba[seam, :3] = 0.0
    rgba[seam, 3] = 0.1
    return save_rgba("StudOverlay", rgba)


def collect_manifest(label, objects, sockets):
    entry = {"parts": {}, "sockets": {}}
    for obj in objects.values():
        entry["parts"][obj.name] = {
            "color": obj.get("ColorHex", PALETTE.get(obj.get("PaletteKey", ""), "#FFFFFF")),
            "glow": obj.get("PaletteKey") in GLOW_PARTS,
            "tris": tri_count(obj),
            "group": obj.get("EggGroup"),
        }
    for s in sockets:
        c = sum((v.co for v in s.data.vertices), Vector()) / len(s.data.vertices)
        entry["sockets"][s.name] = [round(c.x, 3), round(c.y, 3), round(c.z, 3)]
    return entry




# ---------------------------------------------------------------------------
# 1. Mossbark Hatchet: smooth cartoon hero weapon (baked hand-painted look)
# ---------------------------------------------------------------------------
STEEL_DARK, STEEL_MID, STEEL_EDGE = "#5F6C7B", "#8E9DAD", "#E4ECF3"
WOOD_DARK, WOOD_MID = "#6B3E1F", "#9A5A2C"
LEATHER, LEATHER_DARK = "#4E9A3A", "#356F28"
BRASS, BRASS_DARK = "#B9822B", "#7A4E18"

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


HAFT_PATH = bezier((0, 0.0, 0.32), (0, 0.10, 1.5), (0, -0.16, 3.0), (0, 0.0, 4.5), 32)


def haft_point(z):
    """Point on the (slightly S-curved) haft centreline at height ~z."""
    best = min(HAFT_PATH, key=lambda p: abs(p.z - z))
    return best


def build_blade(sb):
    """Bearded axe blade as a Coons patch between four boundary curves:
    the socket (straight, at the haft), the cutting edge (convex arc with two
    small chips), the top (gentle arch) and the beard's concave underside.
    Thick at the socket, thin at the edge, with a slightly domed cheek."""
    top_socket, bottom_socket = Vector((-0.22, 4.38)), Vector((-0.22, 3.62))  # (y, z): blade extends to -y
    top_tip, beard_tip = Vector((-1.38, 4.78)), Vector((-1.22, 2.92))

    def quad(p0, p1, p2, t):
        return p0 * (1 - t) ** 2 + p1 * 2 * (1 - t) * t + p2 * t * t

    def socket(s):
        return top_socket.lerp(bottom_socket, s)

    def edge(s):
        p = quad(top_tip, Vector((-2.05, 4.05)), beard_tip, s)
        for chip_s, depth in ((0.58, 0.07), (0.74, 0.05)):  # a worn starter blade
            p.x += depth * math.exp(-((s - chip_s) / 0.025) ** 2)
        return p

    def top(r):
        p = top_socket.lerp(top_tip, r)
        return p + Vector((0, 0.1 * math.sin(math.pi * r)))

    def bottom(r):
        return quad(bottom_socket, Vector((-0.55, 3.5)), beard_tip, r)

    def patch(s, r):
        p = (top(r) * (1 - s) + bottom(r) * s + socket(s) * (1 - r) + edge(s) * r
             - (top_socket * (1 - s) * (1 - r) + top_tip * (1 - s) * r + bottom_socket * s * (1 - r) + beard_tip * s * r))
        return p

    def half_thickness(s, r):
        dome = 1.0 - 0.35 * (2 * s - 1) ** 2
        return (0.17 * (1 - r) ** 0.85 + 0.022) * dome

    def steel(r):
        if r > 0.84:
            return mix_hex(STEEL_MID, STEEL_EDGE, (r - 0.84) / 0.16)  # sharpened bright edge
        return mix_hex(STEEL_DARK, STEEL_MID, r / 0.84)

    ns, nr = 16, 10
    grid = {}
    for side in (1, -1):
        for i in range(ns + 1):
            for j in range(nr + 1):
                s, r = i / ns, j / nr
                p = patch(s, r)
                x = side * half_thickness(s, r)
                grid[(side, i, j)] = sb.bm.verts.new((x, p.x, p.y))
    face_r = {}
    for side in (1, -1):
        for i in range(ns):
            for j in range(nr):
                q = [grid[(side, i, j)], grid[(side, i, j + 1)], grid[(side, i + 1, j + 1)], grid[(side, i + 1, j)]]
                face = sb.bm.faces.new(q if side > 0 else list(reversed(q)))
                sb.paint(face, linear_rgba(steel((j + 0.5) / nr)), M_STEEL)
                face_r[face] = (j + 0.5) / nr
    # Close the rim: top, bottom, cutting edge and socket strips.
    for i in range(ns):
        for j_fixed in (0, nr):
            a, b = grid[(1, i, j_fixed)], grid[(1, i + 1, j_fixed)]
            c, d = grid[(-1, i + 1, j_fixed)], grid[(-1, i, j_fixed)]
            face = sb.bm.faces.new((a, d, c, b) if j_fixed == 0 else (a, b, c, d))
            sb.paint(face, linear_rgba(STEEL_EDGE if j_fixed == nr else STEEL_DARK), M_STEEL)
    for j in range(nr):
        for i_fixed in (0, ns):
            a, b = grid[(1, i_fixed, j)], grid[(1, i_fixed, j + 1)]
            c, d = grid[(-1, i_fixed, j + 1)], grid[(-1, i_fixed, j)]
            face = sb.bm.faces.new((a, b, c, d) if i_fixed == 0 else (a, d, c, b))
            sb.paint(face, linear_rgba(steel((j + 0.5) / nr)), M_STEEL)
    return top_tip, beard_tip, edge(0.5)


def wood_radius(base, z, seed):
    """Wood haft radius with gentle knots and an oval cross-section."""
    def fn(a):
        bump = 0.012 * noise.noise(Vector((math.cos(a) * 2, math.sin(a) * 2, z * 3.0 + seed)))
        knot = 0.03 * math.exp(-((z - 2.35) / 0.08) ** 2) * max(0.0, math.cos(a - 0.6)) ** 4
        return base * (1.0 + 0.07 * math.cos(2 * a)) + bump + knot
    return fn


def build_hatchet(scene, coll):
    head = SmoothBuilder()
    handle = SmoothBuilder()

    # --- Haft: wood, thicker at both ends, a small knot halfway --------------
    radii = []
    for p in HAFT_PATH:
        z = p.z
        base = 0.135 + 0.03 * math.exp(-((z - 0.4) / 0.35) ** 2) + 0.035 * max(0.0, (z - 3.3) / 1.2)
        radii.append(wood_radius(base, z, 3.1))
    handle.tube(HAFT_PATH, radii, sides=14, mask=M_WOOD,
                color_fn=lambda t, a: mix_hex(WOOD_DARK, WOOD_MID, 0.55 + 0.45 * math.sin(a * math.pi * 2 + t * 9) * 0.5))

    # --- Crossed leather wraps (two opposite helices) ----------------------
    for hand in (1, -1):
        pts, ups, aspect = [], [], []
        turns, z0, z1 = 2.6, 1.35, 2.75
        steps = 44
        for k in range(steps + 1):
            u = k / steps
            z = lerp(z0, z1, u)
            centre = haft_point(z)
            a = hand * u * turns * 2 * math.pi
            radial = Vector((math.cos(a), math.sin(a), 0))
            pts.append(Vector((centre.x, centre.y, z)) + radial * 0.158)
            ups.append(radial)
            aspect.append((0.03 / 0.1, 1.0))
        handle.tube(pts, [0.1] * len(pts), sides=8, ups=ups, aspect=aspect,
                    color=LEATHER if hand > 0 else LEATHER_DARK, mask=M_LEATHER)

    # --- Woven green band and brass collars --------------------------------
    for z0, z1, r, col, mask in ((3.24, 3.42, 0.2, LEATHER, M_LEATHER), (0.38, 0.62, 0.185, BRASS, M_BRASS)):
        c0, c1 = haft_point(z0), haft_point(z1)
        handle.tube([Vector((c0.x, c0.y, z0)), Vector((c1.x, c1.y, z1))], [r, r], sides=16,
                    color_fn=(lambda t, a, col=col: mix_hex(col, LEATHER_DARK if col == LEATHER else BRASS_DARK,
                                                         0.5 * (math.sin(a * 16) > 0))) if col == LEATHER else None,
                    color=col, mask=mask)
    for side in (1, -1):
        handle.sphere(Vector((side * 0.17, haft_point(0.5).y, 0.5)), 0.045, BRASS, M_BRASS)

    # --- Pommel cap and a little curved spike -------------------------------
    handle.tube([Vector((0, 0.0, 0.08)), Vector((0, 0.0, 0.2)), Vector((0, 0.0, 0.34))], [0.13, 0.2, 0.17], sides=16,
                color=BRASS, mask=M_BRASS)
    spike = bezier((0, 0.0, 0.1), (0, -0.04, -0.08), (0, -0.14, -0.2), (0, -0.28, -0.28), 8)
    handle.tube(spike, [0.1 * (1 - i / 8) + 0.008 for i in range(9)], sides=10, color=BRASS_DARK, mask=M_BRASS)

    # --- Head: blade, brass eye collar, rivets, poll, chain ring ------------
    top_tip, beard_tip, edge_mid = build_blade(head)
    head.tube([Vector((0, 0, 3.52)), Vector((0, 0, 3.6)), Vector((0, 0, 4.42)), Vector((0, 0, 4.5))],
              [0.25, 0.27, 0.27, 0.24], sides=18, color=BRASS, mask=M_BRASS)
    for z in (3.58, 4.44):  # darker rims at both ends of the eye collar
        head.tube([Vector((0, 0, z - 0.04)), Vector((0, 0, z + 0.04))], [0.285, 0.285], sides=18,
                  color=BRASS_DARK, mask=M_BRASS)
    for y, z in ((-0.42, 4.18), (-0.42, 3.86)):
        for side in (1, -1):
            head.sphere(Vector((side * 0.19, y, z)), 0.07, BRASS, M_BRASS, scale=(0.6, 1, 1))
    # Poll: a rounded steel block behind the eye.
    head.tube([Vector((0, 0.24, 4.0)), Vector((0, 0.46, 4.0))], [lambda a: 0.17 * (1 + 0.25 * abs(math.sin(a))), 0.14],
              sides=12, color=STEEL_DARK, mask=M_STEEL)
    # Chain ring + one hanging link.
    ring = [Vector((0, 0.62 + 0.17 * math.cos(2 * math.pi * k / 20), 4.0 + 0.17 * math.sin(2 * math.pi * k / 20)))
            for k in range(20)]
    head.tube(ring, [0.04] * 20, sides=8, closed=True, color=BRASS_DARK, mask=M_BRASS)
    link = [Vector((0.13 * math.cos(2 * math.pi * k / 20), 0.79, 3.62 + 0.2 * math.sin(2 * math.pi * k / 20)))
            for k in range(20)]
    head.tube(link, [0.035] * 20, sides=8, closed=True, color=BRASS_DARK, mask=M_BRASS)
    # Seat the head on the haft's curve.
    top_centre = haft_point(4.0)
    head_obj = head.to_object(coll, "Head")
    head_obj.location = (top_centre.x, top_centre.y, 0)
    handle_obj = handle.to_object(coll, "Handle")

    objects = {"Handle": handle_obj, "Head": head_obj}
    for obj in objects.values():
        smooth_and_bake(scene, obj, "MossbarkHatchet_" + obj.name)

    off = Vector((top_centre.x, top_centre.y, 0))
    sockets = [
        add_socket(coll, "Tip", Vector((0, edge_mid.x - 0.05, edge_mid.y)) + off),
        add_socket(coll, "TrailTop", Vector((0, top_tip.x, top_tip.y)) + off),
        add_socket(coll, "TrailBottom", Vector((0, beard_tip.x, beard_tip.y)) + off),
    ]
    return objects, sockets


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
# 2. Mossbark Egg (blocky, Common)
# ---------------------------------------------------------------------------
EGG_BASE_Z = 0.0  # the egg sits straight on the ground
EGG_HEIGHT = 4.0
EGG_RADIUS = 1.6


def egg_radius(t):
    s = 2 * t - 1
    return EGG_RADIUS * math.sqrt(max(0.0, 1 - s * s)) * (1 - 0.16 * s)


def egg_surface(t, a, out=0.0):
    r = egg_radius(t) + out
    return Vector((math.cos(a) * r, math.sin(a) * r, EGG_BASE_Z + t * EGG_HEIGHT))


def build_mossbark_egg(coll):
    rng = random.Random(SEED + 3)
    shell = PartBuilder()

    layers = 11
    for i in range(layers):
        t = (i + 0.5) / layers
        r = egg_radius(t)
        z = EGG_BASE_Z + t * EGG_HEIGHT
        part = "EggShellLight" if i % 3 == 1 else "EggShell"
        thickness = EGG_HEIGHT / layers * 1.04
        for w, d, depth in ((2.0, 1.25, 1.0), (1.25, 2.0, 0.86), (1.68, 1.68, 0.74)):
            shell.box(part, (0, 0, z), (r * w, r * d, thickness * depth))

    # Moss-leaf cap draping from the top.
    for ring_i, t in enumerate((0.93, 0.82, 0.71)):
        count = 8 + ring_i * 3
        for k in range(count):
            a = 2 * math.pi * (k + 0.5 * ring_i) / count + rng.uniform(-0.1, 0.1)
            radial = Vector((math.cos(a), math.sin(a), 0))
            normal = (radial + Vector((0, 0, 0.9 - ring_i * 0.3))).normalized()
            part = rng.choice(("EggLeaf", "EggLeaf", "EggLeafLight", "EggMoss"))
            fur_plate(shell, egg_surface(t, a, -0.08), normal, Vector((0, 0, -1)), rng, rng.uniform(0.7, 0.95),
                      rng.uniform(0.8, 1.3) + ring_i * 0.2, part, thickness=0.2, lift=(5, 14), spin=10)

    # Sprout: a curved stem with two leaves.
    top = Vector((0, 0, EGG_BASE_Z + EGG_HEIGHT - 0.05))
    stem = bezier(top, top + Vector((0, 0, 0.4)), top + Vector((0.15, 0.05, 0.7)), top + Vector((0.3, 0.05, 0.95)), 4)
    shell.chain("EggSprout", stem, [0.22, 0.2, 0.18, 0.16], roll_hint=(1, 0, 0))
    for side, part in ((1, "EggLeafLight"), (-1, "EggLeaf")):
        rot = basis_from_y(Vector((side * 0.9, 0.0, 0.45)), (0, 1, 0.3))
        shell.box(part, stem[-1] + rot @ Vector((0, 0.38, 0)), (0.42, 0.8, 0.1), rot, taper=(0.35, 1.0))

    # A tiny Amanita growing out of the shell.
    a, t = 0.7, 0.32
    base = egg_surface(t, a, -0.1)
    out = Vector((math.cos(a), math.sin(a), 0.55)).normalized()
    shell.box("EggShroomSpots", base + out * 0.25, (0.24, 0.5, 0.24), basis_from_y(out, (0, 0, 1)))
    cap_centre = base + out * 0.55
    shell.blob("EggShroom", cap_centre, (0.42, 0.2, 0.42), step=0.13, rot=basis_from_y(out, (0, 0, 1)),
               profile=lambda u: math.sqrt(max(0.0, 1 - ((u + 1) / 2) ** 2)))
    for k in range(4):
        aa = k * math.pi / 2 + 0.4
        side = out.orthogonal().normalized()
        d = Matrix.Rotation(aa, 3, out) @ side
        spot_pos = cap_centre + out * 0.12 + d * 0.26
        shell.box("EggShroomSpots", spot_pos, (0.12, 0.12, 0.06), basis(out * 0.6 + d * 0.8, out))

    objects = shell.to_objects(coll)
    assign_materials(objects)
    sockets = [
        add_socket(coll, "EggCenter", (0, 0, EGG_BASE_Z + EGG_HEIGHT * 0.45)),
        add_socket(coll, "Crown", stem[-1] + Vector((0, 0, 0.5))),
        add_socket(coll, "Ground", (0, 0, 0.05)),  # base centre: the egg rocks and hatches around this
    ]
    return objects, sockets


# ---------------------------------------------------------------------------
# 3. Mosscap Toad (blocky, Common)
# ---------------------------------------------------------------------------
def build_mosscap_toad(coll):
    rng = random.Random(SEED + 7)
    b = PartBuilder()
    vertical = basis_from_y((0, 0, 1), (0, 1, 0))  # blob slices stacked upwards
    dome = lambda u: math.sqrt(max(0.0, 1 - ((u + 1) / 2) ** 2))  # noqa: E731  (flat bottom, round top)

    # Chubby body and a wide head bulge.
    b.blob("ToadBody", (0, 0.15, 1.7), (1.9, 1.45, 1.75), step=0.4, rot=vertical)
    b.blob("ToadBody", (0, -0.85, 2.35), (1.65, 1.0, 1.2), step=0.36, rot=vertical)
    b.blob("ToadBelly", (0, -1.3, 1.4), (1.3, 0.85, 0.5), step=0.34, rot=vertical)

    # Big eyes on top with lids, pupils and glints.
    for side in (-1, 1):
        x = side * 0.82
        b.blob("ToadBody", (x, -0.95, 2.98), (0.66, 0.5, 0.58), step=0.3, rot=vertical)
        b.blob("ToadEyes", (x, -1.18, 3.2), (0.56, 0.52, 0.5), step=0.26, rot=vertical)
        b.box("ToadPupils", (x * 1.02, -1.66, 3.24), (0.4, 0.1, 0.48))
        b.box("ToadEyes", (x * 1.02 - side * 0.1, -1.72, 3.38), (0.13, 0.06, 0.13))
        b.box("ToadCheeks", (side * 1.12, -1.9, 2.32), (0.44, 0.08, 0.26))
    # Little smile.
    b.box("ToadMouth", (0, -2.07, 2.12), (0.8, 0.08, 0.1))
    for side in (-1, 1):
        b.box("ToadMouth", (side * 0.55, -2.04, 2.19), (0.42, 0.08, 0.1), euler_deg(0, -side * 20, 0))

    # Folded back legs and stubby front legs with toes.
    for side in (-1, 1):
        b.blob("ToadBody", (side * 1.55, 0.55, 0.85), (0.66, 1.05, 0.58), step=0.3)
        b.box("ToadToes", (side * 1.7, -0.5, 0.16), (0.95, 0.75, 0.32))
        b.blob("ToadBody", (side * 0.98, -1.45, 0.55), (0.38, 0.55, 0.38), step=0.25, rot=vertical)
        b.box("ToadToes", (side * 1.0, -1.72, 0.13), (0.78, 0.62, 0.26))
        for k, foot in enumerate(((side * 1.7, -0.95), (side * 1.0, -2.07))):
            for t in (-1, 0, 1):
                b.box("ToadToes", (foot[0] + t * 0.24, foot[1] - k * 0.0, 0.13), (0.2, 0.32, 0.22))

    # Amanita cap: red dome, cream gills underneath, white warts.
    cap_c = Vector((0, -0.25, 3.62))
    b.box("ToadBelly", cap_c + Vector((0, 0, -0.62)), (0.7, 0.7, 0.5))  # stem
    b.box("ToadBelly", cap_c + Vector((0, 0, -0.5)), (2.1, 2.1, 0.12))  # gills
    b.blob("ToadCap", cap_c, (1.3, 0.55, 1.3), step=0.18, rot=vertical, profile=dome)
    for k in range(10):
        a = 2 * math.pi * k / 10 + rng.uniform(-0.2, 0.2)
        f = rng.uniform(0.15, 0.75) if k else 0.95
        r = 1.3 * 0.95 * math.sqrt(max(0.0, 1 - f * f))
        p = cap_c + Vector((math.cos(a) * r, math.sin(a) * r, -0.55 + f * 1.1))
        normal = Vector((math.cos(a) * (1 - f), math.sin(a) * (1 - f), f + 0.2)).normalized()
        b.box("ToadSpots", p + normal * 0.06, (0.3, 0.3, 0.12), basis(normal, (0, 1, 0)))

    # Moss tufts down the back.
    for k in range(7):
        a = -0.9 + k * 0.3
        anchor = Vector((math.sin(a) * 1.2, 0.7 + abs(a) * 0.2, 2.95 - abs(a) * 0.4))
        fur_plate(b, anchor, Vector((math.sin(a), 0.4, 1)), Vector((math.sin(a) * 0.5, 1, -0.7)), rng,
                  0.55, rng.uniform(0.8, 1.1), "ToadMoss", thickness=0.16, lift=(8, 18))

    objects = b.to_objects(coll)
    assign_materials(objects)
    sockets = [
        add_socket(coll, "Head", cap_c + Vector((0, 0, 0.8))),
        add_socket(coll, "Mouth", (0, -2.15, 2.1)),
        add_socket(coll, "Back", (0, 0.9, 3.0)),
        add_socket(coll, "Feet", (0, -0.3, 0.1)),
    ]
    return objects, sockets


# ---------------------------------------------------------------------------
# 4. VFX: this set's textures and the egg's hatch shards
# ---------------------------------------------------------------------------
def write_set_textures():
    import numpy as np
    rng = np.random.default_rng(SEED)
    n = 256
    x, y = grid(n)
    r = np.sqrt(x * x + y * y)
    out = {}
    # Spore: soft dot with a faint ring, drifting forest spores.
    spore = np.exp(-(r / 0.16) ** 2) + 0.35 * np.exp(-((r - 0.42) / 0.07) ** 2) + 0.25 * np.exp(-(r / 0.5) ** 2)
    out["Spore"] = save_rgba("Spore", white_alpha(spore))

    def pixel_art(rows):
        g = np.array([[1.0 if ch == "#" else (0.55 if ch == "+" else 0.0) for ch in row] for row in rows], dtype=np.float32)
        return np.kron(g, np.ones((n // g.shape[0], n // g.shape[1]), dtype=np.float32))

    out["LeafBit"] = save_rgba("LeafBit", white_alpha(pixel_art([
        "................",
        "...........##...",
        ".........#####..",
        ".......#######..",
        "......########..",
        ".....#####+###..",
        "....#####+####..",
        "....####+#####..",
        "...####+#####...",
        "...###+#####....",
        "...##+#####.....",
        "...#+####.......",
        "..#+.##.........",
        ".#+.............",
        "#...............",
        "................",
    ])))
    dust = np.zeros_like(r)
    for _ in range(18):
        cx, cy = rng.uniform(-0.4, 0.4, 2)
        s = rng.uniform(0.15, 0.3)
        dust += rng.uniform(0.4, 0.8) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (s * s)))
    dust = np.clip(dust / dust.max() * 1.2, 0, 1) * np.clip(1.1 - r, 0, 1) ** 1.4
    out["DustPuff"] = save_rgba("DustPuff", white_alpha(dust))

    # Weapon swing trail: bright head on the left, soft lengthwise streaks.
    w, h = 256, 64
    u = np.linspace(0, 1, w)[None, :]
    v = np.linspace(-1, 1, h)[:, None]
    lanes = np.zeros((h, 1))
    for _ in range(5):
        lanes += rng.uniform(0.3, 0.8) * np.exp(-((v - rng.uniform(-0.6, 0.6)) / rng.uniform(0.06, 0.15)) ** 2)
    breakup = 0.55 + 0.45 * np.clip(lanes, 0, 1) ** (0.6 + 1.6 * u)
    out["SwingStreak"] = save_rgba("SwingStreak", white_alpha((1 - u) ** 1.4 * np.exp(-(v / 0.6) ** 2) * breakup))
    log("Wrote %d set textures" % len(out))
    return out


def build_hatch_shards(coll):
    rng = random.Random(SEED + 31)
    objects = {}
    for i in range(10):
        sb = PartBuilder()
        part = ("EggShell", "EggShellLight", "EggLeaf")[i % 3]
        size = rng.uniform(0.55, 0.9)
        for _ in range(rng.randint(2, 3)):
            off = Vector((rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25), rng.uniform(-0.15, 0.15))) * size
            sb.box(part, off, (size * rng.uniform(0.5, 0.9), size * rng.uniform(0.5, 0.9), 0.24),
                   euler_deg(0, 0, rng.uniform(-20, 20)))
        made = sb.to_objects(coll, name_prefix="EggShard%02d_" % (i + 1))
        for obj in made.values():
            obj.data.materials.append(material_for(part))
            obj.location = ((i % 5) * 1.3 - 2.6, 4 + (i // 5) * 1.3, 0.3)
            objects[obj.name] = obj
    return objects


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log("Blender %s - building %s" % (bpy.app.version_string, SET_NAME))
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    write_stud_overlay()
    manifest = {"palette": PALETTE, "stud_texture": "Textures/StudOverlay.png"}

    if BUILD_AXE:
        scene, coll = make_scene("MossbarkHatchet")
        objects, sockets = build_hatchet(scene, coll)
        check_budget(objects, "MossbarkHatchet")
        manifest["MossbarkHatchet"] = collect_manifest("MossbarkHatchet", objects, sockets)
        export_glb(scene, list(objects.values()) + sockets, os.path.join(OUTPUT_DIR, "MossbarkHatchet.glb"))
        setup_preview(scene, coll, target=(0, -0.4, 2.4), distance=9.5, height=1.6, angle_deg=-50, ground=False,
                      size=(800, 1000), background="#6E7480")
        render_preview(scene, "MossbarkHatchet.png")
        orbit_camera(scene, (0, -0.4, 2.4), 9.5, 2.0, 130)
        render_preview(scene, "MossbarkHatchet_back.png")

    if BUILD_EGG:
        scene, coll = make_scene("MossbarkEgg")
        objects, sockets = build_mossbark_egg(coll)
        check_budget(objects, "MossbarkEgg")
        manifest["MossbarkEgg"] = collect_manifest("MossbarkEgg", objects, sockets)
        export_glb(scene, list(objects.values()) + sockets, os.path.join(OUTPUT_DIR, "MossbarkEgg.glb"))
        setup_preview(scene, coll, target=(0, 0, 2.2), distance=14, height=2.6, angle_deg=-30, size=(900, 900))
        render_preview(scene, "MossbarkEgg.png")

    if BUILD_MONSTER:
        scene, coll = make_scene("MosscapToad")
        objects, sockets = build_mosscap_toad(coll)
        check_budget(objects, "MosscapToad")
        manifest["MosscapToad"] = collect_manifest("MosscapToad", objects, sockets)
        export_glb(scene, list(objects.values()) + sockets, os.path.join(OUTPUT_DIR, "MosscapToad.glb"))
        setup_preview(scene, coll, target=(0, -0.4, 2.0), distance=14, height=3.2, angle_deg=-35, size=(900, 900))
        render_preview(scene, "MosscapToad.png")

    manifest["textures"] = {k: "Textures/%s.png" % k for k in write_set_textures()}
    scene, coll = make_scene("MossbarkVFX")
    shards = build_hatch_shards(coll)
    export_glb(scene, list(shards.values()), os.path.join(OUTPUT_DIR, "MossbarkVFXMeshes.glb"))

    scene = work_scene()
    for child in scene.collection.children:
        set_collection_visible(scene, child, child.name == "MosscapToad_Parts")
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
