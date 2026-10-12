"""
GenerateBestiary.py  -  Blender 4.x
"+1 Chop Mushrooms for Eggs": every egg and monster in the game, blocky stud style

Builds 7 eggs and 34 monsters (the Mossbark Egg, Mosscap Toad, Celestial/
Frostmane Egg and Frostmane Wyrm already exist in GenerateStarterSet.py and
GenerateFrostmaneSet.py):

  Fernleaf Egg      Fernling Snail, Leafwing Beetle, Thornback Hedgehog, Elderfern Treant
  Toadstool Egg     Spotcap Frog, Puffball Bunny, Sporecloak Fox, Toadstool Titan
  Crystal Egg       Quartzpaw Kit, Amethyst Moth, Prismhorn Ram, Geodeback Tortoise
  Geode Egg         Shardling Mole, Druzy Lynx, Gemhorn Rhino, Prismatic Basilisk
  Lava Egg          Cinderpaw Pup, Magmashell Crab, Emberwing Drake, Obsidian Colossus
  Obsidian Egg      Ashen Imp, Slagback Boar, Basalt Wyvern, Molten Behemoth
  Void Egg          Voidmote Wisp, Gloomfang Wolf, Nullhorn Beast, Abyssbone Leviathan
  (Mossbark Egg)    Twigroot Boar, Barkhorn Stag, Oakheart Golem
  (Celestial Egg)   Starfrost Owl, Glacierhorn Elk, Frostroot Wyrmling

Complexity follows rarity (master brief 4a): Commons are plain, cute slab
bodies, and each rarity step adds texture: plates, patterns, coats, crystals,
then glowing Glass/Neon parts. Size grows with rarity too. Eggs sit straight on
the ground (no nest) and get more decorated the rarer they are.

Output: ~/Documents/Bestiary/
  Family_<Egg>.glb     one file per egg family (egg + its monsters, side by side).
                       Studio's CreatureKit.Unpack splits it back into one Model per asset.
  Previews/<Asset>.png and Previews/Family_<Egg>.png (contact sheets)
  Textures/            StudOverlay, Ember, VoidWisp, Glint
  BestiaryData.lua     per-asset part colours/looks, sockets and your game stats;
                       paste into ReplicatedStorage.BestiaryData
  Bestiary.blend, Bestiary_Manifest.json

Run: Blender Text Editor -> Run Script (Alt+P), or
     blender --background --python GenerateBestiary.py
Building everything with previews takes a while (Blender looks frozen; that's
normal). Set ONLY = ["Lava"] (family) or ["CinderpawPup"] (asset) to build part.
"""

import bpy  # noqa: I001  (bpy first: bmesh/mathutils need it loaded outside Blender's UI)
import bmesh
import json
import math
import os
import random
import traceback
import zlib
from mathutils import Matrix, Vector, noise

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SET_NAME = "Bestiary"
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", SET_NAME)
TEXTURE_DIR = os.path.join(OUTPUT_DIR, "Textures")
PREVIEW_DIR = os.path.join(OUTPUT_DIR, "Previews")
LOG_NAME = SET_NAME + "_Log"

ONLY = []  # e.g. ["Lava"] or ["CinderpawPup", "VoidEgg"]; empty = everything
RENDER_PREVIEWS = True
PREVIEW_SIZE = 560
PREVIEW_SAMPLES = 16
FACE_POSITIVE_Y = False
SEED = 23

MAX_TRIS_PER_PART = 20000
STUD_TILE_PX = 128
STUDS_PER_UNIT = 2.0

# Used by the shared helper code; per-asset colours live in each asset's spec.
PALETTE = {}
GLOW_PARTS = set()
NO_STUD_PARTS = set()

RARITY_DETAIL = {"Common": 0, "Uncommon": 1, "Rare": 2, "Epic": 3, "Legendary": 4,
                 "Mythic": 5, "Divine": 6, "Secret": 7, "Celestial": 5}
RARITY_SCALE = {"Common": 1.0, "Uncommon": 1.12, "Rare": 1.28, "Epic": 1.5, "Legendary": 1.8,
                "Mythic": 2.15, "Divine": 2.5, "Secret": 3.0, "Celestial": 1.3}

DEFAULT_COLORS = {"Eyes": "#FFFFFF", "Pupils": "#1B1B1B", "Mouth": "#2A1A12", "Cheeks": "#FF8FA3"}


def look_of(role):
    """Studio look for a part role: Neon glows, Glass is translucent, Smooth
    has no studs, Plastic gets the stud overlay."""
    if "Glow" in role:
        return "Neon"
    if "Glass" in role:
        return "Glass"
    if role in ("Eyes", "Pupils", "Mouth", "Cheeks", "Iris"):
        return "Smooth"
    return "Plastic"


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
    """Tiny tetra marker. Studio turns it into an Attachment (FrostmaneVFX.lua)."""
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
        if obj.data.materials and not obj.get("IsSocket"):
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


def setup_preview(scene, coll, target, distance, height, angle_deg, lens=50, ground=True, size=(1100, 820)):
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
    bg.inputs["Color"].default_value = linear_rgba("#BFE3FF")
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




# ---------------------------------------------------------------------------
# Creature construction kit
# ---------------------------------------------------------------------------
class ScaledBuilder(PartBuilder):
    """PartBuilder that designs in 'creature units' and scales everything by
    `s` while building. Stud UVs are computed after scaling, so studs keep the
    same real size on small and huge creatures."""

    def __init__(self, s):
        super().__init__()
        self.s = s

    def box(self, part, center, size, rot=None, taper=(1.0, 1.0)):
        super().box(part, Vector(center) * self.s, tuple(v * self.s for v in size), rot, taper)

    def crystal(self, part, base, direction, length, radius, sides=6, twist=0.0):
        super().crystal(part, Vector(base) * self.s, direction, length * self.s, radius * self.s, sides, twist)


class Ctx:
    """Everything one asset is built with: builder, colours, detail level,
    randomness and sockets (all in unscaled creature units)."""

    def __init__(self, spec):
        self.spec = spec
        self.asset = spec["asset"]
        self.rarity = spec["rarity"]
        self.D = RARITY_DETAIL[self.rarity]
        self.s = spec.get("scale", RARITY_SCALE[self.rarity])
        self.colors = dict(DEFAULT_COLORS)
        self.colors.update(spec["colors"])
        self.b = ScaledBuilder(self.s)
        self.rng = random.Random(zlib.crc32(self.asset.encode()) + SEED)  # stable across runs
        self.sockets = {}

    def socket(self, name, pos):
        self.sockets[name] = Vector(pos)

    def pick(self, *roles):
        return self.rng.choice(roles)


def ell(c, role, center, radii, step=0.32, vertical=False, profile=None, rot=None):
    """Rounded blocky mass. vertical=True stacks slices upwards: radii are
    then (x, height, depth). Otherwise slices run along Y: (x, length, height)."""
    if rot is None and vertical:
        rot = basis_from_y((0, 0, 1), (0, 1, 0))
    c.b.blob(role, center, radii, step=step, rot=rot, profile=profile)


DOME = lambda u: math.sqrt(max(0.0, 1 - ((u + 1) / 2) ** 2))  # noqa: E731  flat bottom, round top


def surf(center, radii, theta, t):
    """Point and normal on an ellipsoid. theta: 0 top, +-pi/2 flanks, pi bottom;
    t: -1 front .. +1 back (along Y). radii = (x, y, z)."""
    rx, ry, rz = radii
    k = math.sqrt(max(0.0, 1.0 - t * t))
    off = Vector((math.sin(theta) * rx * k, t * ry, math.cos(theta) * rz * k))
    n = Vector((off.x / (rx * rx), off.y / (ry * ry), off.z / (rz * rz))).normalized()
    return Vector(center) + off, n


def cute_eyes(c, x, y, z, size=0.4, glow=False, role="Eyes", iris=None):
    """Big friendly eyes on a front face at depth y (front = -Y)."""
    for side in (-1, 1):
        px = side * x
        if glow:
            c.b.box("EyeGlow", (px, y - 0.02, z), (size * 1.05, 0.12, size * 0.75))
            continue
        c.b.box(role, (px, y, z), (size, 0.12, size * 1.15))
        if iris:
            c.b.box(iris, (px, y - 0.04, z - size * 0.05), (size * 0.72, 0.1, size * 0.82))
        c.b.box("Pupils", (px, y - 0.07, z - size * 0.08), (size * 0.48, 0.1, size * 0.64))
        c.b.box(role, (px - side * size * 0.14, y - 0.11, z + size * 0.18), (size * 0.17, 0.06, size * 0.17))


def smile(c, y, z, width=0.6):
    c.b.box("Mouth", (0, y, z), (width * 0.6, 0.08, 0.08))
    for side in (-1, 1):
        c.b.box("Mouth", (side * width * 0.42, y + 0.02, z + 0.05), (width * 0.32, 0.08, 0.08), euler_deg(0, -side * 22, 0))


def chain_curve(c, role, p0, p1, p2, p3, r0, r1, n=6, up=(0, 0, 1), taper=(0.5, 0.5)):
    pts = bezier(p0, p1, p2, p3, n)
    sizes = [r0 + (r1 - r0) * i / max(1, n - 1) for i in range(n)]
    c.b.chain(role, pts, sizes, roll_hint=up, taper_last=taper)
    return pts


def plates_on(c, roles, center, radii, rows, per_row, theta=(-1.9, 1.9), tspan=(-0.85, 0.85),
              size=(1.0, 1.4), drape=(0, 0.5, -1), thickness=0.18, lift=(6, 18)):
    """Draped slab coat (fur, scales, leaves, armour) over an ellipsoid."""
    rng = c.rng
    for r in range(rows):
        t = tspan[0] + (tspan[1] - tspan[0]) * (r / max(1, rows - 1))
        for j in range(per_row):
            th = theta[0] + (theta[1] - theta[0]) * (j / max(1, per_row - 1)) + rng.uniform(-0.08, 0.08)
            p, n = surf(center, radii, th, t + rng.uniform(-0.03, 0.03))
            d = Vector(drape)
            if abs(th) < 0.3:
                d = Vector((math.copysign(0.6, th if th else 1), 0.9, -0.2))
            role = roles[(r + j) % len(roles)] if len(roles) > 1 and rng.random() < 0.7 else rng.choice(roles)
            fur_plate(c.b, p, n, d, rng, size[0] * rng.uniform(0.85, 1.15), size[1] * rng.uniform(0.85, 1.15),
                      role, thickness=thickness, lift=lift, spin=10)


def spikes_on(c, role, center, radii, count, length, radius, theta=(-1.2, 1.2), tspan=(-0.8, 0.85),
              tip_role=None, back_tilt=0.5, crystal=False):
    rng = c.rng
    for i in range(count):
        th = rng.uniform(*theta)
        t = rng.uniform(*tspan)
        p, n = surf(center, radii, th, t)
        d = (n + Vector((0, back_tilt, 0))).normalized()
        ln = length * rng.uniform(0.75, 1.2)
        if crystal:
            c.b.crystal(role, p - n * 0.05, d, ln, radius)
        else:
            rot = basis_from_y(d, Vector((0, 0, 1)).cross(d) if abs(d.z) < 0.95 else (1, 0, 0))
            c.b.box(role, p + d * ln * 0.45, (radius, ln, radius), rot, taper=(0.15, 0.15))
            if tip_role:
                c.b.box(tip_role, p + d * ln * 0.92, (radius * 0.35, ln * 0.18, radius * 0.35), rot, taper=(0.2, 0.2))


def spots_on(c, role, center, radii, count, size, theta=(-1.3, 1.3), tspan=(-0.8, 0.8), out=0.04):
    rng = c.rng
    for _ in range(count):
        p, n = surf(center, radii, rng.uniform(*theta), rng.uniform(*tspan))
        s = size * rng.uniform(0.7, 1.25)
        c.b.box(role, p + n * out, (s, s, s * 0.35), basis(n, (0, 1, 0) if abs(n.y) < 0.9 else (1, 0, 0)))


def cracks_on(c, role, center, radii, count, segs=5, width=0.12, theta=(-1.7, 1.7), tspan=(-0.8, 0.8)):
    """Zig-zag glowing seams (magma, runes, crystal veins) on an ellipsoid."""
    rng = c.rng
    for _ in range(count):
        th = rng.uniform(*theta)
        t = rng.uniform(*tspan)
        prev, n = surf(center, radii, th, t)
        for _ in range(segs):
            th += rng.uniform(-0.25, 0.25)
            t += rng.choice((-1, 1)) * rng.uniform(0.06, 0.14)
            t = max(-0.95, min(0.95, t))
            cur, n = surf(center, radii, th, t)
            d = cur - prev
            if d.length > 1e-3:
                c.b.box(role, (prev + cur) / 2 + n * 0.03, (width, d.length * 1.15, width * 0.7), basis_from_y(d, n))
            prev = cur


def crystals(c, role, base, up, size=1.0, count=3, alt_role=None, alt_chance=0.3):
    crystal_cluster(c.b, base, up, c.rng, size=size, count=count, violet_chance=alt_chance if alt_role else 0.0,
                    part=role, violet_part=alt_role or role)


def leaf(c, role, base, direction, length=0.8, width=0.45, vein=None):
    d = Vector(direction).normalized()
    up = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((0, 1, 0))
    rot = basis_from_y(d, up)
    c.b.box(role, Vector(base) + d * length * 0.5, (width, length, 0.08), rot, taper=(0.25, 1.0))
    if vein:
        c.b.box(vein, Vector(base) + d * length * 0.45, (0.06, length * 0.85, 0.1), rot, taper=(0.4, 1.0))


def frond(c, role, base, p1, p2, tip, leaflets=5, size=0.45, alt=None):
    """Curling fern frond: a stem chain with paired leaflets shrinking to the tip."""
    pts = bezier(base, p1, p2, tip, leaflets + 1)
    c.b.chain(role, pts, [0.12] * (leaflets + 1), roll_hint=(0, 0, 1))
    for i in range(1, leaflets + 1):
        d = (pts[min(i + 1, leaflets)] - pts[i - 1]).normalized()
        side_axis = d.cross(Vector((0, 0, 1)))
        if side_axis.length < 1e-3:
            side_axis = Vector((1, 0, 0))
        side_axis.normalize()
        k = 1.0 - i / (leaflets + 1) * 0.6
        for s in (-1, 1):
            leaf(c, alt if (alt and i % 2) else role, pts[i], side_axis * s + d * 0.35, length=size * k, width=size * 0.45 * k)


def legs4(c, role, paw_role, W, L, leg_h, leg_r, stance=0.32, spread=0.3, toes=None, y_off=0.0):
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * W * stance, sy * L * spread + y_off
            ell(c, role, (x, y, leg_h / 2 + 0.06), (leg_r, leg_h / 2 + 0.1, leg_r), step=0.24, vertical=True)
            c.b.box(paw_role, (x, y - 0.05, 0.11), (leg_r * 2.3, leg_r * 2.5, 0.24))
            if toes:
                for t in (-1, 0, 1):
                    c.b.box(toes, (x + t * leg_r * 0.62, y - leg_r * 1.3, 0.1), (leg_r * 0.5, leg_r * 0.6, 0.2))


def quadruped(c, L=2.6, W=1.7, H=1.4, leg_h=0.9, leg_r=0.3, head_r=0.75, head_up=0.45, head_fwd=0.0,
              snout=(0.6, 0.45, 0.42), body="Body", belly="Belly", leg="Body", paw="Paw", snout_role="Snout",
              nose="Nose", eyes=None, mouth=True, stance=0.32, spread=0.3, neck=None, toes=None, head_role=None):
    """Four-legged creature facing -Y. Returns key anatomy points for features."""
    zb = leg_h + H / 2
    ell(c, body, (0, 0, zb), (W / 2, L / 2, H / 2), step=0.3)
    if belly:
        ell(c, belly, (0, -0.05, zb - H * 0.2), (W * 0.36, L * 0.4, H * 0.3), step=0.28)
    hy = -L / 2 - head_r * 0.35 - head_fwd
    hz = zb + head_up
    if neck:
        a = Vector((0, -L / 2 + 0.2, zb + H * 0.2))
        b_ = Vector((0, hy + head_r * 0.3, hz - head_r * 0.3))
        c.b.chain(body, [a, (a + b_) / 2 + Vector((0, 0, 0.1)), b_], [neck, neck * 0.85], roll_hint=(0, 0, 1))
    ell(c, head_role or body, (0, hy, hz), (head_r, head_r * 0.92, head_r * 0.95), step=0.24, vertical=True)
    sx, sy, sz = snout
    front = hy - head_r * 0.85
    if sy > 0:
        c.b.box(snout_role, (0, front - sy * 0.35, hz - head_r * 0.3), (sx, sy, sz))
        if nose:
            c.b.box(nose, (0, front - sy * 0.82, hz - head_r * 0.3 + sz * 0.22), (sx * 0.45, 0.12, sz * 0.32))
        if mouth:
            c.b.box("Mouth", (0, front - sy * 0.83, hz - head_r * 0.3 - sz * 0.22), (sx * 0.55, 0.08, 0.07))
    eyes = eyes or {}
    cute_eyes(c, head_r * 0.45, front + 0.04, hz + head_r * 0.15, size=eyes.get("size", head_r * 0.42),
              glow=eyes.get("glow", False), iris=eyes.get("iris"))
    legs4(c, leg, paw, W, L, leg_h, leg_r, stance, spread, toes)
    g = dict(zb=zb, hy=hy, hz=hz, L=L, W=W, H=H, head_r=head_r, front=front,
             body_c=Vector((0, 0, zb)), body_r=(W / 2, L / 2, H / 2), leg_h=leg_h)
    c.socket("Head", (0, hy, hz + head_r + 0.3))
    c.socket("Mouth", (0, front - sy, hz - head_r * 0.3))
    c.socket("Back", (0, L * 0.15, zb + H / 2 + 0.2))
    c.socket("Feet", (0, 0, 0.1))
    c.socket("Chest", (0, -L / 2, zb))
    return g


def ears(c, role, g, kind="pointy", size=0.5, inner=None, spread=0.55, tilt=15):
    hr, hy, hz = g["head_r"], g["hy"], g["hz"]
    for side in (-1, 1):
        base = Vector((side * hr * spread, hy + hr * 0.1, hz + hr * 0.8))
        if kind == "pointy":
            rot = euler_deg(-8, side * tilt, 0) @ basis_from_y((0, 0, 1), (0, -1, 0))
            c.b.box(role, base + Vector((0, 0, size * 0.45)), (size * 0.75, size, size * 0.3), rot, taper=(0.15, 0.6))
            if inner:
                c.b.box(inner, base + Vector((0, -size * 0.12, size * 0.4)), (size * 0.42, size * 0.7, size * 0.1), rot, taper=(0.15, 0.6))
        elif kind == "long":
            rot = euler_deg(-10, side * tilt, 0) @ basis_from_y((0, 0, 1), (0, -1, 0))
            c.b.box(role, base + Vector((side * 0.05, 0, size * 0.55)), (size * 0.38, size * 1.15, size * 0.18), rot, taper=(0.7, 1.0))
            if inner:
                c.b.box(inner, base + Vector((side * 0.05, -size * 0.08, size * 0.55)), (size * 0.2, size * 0.95, size * 0.1), rot, taper=(0.7, 1.0))
        else:  # round
            c.b.box(role, base + Vector((0, 0, size * 0.2)), (size * 0.7, size * 0.6, size * 0.25), euler_deg(-90, 0, 0))


def tail(c, role, start, mid1, mid2, end, r0, r1, n=6, tip=None, tip_size=None):
    pts = chain_curve(c, role, start, mid1, mid2, end, r0, r1, n=n)
    if tip:
        ell(c, tip, pts[-1], tip_size or (r1 * 1.6, r1 * 2.0, r1 * 1.6), step=0.2)
    return pts


def biped(c, torso=(1.5, 1.0, 1.6), hip_z=1.2, leg_r=0.38, leg_gap=0.42, arm_r=0.32, head_r=0.6, head_up=0.2,
          body="Body", limb="Body", hand="Hand", foot="Foot", head_role=None, eyes=None, arms_down=True,
          fist=0.42, mouth=True):
    """Upright creature (golems, treants, imps). Returns anatomy points."""
    tw, td, th = torso
    tz = hip_z + th / 2
    ell(c, body, (0, 0, tz), (tw / 2, th / 2, td / 2), step=0.3, vertical=True)
    hz = hip_z + th + head_r * 0.7 + head_up
    ell(c, head_role or body, (0, -td * 0.1, hz), (head_r, head_r * 0.95, head_r * 0.9), step=0.24, vertical=True)
    front = -td * 0.1 - head_r * 0.85
    eyes = eyes or {}
    cute_eyes(c, head_r * 0.42, front + 0.04, hz + head_r * 0.1, size=eyes.get("size", head_r * 0.38),
              glow=eyes.get("glow", False), iris=eyes.get("iris"))
    if mouth:
        smile(c, front + 0.02, hz - head_r * 0.42, width=head_r * 0.8)
    # Legs.
    for side in (-1, 1):
        x = side * leg_gap * tw / 1.5
        ell(c, limb, (x, 0, hip_z / 2 + 0.05), (leg_r, hip_z / 2 + 0.12, leg_r), step=0.24, vertical=True)
        c.b.box(foot, (x, -0.1, 0.13), (leg_r * 2.3, leg_r * 2.8, 0.26))
    # Arms.
    hands = []
    for side in (-1, 1):
        sh = Vector((side * (tw / 2 + arm_r * 0.4), 0, hip_z + th * 0.85))
        el = sh + Vector((side * 0.25, -0.15, -th * 0.45))
        hd = el + Vector((side * 0.1, -0.25, -th * 0.4 if arms_down else 0.1))
        c.b.chain(limb, [sh, el, hd], [arm_r * 2, arm_r * 1.8], roll_hint=(0, 0, 1))
        ell(c, hand, hd, (fist, fist, fist), step=0.22, vertical=True)
        hands.append(hd)
    g = dict(tz=tz, hz=hz, head_r=head_r, front=front, torso=torso, hip_z=hip_z, hands=hands,
             body_c=Vector((0, 0, tz)), body_r=(tw / 2, td / 2, th / 2))
    c.socket("Head", (0, 0, hz + head_r + 0.3))
    c.socket("Mouth", (0, front - 0.1, hz - head_r * 0.35))
    c.socket("Back", (0, td * 0.4, tz + th * 0.3))
    c.socket("Chest", (0, -td * 0.5, tz))
    c.socket("Feet", (0, 0, 0.1))
    return g


def wings(c, frame_role, membrane_role, root, span=2.4, height=1.4, back=0.6, fingers=3, tile=0.32, raise_deg=25,
          folded=False):
    """Bat/dragon wings: spars from a wrist with membrane tiles between them."""
    for side in (-1, 1):
        r = Vector((side * abs(root[0]), root[1], root[2]))
        lift = math.radians(raise_deg)
        wrist = r + Vector((side * span * 0.45, back * 0.3, height * 0.55))
        tips = []
        for f in range(fingers):
            a = f / max(1, fingers - 1)
            tips.append(wrist + Vector((side * span * (0.55 - 0.15 * a), back * (0.2 + 1.2 * a),
                                        height * (0.5 - 1.1 * a) + math.sin(lift) * 0.2)))
        if folded:
            tips = [r + (t - r) * 0.55 + Vector((0, 0.3, -0.2)) for t in tips]
            wrist = r + (wrist - r) * 0.6
        c.b.chain(frame_role, [r, (r + wrist) / 2, wrist], [0.2, 0.16], roll_hint=(0, 0, 1))
        for t in tips:
            c.b.chain(frame_role, [wrist, (wrist + t) / 2, t], [0.12, 0.08], roll_hint=(0, 0, 1), taper_last=(0.4, 0.4))
        trailing = r + Vector((side * 0.2, back * 1.4, -0.3))
        edges = [(r, wrist, r, tips[0])] + [(wrist, tips[i], wrist, tips[i + 1]) for i in range(len(tips) - 1)]
        edges.append((wrist, tips[-1], r + Vector((side * 0.1, back * 0.3, 0)), trailing))
        for a0, a1, b0, b1 in edges:
            nu, nv = 4, 3
            for iu in range(nu):
                for iv in range(nv):
                    u, v = (iu + 0.5) / nu, (iv + 0.5) / nv
                    pa, pb = a0.lerp(a1, u), b0.lerp(b1, u)
                    p = pa.lerp(pb, v)
                    du = a1.lerp(b1, v) - a0.lerp(b0, v)
                    dv = pb - pa
                    if dv.length < 0.2 or du.length < 0.2:
                        continue
                    normal = du.cross(dv).normalized()
                    rot = basis_from_y(du, normal)
                    w = dv.length / nv * 1.35 + 0.12
                    ln = du.length / nu * 1.35 + 0.12
                    c.b.box(membrane_role, p, (w, ln, 0.08), rot)
    return True


def dome_dots(c, role, center, rx, ry, count, size, fmin=0.1, fmax=0.85, out=0.05):
    """Dots (warts, spots, plates) on a DOME blob made by ell(..., vertical=True, profile=DOME)."""
    cx, cy, cz = center
    rng = c.rng
    for k in range(count):
        a = 2 * math.pi * k / count + rng.uniform(-0.25, 0.25)
        f = rng.uniform(fmin, fmax)
        r = rx * 0.95 * math.sqrt(max(0.0, 1 - f * f))
        p = Vector((cx + math.cos(a) * r, cy + math.sin(a) * r, cz - ry + 2 * ry * f))
        n = Vector((math.cos(a) * (1 - f), math.sin(a) * (1 - f), f + 0.25)).normalized()
        s = size * rng.uniform(0.8, 1.2)
        c.b.box(role, p + n * out, (s, s, s * 0.4), basis(n, (0, 1, 0)))


def slats_around(c, roles, center, rx, ry, z0, z1, count, width=0.45, depth=0.18, jitter=0.12):
    """Vertical slats around an upright torso (bark, stone ribs)."""
    for k in range(count):
        a = 2 * math.pi * k / count
        radial = Vector((math.cos(a), math.sin(a), 0))
        h = (z1 - z0) * c.rng.uniform(1 - jitter, 1)
        p = Vector(center) + Vector((math.cos(a) * rx, math.sin(a) * ry, 0)) + Vector((0, 0, z0 + h / 2 - center[2]))
        rot = basis(radial, (0, 0, 1))
        c.b.box(roles[k % len(roles)], p, (width, h, depth), rot)


def flat_wing(c, glass, vein, root, direction, length, width, lift=15, segs=5, spot=None):
    """Moth/beetle-style wing: overlapping slabs in a rounded leaf outline."""
    d = Vector(direction).normalized()
    side = Vector((0, 0, 1)).cross(d).normalized()
    up = d.cross(side).normalized()
    tilt = Matrix.Rotation(math.radians(lift), 3, d)
    for i in range(segs):
        u = (i + 0.5) / segs
        w = width * math.sin(math.pi * (0.15 + 0.85 * u)) + 0.15
        p = Vector(root) + d * (length * u)
        rot = basis_from_y(side, tilt @ up)
        c.b.box(glass, p, (length / segs * 1.25, w, 0.08), rot)
    c.b.box(vein, Vector(root) + d * length * 0.5, (length * 0.95, 0.07, 0.1), basis_from_y(d, tilt @ up))
    if spot:
        c.b.box(spot, Vector(root) + d * length * 0.62 + (tilt @ up) * 0.06, (0.32, 0.32, 0.1), basis(tilt @ up, d))


def antlers(c, role, g, spread=0.35, height=1.3, tines=2, tip_roles=None, glass=False, size=0.13):
    hy, hz, hr = g["hy"], g["hz"], g["head_r"]
    for side in (-1, 1):
        base = Vector((side * hr * spread, hy + 0.1, hz + hr * 0.8))
        pts = chain_curve(c, role, base, base + Vector((side * 0.35, 0.1, height * 0.4)),
                          base + Vector((side * 0.75, 0.35, height * 0.75)), base + Vector((side * 0.85, 0.55, height)),
                          size, size * 0.55, n=5)
        for k in range(tines):
            p = pts[1 + k * 2 if 1 + k * 2 < len(pts) else -2]
            tip = p + Vector((side * 0.15, -0.35, 0.45))
            c.b.chain(role, [p, (p + tip) / 2, tip], [size * 0.7, size * 0.5], roll_hint=(0, 0, 1), taper_last=(0.5, 0.5))
            if tip_roles:
                crystals(c, tip_roles[0], tip, Vector((0, -0.4, 1)), size=0.28, count=1) if glass else \
                    leaf(c, c.pick(*tip_roles), tip, (side * 0.4, -0.2, 1), length=0.45, width=0.3)
        if tip_roles:
            if glass:
                crystals(c, tip_roles[0], pts[-1], Vector((side * 0.3, 0.2, 1)), size=0.35, count=2)
            else:
                leaf(c, c.pick(*tip_roles), pts[-1], (side * 0.3, 0.3, 1), length=0.55, width=0.35)


def horns_curl(c, role, base_l, center_l, r0=0.55, r1=0.2, turns=1.4, size0=0.32, size1=0.1, n=12):
    """Ram-style spiral horn on the character's left (+X); mirrored on the right."""
    for side in (-1, 1):
        pts = []
        for i in range(n + 1):
            u = i / n
            a = u * turns * 2 * math.pi
            r = r0 + (r1 - r0) * u
            cx, cy, cz = center_l
            pts.append(Vector((side * (cx + 0.18 * u), cy + math.sin(a) * r, cz + math.cos(a) * r)))
        pts[0] = Vector((side * base_l[0], base_l[1], base_l[2]))
        c.b.chain(role, pts, [size0 + (size1 - size0) * i / n for i in range(n)], roll_hint=(1, 0, 0), taper_last=(0.5, 0.5))


# ---------------------------------------------------------------------------
# Mossbark family (Wood)
# ---------------------------------------------------------------------------
def twigroot_boar(c):
    g = quadruped(c, L=2.7, W=1.9, H=1.55, leg_h=0.65, leg_r=0.32, head_r=0.82, head_up=0.15,
                  snout=(0.8, 0.5, 0.55), stance=0.3, eyes={"size": 0.3})
    ears(c, "Body", g, "pointy", size=0.5, inner="Snout", tilt=35)
    for side in (-1, 1):
        base = Vector((side * 0.34, g["front"] - 0.3, g["hz"] - 0.5))
        chain_curve(c, "Tusk", base, base + Vector((side * 0.15, -0.15, 0.05)), base + Vector((side * 0.25, -0.2, 0.35)),
                    base + Vector((side * 0.2, -0.05, 0.55)), 0.17, 0.08, n=4)
    for i in range(6):
        p, n = surf(g["body_c"], g["body_r"], 0.0, -0.8 + i * 0.3)
        leaf(c, c.pick("Leaf", "LeafDark"), p - n * 0.08, (0, 0.55, 1), length=0.6, width=0.38)
    tail(c, "Twig", (0, 1.3, g["zb"] + 0.2), (0, 1.55, g["zb"] + 0.4), (0.2, 1.65, g["zb"] + 0.7), (0.05, 1.5, g["zb"] + 0.85), 0.1, 0.07, n=4)


def barkhorn_stag(c):
    g = quadruped(c, L=2.5, W=1.35, H=1.25, leg_h=1.55, leg_r=0.2, head_r=0.6, head_up=1.0, head_fwd=0.35,
                  snout=(0.42, 0.6, 0.4), neck=0.55, stance=0.3, spread=0.33, eyes={"size": 0.26}, paw="Hoof")
    ears(c, "Body", g, "pointy", size=0.45, inner="Belly", tilt=55)
    antlers(c, "Antler", g, spread=0.4, height=1.4, tines=2, tip_roles=("Leaf", "LeafLight"))
    plates_on(c, ["Bark", "Bark2"], g["body_c"], tuple(r + 0.04 for r in g["body_r"]), rows=3, per_row=5,
              theta=(-1.1, 1.1), tspan=(-0.6, 0.7), size=(0.6, 0.75), thickness=0.13, lift=(3, 9))
    spots_on(c, "Spots", g["body_c"], g["body_r"], 8, 0.2, theta=(-1.2, 1.2))
    c.b.box("Spots", (0, 1.3, g["zb"] + 0.35), (0.45, 0.35, 0.5), euler_deg(-30, 0, 0))


def oakheart_golem(c):
    g = biped(c, torso=(2.0, 1.3, 1.9), hip_z=1.1, leg_r=0.45, arm_r=0.38, head_r=0.62, head_up=0.0,
              body="Bark", limb="Bark", hand="BarkLight", foot="Root", eyes={"glow": True}, fist=0.5, mouth=False)
    slats_around(c, ["BarkLight", "Bark"], g["body_c"], 1.0, 0.66, g["hip_z"] + 0.1, g["hip_z"] + 1.85, 12, width=0.42)
    tz = g["tz"]
    c.b.box("BarkLight", (0, -0.72, tz + 0.2), (0.95, 0.2, 0.95))
    c.b.box("CoreGlow", (0, -0.8, tz + 0.2), (0.55, 0.16, 0.6))
    for side in (-1, 1):
        for k in range(3):
            fur_plate(c.b, Vector((side * (0.75 + k * 0.12), -0.1 + k * 0.2, g["hip_z"] + 1.9)), (side * 0.4, 0, 1),
                      (side, 0.2, -0.6), c.rng, 0.6, 0.8, c.pick("Moss", "Leaf"), thickness=0.14)
    for k in range(8):
        a = 2 * math.pi * k / 8
        leaf(c, c.pick("Leaf", "LeafLight"), (math.cos(a) * 0.35, -0.1 + math.sin(a) * 0.3, g["hz"] + 0.5),
             (math.cos(a) * 0.5, math.sin(a) * 0.5, 1), length=0.7, width=0.42)
    sh = Vector((0.95, 0.1, g["hip_z"] + 2.05))
    c.b.box("ShroomSpots", sh + Vector((0, 0, 0.15)), (0.18, 0.18, 0.3))
    ell(c, "Shroom", sh + Vector((0, 0, 0.42)), (0.32, 0.16, 0.32), step=0.08, vertical=True, profile=DOME)
    for side in (-1, 1):
        for t in (-1, 0, 1):
            f = Vector((side * 0.6 + t * 0.2, -0.3, 0.12))
            c.b.chain("Root", [f, f + Vector((t * 0.15, -0.35, -0.04))], [0.16], roll_hint=(0, 0, 1), taper_last=(0.5, 0.5))


# ---------------------------------------------------------------------------
# Fernleaf family
# ---------------------------------------------------------------------------
def fernling_snail(c):
    ell(c, "Body", (0, -0.1, 0.3), (0.6, 1.45, 0.3), step=0.3)
    ell(c, "Body", (0, -1.25, 0.62), (0.45, 0.42, 0.42), step=0.2, vertical=True)
    for side in (-1, 1):
        top = Vector((side * 0.3, -1.35, 1.45))
        c.b.chain("Body", [Vector((side * 0.16, -1.3, 0.9)), (Vector((side * 0.16, -1.3, 0.9)) + top) / 2, top], [0.12, 0.1], roll_hint=(0, 0, 1))
        c.b.box("Eyes", top + Vector((0, 0, 0.12)), (0.32, 0.3, 0.32))
        c.b.box("Pupils", top + Vector((0, -0.16, 0.1)), (0.17, 0.06, 0.2))
    smile(c, -1.67, 0.55, width=0.38)
    ell(c, "Shell", (0, 0.35, 1.05), (0.55, 0.82, 0.82), step=0.25)
    for side in (-1, 1):
        pts = []
        for i in range(14):
            u = i / 13
            a = u * 3.1 * math.pi
            r = 0.72 - 0.6 * u
            pts.append(Vector((side * (0.5 + 0.06 * (1 - u)), 0.35 + math.sin(a) * r, 1.05 + math.cos(a) * r)))
        c.b.chain("ShellLight", pts, [0.15 - 0.06 * i / 13 for i in range(13)], roll_hint=(side, 0, 0))
    frond(c, "Frond", (0, 0.35, 1.8), (0, 0.35, 2.2), (0, 0.65, 2.45), (0, 0.95, 2.3), leaflets=4, size=0.36)
    c.socket("Head", (0, -1.3, 1.9))
    c.socket("Mouth", (0, -1.7, 0.55))
    c.socket("Back", (0, 0.35, 1.9))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -1.2, 0.6))


def leafwing_beetle(c):
    ell(c, "Body", (0, 0.1, 0.65), (0.75, 1.05, 0.45), step=0.28)
    ell(c, "Body", (0, -1.0, 0.62), (0.42, 0.38, 0.38), step=0.2, vertical=True)
    cute_eyes(c, 0.2, -1.33, 0.72, size=0.24)
    chain_curve(c, "Horn", (0, -1.25, 0.8), (0, -1.6, 1.0), (0, -1.65, 1.35), (0, -1.5, 1.55), 0.18, 0.07, n=5)
    for side in (-1, 1):
        rot = euler_deg(0, side * -16, side * -6)
        c.b.box("Shell", (side * 0.4, 0.25, 1.05), (0.72, 1.9, 0.14), rot, taper=(0.35, 1.0))
        c.b.box("ShellLight", (side * 0.4, 0.25, 1.13), (0.07, 1.7, 0.06), rot)
        for k in (-1, 1):
            c.b.box("ShellLight", (side * (0.4 + k * 0.17), 0.1, 1.12), (0.05, 0.9, 0.05), rot @ euler_deg(0, 0, k * 25))
        for k, y in enumerate((-0.55, 0.05, 0.65)):
            hip = Vector((side * 0.6, y, 0.55))
            knee = Vector((side * 0.88, y - 0.05, 0.55))
            foot = Vector((side * 0.98, y - 0.12, 0.05))
            c.b.chain("Leg", [hip, knee, foot], [0.13, 0.11], roll_hint=(0, 0, 1))
        c.b.chain("Leg", [Vector((side * 0.15, -1.2, 0.95)), Vector((side * 0.35, -1.45, 1.3)), Vector((side * 0.5, -1.4, 1.5))],
                  [0.05, 0.05], roll_hint=(0, 0, 1))
    c.socket("Head", (0, -1.2, 1.7))
    c.socket("Mouth", (0, -1.4, 0.55))
    c.socket("Back", (0, 0.3, 1.3))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -0.9, 0.6))


def thornback_hedgehog(c):
    centre = Vector((0, 0.15, 0.9))
    ell(c, "Body", centre, (1.05, 1.15, 0.85), step=0.28)
    ell(c, "Face", (0, -0.8, 0.7), (0.62, 0.5, 0.52), step=0.22, vertical=True)
    c.b.box("Face", (0, -1.32, 0.6), (0.42, 0.45, 0.36), taper=(1, 1))
    c.b.box("Nose", (0, -1.56, 0.66), (0.2, 0.12, 0.18))
    cute_eyes(c, 0.3, -1.22, 0.92, size=0.24)
    smile(c, -1.56, 0.48, width=0.3)
    spikes_on(c, "Spike", centre + Vector((0, 0.1, 0.05)), (1.1, 1.2, 0.95), 60, 0.6, 0.17,
              theta=(-1.6, 1.6), tspan=(-0.5, 0.95), tip_role="SpikeTip", back_tilt=0.9)
    for k in range(3):
        p, n = surf(centre, (1.1, 1.2, 0.95), c.rng.uniform(-0.9, 0.9), c.rng.uniform(-0.2, 0.6))
        leaf(c, "Leaf", p + n * 0.35, n + Vector((0, 0.4, 0)), length=0.55, width=0.35)
    p, n = surf(centre, (1.1, 1.2, 0.95), 0.4, 0.1)
    c.b.box("Berry", p + n * 0.55, (0.24, 0.24, 0.24))
    for sx in (-1, 1):
        for sy in (-0.6, 0.6):
            c.b.box("Face", (sx * 0.55, sy, 0.1), (0.3, 0.35, 0.2))
    c.socket("Head", (0, -0.8, 1.6))
    c.socket("Mouth", (0, -1.6, 0.5))
    c.socket("Back", (0, 0.3, 1.9))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -1.0, 0.7))


def elderfern_treant(c):
    g = biped(c, torso=(1.5, 1.2, 2.4), hip_z=1.2, leg_r=0.42, arm_r=0.3, head_r=0.72, head_up=-0.2,
              body="Bark", limb="Bark", hand="BarkLight", foot="Root", eyes={"glow": True}, fist=0.36, mouth=False)
    slats_around(c, ["BarkLight", "Bark"], g["body_c"], 0.75, 0.6, g["hip_z"] + 0.05, g["hip_z"] + 2.35, 10, width=0.38)
    for k in range(7):
        x = -0.45 + k * 0.15
        fur_plate(c.b, Vector((x, g["front"] - 0.02, g["hz"] - 0.25)), (0, -1, 0), (0, 0, -1), c.rng, 0.26,
                  0.75 + 0.25 * math.sin(k), c.pick("Moss", "Beard"), thickness=0.12, lift=(2, 6), spin=6)
    top = Vector((0, 0, g["hz"] + 0.6))
    for k in range(6):
        a = 2 * math.pi * k / 6 + 0.3
        d = Vector((math.cos(a), math.sin(a), 0))
        frond(c, "Frond", top, top + d * 0.4 + Vector((0, 0, 0.7)), top + d * 1.1 + Vector((0, 0, 0.8)),
              top + d * 1.5 + Vector((0, 0, 0.2)), leaflets=5, size=0.42, alt="FrondLight")
    for hd in g["hands"]:
        for t in (-1, 0, 1):
            tip = hd + Vector((t * 0.25, -0.2, -0.45))
            c.b.chain("BarkLight", [hd, tip], [0.11], roll_hint=(0, 0, 1), taper_last=(0.4, 0.4))
        leaf(c, "FrondLight", hd + Vector((0, 0, 0.2)), (0.2, -0.3, 1), length=0.45, width=0.3)
    for side in (-1, 1):
        for t in (-1, 1):
            f = Vector((side * 0.55, -0.1, 0.12))
            c.b.chain("Root", [f, f + Vector((side * 0.3 + t * 0.15, t * 0.35 - 0.2, -0.04))], [0.16], roll_hint=(0, 0, 1),
                      taper_last=(0.4, 0.4))


# ---------------------------------------------------------------------------
# Toadstool family
# ---------------------------------------------------------------------------
def spotcap_frog(c):
    ell(c, "Body", (0, 0.15, 1.1), (1.4, 1.0, 1.35), step=0.3, vertical=True)
    ell(c, "Body", (0, -0.65, 1.55), (1.2, 0.72, 0.9), step=0.28, vertical=True)
    ell(c, "Belly", (0, -1.0, 0.95), (0.9, 0.58, 0.4), step=0.26, vertical=True)
    for side in (-1, 1):
        ell(c, "Body", (side * 0.6, -0.7, 2.15), (0.46, 0.36, 0.4), step=0.2, vertical=True)
    cute_eyes(c, 0.6, -1.1, 2.22, size=0.42)
    smile(c, -1.55, 1.5, width=0.9)
    for side in (-1, 1):
        c.b.box("Cheeks", (side * 0.9, -1.48, 1.68), (0.38, 0.08, 0.22))
        ell(c, "Body", (side * 1.15, 0.5, 0.5), (0.45, 0.85, 0.42), step=0.25)
        c.b.box("Toes", (side * 1.3, -0.35, 0.12), (0.75, 0.6, 0.24))
        ell(c, "Body", (side * 0.75, -1.15, 0.45), (0.3, 0.45, 0.3), step=0.22, vertical=True)
        c.b.box("Toes", (side * 0.78, -1.4, 0.1), (0.6, 0.5, 0.2))
    cap = Vector((0.15, -0.45, 2.38))
    c.b.box("Belly", cap + Vector((0, 0, -0.08)), (0.4, 0.4, 0.3))
    ell(c, "Cap", cap + Vector((0, 0, 0.2)), (0.72, 0.32, 0.72), step=0.1, vertical=True, profile=DOME)
    dome_dots(c, "Spots", cap + Vector((0, 0, 0.2)), 0.72, 0.32, 5, 0.2)
    c.socket("Head", (0, -0.5, 2.9))
    c.socket("Mouth", (0, -1.6, 1.5))
    c.socket("Back", (0, 0.6, 2.1))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -1.1, 1.0))


def puffball_bunny(c):
    ell(c, "Fur", (0, 0.25, 0.95), (1.0, 0.95, 1.0), step=0.28, vertical=True)
    ell(c, "Belly", (0, -0.55, 0.85), (0.62, 0.62, 0.42), step=0.24, vertical=True)
    ell(c, "Fur", (0, -0.45, 2.1), (0.78, 0.7, 0.72), step=0.24, vertical=True)
    cute_eyes(c, 0.33, -1.14, 2.2, size=0.3)
    c.b.box("Nose", (0, -1.2, 1.98), (0.16, 0.08, 0.12))
    smile(c, -1.18, 1.85, width=0.3)
    for side in (-1, 1):
        c.b.box("Cheeks", (side * 0.5, -1.12, 1.95), (0.24, 0.06, 0.16))
        rot = euler_deg(-6, side * 12, 0)
        c.b.box("Fur", (side * 0.32, -0.4, 3.15), (0.34, 0.26, 1.25), rot, taper=(1, 1))
        c.b.box("Inner", (side * 0.32, -0.55, 3.15), (0.18, 0.06, 1.0), rot)
        ell(c, "Puff", (side * 0.4, -0.4, 3.85), (0.28, 0.28, 0.28), step=0.14, vertical=True)
        c.b.box("Fur", (side * 0.4, -1.0, 0.15), (0.32, 0.4, 0.3))
        c.b.box("Fur", (side * 0.75, -0.3, 0.13), (0.45, 1.0, 0.26))
    ell(c, "Puff", (0, 1.25, 0.75), (0.4, 0.4, 0.4), step=0.18, vertical=True)
    for k in range(2):
        p = Vector((0.45 - k * 0.9, 0.7, 1.75 - k * 0.1))
        ell(c, "Puff", p, (0.2, 0.2, 0.2), step=0.12, vertical=True)
        c.b.box("PuffSpots", p + Vector((0.05, -0.15, 0.12)), (0.07, 0.06, 0.07))
    c.socket("Head", (0, -0.4, 3.0))
    c.socket("Mouth", (0, -1.2, 1.9))
    c.socket("Back", (0, 0.6, 1.9))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -0.9, 1.0))


def sporecloak_fox(c):
    g = quadruped(c, L=2.3, W=1.15, H=1.0, leg_h=1.0, leg_r=0.17, head_r=0.6, head_up=0.55,
                  snout=(0.38, 0.65, 0.32), stance=0.32, spread=0.32, eyes={"size": 0.28, "iris": "Iris"},
                  body="Fur", leg="Fur", paw="Dark", snout_role="Belly", nose="Dark")
    ears(c, "Fur", g, "pointy", size=0.62, inner="Belly", tilt=12)
    ell(c, "Belly", (0, -1.05, g["zb"] - 0.05), (0.4, 0.45, 0.35), step=0.2)
    tail(c, "Fur", (0, 1.1, g["zb"] + 0.15), (0, 1.8, g["zb"] + 0.35), (0, 2.25, g["zb"] + 0.95), (0, 2.2, g["zb"] + 1.55),
         0.36, 0.48, n=5, tip="Belly", tip_size=(0.45, 0.5, 0.45))
    cape_c = g["body_c"] + Vector((0, 0.05, 0.12))
    cape_r = (g["W"] / 2 + 0.08, g["L"] / 2 + 0.05, g["H"] / 2 + 0.08)
    plates_on(c, ["Cape", "CapeDark"], cape_c, cape_r, rows=4, per_row=7, theta=(-1.8, 1.8), tspan=(-0.9, 0.55),
              size=(0.6, 0.85), thickness=0.14, lift=(4, 12))
    spots_on(c, "CapeSpots", cape_c, tuple(r + 0.12 for r in cape_r), 10, 0.17, theta=(-1.4, 1.4), tspan=(-0.8, 0.5))
    for k in range(8):
        a = -1.9 + k * 0.54
        p = Vector((math.sin(a) * 0.55, -1.05 + abs(math.sin(a)) * 0.1, g["zb"] + 0.25 + math.cos(a) * 0.3))
        fur_plate(c.b, p, (math.sin(a), -0.4, math.cos(a)), (0, 0.2, -1), c.rng, 0.3, 0.45, "Gill", thickness=0.1)


def toadstool_titan(c):
    g = biped(c, torso=(1.6, 1.3, 2.0), hip_z=1.1, leg_r=0.45, arm_r=0.33, head_r=0.55, head_up=-0.35,
              body="Stem", limb="Stem", hand="Root", foot="Root", eyes={"glow": True}, fist=0.45, mouth=False,
              head_role="Stem")
    cap = Vector((0, -0.1, g["hz"] + 0.55))
    c.b.box("Gill", cap + Vector((0, 0, -0.75)), (3.2, 3.2, 0.14))
    ell(c, "CapDark", cap + Vector((0, 0, -0.62)), (1.95, 0.12, 1.95), step=0.12, vertical=True)
    ell(c, "Cap", cap, (1.9, 0.85, 1.9), step=0.17, vertical=True, profile=DOME)
    dome_dots(c, "Spots", cap, 1.9, 0.85, 12, 0.36)
    dome_dots(c, "SpotGlow", cap, 1.9, 0.85, 5, 0.26, fmin=0.2, fmax=0.6)
    for k in range(10):
        a = 2 * math.pi * k / 10
        p = Vector((math.cos(a) * 0.78, math.sin(a) * 0.62, g["hip_z"] + 1.75))
        fur_plate(c.b, p, (math.cos(a), math.sin(a), 0.2), (0, 0, -1), c.rng, 0.45, 0.6, "StemShade", thickness=0.1)
    for side in (-1, 1):
        sh = Vector((side * 1.0, 0.15, g["hip_z"] + 2.05))
        c.b.box("Stem", sh + Vector((0, 0, 0.12)), (0.16, 0.16, 0.3))
        ell(c, "Cap", sh + Vector((0, 0, 0.35)), (0.3, 0.15, 0.3), step=0.08, vertical=True, profile=DOME)
        fur_plate(c.b, Vector((side * 0.5, -0.3, 0.55)), (side, -0.5, 0.3), (0, 0, -1), c.rng, 0.5, 0.5, "Moss", thickness=0.12)
    for hd in g["hands"]:
        for t in (-1, 0, 1):
            tip = hd + Vector((t * 0.3, -0.2, -0.5))
            c.b.chain("Root", [hd, tip], [0.13], roll_hint=(0, 0, 1), taper_last=(0.4, 0.4))
    c.socket("Head", tuple(cap + Vector((0, 0, 1.1))))


# ---------------------------------------------------------------------------
# Crystal family
# ---------------------------------------------------------------------------
def quartzpaw_kit(c):
    g = quadruped(c, L=1.7, W=1.15, H=1.0, leg_h=0.6, leg_r=0.2, head_r=0.72, head_up=0.6,
                  snout=(0.38, 0.3, 0.28), stance=0.3, spread=0.3, eyes={"size": 0.34, "iris": "Iris"},
                  body="Fur", leg="Fur", paw="Paw", snout_role="Belly")
    ears(c, "Fur", g, "pointy", size=0.55, inner="Belly", tilt=15)
    for side in (-1, 1):
        crystals(c, "CrystalGlass", (side * g["head_r"] * 0.55, g["hy"] + 0.1, g["hz"] + g["head_r"] + 0.45),
                 (side * 0.2, 0, 1), size=0.28, count=1)
    pts = tail(c, "Fur", (0, 0.8, g["zb"] + 0.1), (0, 1.25, g["zb"] + 0.3), (0.1, 1.45, g["zb"] + 0.8),
               (0.05, 1.3, g["zb"] + 1.1), 0.18, 0.14, n=4)
    crystals(c, "CrystalGlass", pts[-1], (0, -0.2, 1), size=0.3, count=1)


def amethyst_moth(c):
    ell(c, "Body", (0, -0.2, 1.6), (0.55, 0.55, 0.55), step=0.22, vertical=True)
    ell(c, "Body", (0, 0.7, 1.4), (0.45, 0.7, 0.42), step=0.24)
    for y in (0.45, 0.85):
        c.b.box("Fuzz", (0, y, 1.4), (0.92, 0.12, 0.86))
    ell(c, "Fuzz", (0, -0.75, 1.75), (0.42, 0.38, 0.4), step=0.18, vertical=True)
    cute_eyes(c, 0.2, -1.12, 1.82, size=0.26, iris="Iris")
    for k in range(8):
        a = 2 * math.pi * k / 8
        fur_plate(c.b, Vector((math.cos(a) * 0.45, -0.45 + math.sin(a) * 0.12, 1.65 + math.sin(a) * 0.35)),
                  (math.cos(a), -0.3, math.sin(a)), (0, 0.4, -1), c.rng, 0.35, 0.45, "Fuzz", thickness=0.1)
    for side in (-1, 1):
        base = Vector((side * 0.12, -0.9, 2.05))
        tip = base + Vector((side * 0.45, -0.35, 0.7))
        c.b.chain("Antenna", [base, (base + tip) / 2, tip], [0.05, 0.05], roll_hint=(0, 0, 1))
        for k in range(4):
            p = base.lerp(tip, 0.3 + k * 0.18)
            c.b.box("Antenna", p + Vector((side * 0.08, 0, 0)), (0.18, 0.04, 0.04), euler_deg(0, 0, side * 20))
        flat_wing(c, "WingGlass", "WingVein", (side * 0.4, -0.15, 1.75), (side * 1.0, -0.15, 0.55), 1.8, 1.2, lift=side * 10,
                  segs=5, spot="Fuzz")
        flat_wing(c, "WingGlass", "WingVein", (side * 0.35, 0.3, 1.5), (side * 1.0, 0.55, -0.25), 1.3, 0.9, lift=side * 10, segs=4)
        for y in (-0.3, 0.1, 0.5):
            c.b.chain("Antenna", [Vector((side * 0.3, y, 1.25)), Vector((side * 0.5, y - 0.1, 0.9))], [0.05], roll_hint=(0, 0, 1))
    c.socket("Head", (0, -0.75, 2.4))
    c.socket("Mouth", (0, -1.15, 1.65))
    c.socket("Back", (0, 0.2, 2.1))
    c.socket("Feet", (0, 0, 0.9))
    c.socket("Chest", (0, -0.6, 1.5))


def prismhorn_ram(c):
    g = quadruped(c, L=2.3, W=1.7, H=1.5, leg_h=0.85, leg_r=0.24, head_r=0.62, head_up=0.35,
                  snout=(0.5, 0.55, 0.45), body="Wool", belly="WoolShade", leg="Face", paw="Hoof",
                  snout_role="Face", head_role="Face", nose="Hoof", eyes={"size": 0.28})
    plates_on(c, ["Wool", "WoolShade"], g["body_c"], tuple(r + 0.05 for r in g["body_r"]), rows=4, per_row=6,
              size=(0.7, 0.8), drape=(0, 0.3, -1), thickness=0.22, lift=(10, 25))
    ell(c, "Wool", (0, g["hy"] + 0.05, g["hz"] + g["head_r"] * 0.85), (0.42, 0.3, 0.3), step=0.15)
    horns_curl(c, "HornGlass", (0.38, g["hy"] + 0.05, g["hz"] + 0.45), (0.62, g["hy"] + 0.25, g["hz"] + 0.05),
               r0=0.5, r1=0.18, turns=1.25, size0=0.3, size1=0.1, n=11)
    for side in (-1, 1):
        crystals(c, "HornGlass", (side * 0.45, g["hy"] + 0.2, g["hz"] + 0.5), (side * 0.3, 0.3, 1), size=0.22, count=2)


def geodeback_tortoise(c):
    for sx in (-1, 1):
        for sy in (-1, 1):
            ell(c, "Skin", (sx * 0.95, sy * 0.8, 0.35), (0.34, 0.38, 0.34), step=0.2, vertical=True)
            for t in (-1, 0, 1):
                c.b.box("SkinDark", (sx * 0.95 + t * 0.18, sy * 0.8 - 0.35, 0.08), (0.14, 0.2, 0.16))
    ell(c, "SkinDark", (0, 0, 0.6), (1.2, 1.35, 0.32), step=0.26)
    shell = Vector((0, 0.05, 1.22))
    ell(c, "Shell", shell, (1.38, 0.92, 1.55), step=0.18, vertical=True, profile=DOME)
    for k in range(16):
        a = 2 * math.pi * k / 16
        c.b.box("ShellRim", (math.cos(a) * 1.3, 0.05 + math.sin(a) * 1.45, 0.38), (0.55, 0.32, 0.26),
                euler_deg(0, 0, math.degrees(a) + 90))
    dome_dots(c, "ShellRim", shell, 1.38, 0.92, 12, 0.55, fmin=0.15, fmax=0.6)
    top = Vector((0, 0.05, 2.08))
    for k in range(10):
        a = 2 * math.pi * k / 10
        c.b.box("ShellRim", top + Vector((math.cos(a) * 0.55, math.sin(a) * 0.55, 0.0)), (0.32, 0.3, 0.28),
                euler_deg(0, 0, math.degrees(a)))
    c.b.box("CoreGlow", top + Vector((0, 0, -0.05)), (0.75, 0.75, 0.12))
    crystals(c, "CrystalGlass", top, (0, 0, 1), size=0.9, count=6, alt_role="CrystalGlass2", alt_chance=0.4)
    for k in range(3):
        a = 0.8 + k * 2.1
        p = Vector((math.cos(a) * 1.0, 0.05 + math.sin(a) * 1.1, 1.3))
        crystals(c, "CrystalGlass2", p, (math.cos(a), math.sin(a), 0.8), size=0.42, count=2)
    spots_on(c, "Gold", shell + Vector((0, 0, -0.1)), (1.32, 1.5, 0.95), 8, 0.12, theta=(-1.4, 1.4))
    c.b.chain("Skin", [Vector((0, -1.15, 0.75)), Vector((0, -1.5, 0.95)), Vector((0, -1.75, 1.08))], [0.45, 0.42], roll_hint=(0, 0, 1))
    ell(c, "Skin", (0, -2.0, 1.15), (0.5, 0.45, 0.48), step=0.2, vertical=True)
    cute_eyes(c, 0.24, -2.4, 1.25, size=0.24)
    smile(c, -2.43, 1.0, width=0.32)
    crystals(c, "CrystalGlass", (0, -1.95, 1.62), (0, -0.2, 1), size=0.28, count=2)
    c.b.chain("SkinDark", [Vector((0, 1.3, 0.55)), Vector((0, 1.65, 0.4))], [0.16], roll_hint=(0, 0, 1), taper_last=(0.3, 0.3))
    c.socket("Head", (0, -2.0, 1.9))
    c.socket("Mouth", (0, -2.45, 1.05))
    c.socket("Back", tuple(top + Vector((0, 0, 0.6))))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -1.4, 0.8))


# ---------------------------------------------------------------------------
# Geode family
# ---------------------------------------------------------------------------
def shardling_mole(c):
    ell(c, "Fur", (0, 0.15, 0.62), (0.95, 1.1, 0.6), step=0.26)
    ell(c, "Belly", (0, -0.35, 0.45), (0.65, 0.6, 0.35), step=0.24)
    ell(c, "Fur", (0, -0.95, 0.6), (0.55, 0.5, 0.46), step=0.2, vertical=True)
    c.b.box("Nose", (0, -1.48, 0.6), (0.3, 0.2, 0.24))
    for k in range(5):
        a = 2 * math.pi * k / 5
        c.b.box("Nose", (math.cos(a) * 0.17, -1.58, 0.6 + math.sin(a) * 0.15), (0.09, 0.12, 0.09))
    for side in (-1, 1):
        c.b.box("Pupils", (side * 0.22, -1.38, 0.86), (0.16, 0.06, 0.05))
        arm = Vector((side * 0.8, -0.65, 0.35))
        c.b.box("Fur", arm, (0.38, 0.45, 0.32))
        for t in (-1, 0, 1):
            c.b.crystal("ClawGlass", arm + Vector((t * 0.12, -0.18, -0.05)), (side * 0.1 + t * 0.15, -1, -0.4), 0.45, 0.07)
        c.b.box("Fur", (side * 0.6, 0.9, 0.12), (0.32, 0.4, 0.22))
    crystals(c, "ClawGlass", (0, -0.75, 1.0), (0, 0.3, 1), size=0.4, count=1)
    c.socket("Head", (0, -0.9, 1.6))
    c.socket("Mouth", (0, -1.6, 0.55))
    c.socket("Back", (0, 0.4, 1.3))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -1.1, 0.6))


def druzy_lynx(c):
    g = quadruped(c, L=2.3, W=1.25, H=1.05, leg_h=1.1, leg_r=0.22, head_r=0.65, head_up=0.5,
                  snout=(0.45, 0.4, 0.32), eyes={"size": 0.3, "iris": "Iris"}, body="Fur", leg="Fur", paw="Belly",
                  snout_role="Belly", nose="Nose")
    ears(c, "Fur", g, "pointy", size=0.58, inner="Belly", tilt=10)
    for side in (-1, 1):
        c.b.box("Tuft", (side * g["head_r"] * 0.55, g["hy"] + 0.1, g["hz"] + g["head_r"] + 0.85), (0.08, 0.08, 0.4))
        for k in range(2):
            fur_plate(c.b, Vector((side * g["head_r"] * 0.9, g["hy"] - 0.1 + k * 0.2, g["hz"] - 0.2)), (side, -0.3, 0),
                      (side * 0.3, 0.3, -1), c.rng, 0.35, 0.5, "Belly", thickness=0.1)
    spots_on(c, "Spots", g["body_c"], g["body_r"], 14, 0.22, theta=(-1.4, 1.4))
    for t, th in ((-0.4, 0.5), (0.0, -0.6), (0.35, 0.3), (0.6, -0.2)):
        p, n = surf(g["body_c"], g["body_r"], th, t)
        crystals(c, "DruzyGlass", p, n, size=0.32, count=3, alt_role="DruzyGlass2", alt_chance=0.4)
    pts = tail(c, "Fur", (0, 1.1, g["zb"] + 0.2), (0, 1.4, g["zb"] + 0.35), (0, 1.55, g["zb"] + 0.5),
               (0, 1.6, g["zb"] + 0.6), 0.2, 0.18, n=3)
    ell(c, "Tuft", pts[-1], (0.2, 0.22, 0.2), step=0.12)


def gemhorn_rhino(c):
    g = quadruped(c, L=3.0, W=2.0, H=1.6, leg_h=0.9, leg_r=0.36, head_r=0.78, head_up=0.0, head_fwd=0.1,
                  snout=(0.82, 0.8, 0.66), body="Hide", belly="HideDark", leg="Hide", paw="HideDark",
                  snout_role="Hide", nose=None, eyes={"size": 0.24}, head_role="Hide")
    plates_on(c, ["Plate", "HideDark"], g["body_c"], tuple(r + 0.06 for r in g["body_r"]), rows=4, per_row=6,
              theta=(-1.6, 1.6), size=(0.95, 1.0), thickness=0.2, lift=(2, 8))
    for y in (-1.2, 1.25):
        c.b.box("Gold", (0, y, g["zb"] + 0.1), (g["W"] * 0.95, 0.14, g["H"] * 1.02))
    horn_base = Vector((0, g["front"] - 0.45, g["hz"] + 0.05))
    c.b.crystal("GemGlass", horn_base, (0, -0.45, 1), 1.4, 0.3)
    c.b.crystal("GemGlow", horn_base + Vector((0, 0, 0.05)), (0, -0.45, 1), 0.95, 0.14)
    c.b.crystal("GemGlass", horn_base + Vector((0, 0.45, 0.3)), (0, -0.2, 1), 0.6, 0.18)
    for side in (-1, 1):
        c.b.box("Gold", (side * 0.3, horn_base.y + 0.1, horn_base.z - 0.15), (0.12, 0.3, 0.12))
    ears(c, "Hide", g, "pointy", size=0.38, inner="HideDark", tilt=35)
    c.b.chain("Hide", [Vector((0, 1.5, g["zb"] + 0.2)), Vector((0, 1.85, g["zb"] - 0.1))], [0.14], roll_hint=(0, 0, 1),
              taper_last=(0.3, 0.3))


def prismatic_basilisk(c):
    path = bezier((0, -1.8, 1.15), (0, -0.6, 1.0), (1.2, 0.8, 0.75), (0.2, 3.4, 0.35), 12)
    radii = [0.62, 0.7, 0.72, 0.7, 0.66, 0.6, 0.52, 0.44, 0.36, 0.28, 0.2, 0.14]
    for i in range(len(path) - 1):
        a, b_ = path[i], path[i + 1]
        d = b_ - a
        r = radii[i]
        ell(c, "Scale", (a + b_) / 2, (r, d.length * 0.62, r * 0.85), step=0.22, rot=basis_from_y(d, (0, 0, 1)))
        if i < 7:
            c.b.box("Belly", (a + b_) / 2 + Vector((0, 0, -r * 0.6)), (r * 1.3, d.length * 1.05, 0.2), basis_from_y(d, (0, 0, 1)))
        role = ("CrestGlass1", "CrestGlass2", "CrestGlass3")[i % 3]
        top = (a + b_) / 2 + Vector((0, 0, r * 0.8))
        c.b.crystal(role, top, (0, 0.35, 1), 0.9 * r + 0.25, 0.14 + r * 0.12)
        if i % 2 == 0:
            c.b.box("SpineGlow", top + Vector((0, 0, -0.05)), (0.2, 0.3, 0.12), basis_from_y(d, (0, 0, 1)))
    spots_on(c, "ScaleLight", path[2], (0.8, 1.0, 0.7), 10, 0.18, theta=(-1.4, 1.4))
    head = Vector((0, -2.45, 1.3))
    ell(c, "Scale", head, (0.55, 0.7, 0.45), step=0.22)
    c.b.box("Scale", head + Vector((0, -0.75, -0.08)), (0.6, 0.6, 0.38))
    c.b.box("Belly", head + Vector((0, -0.6, -0.33)), (0.55, 0.75, 0.16))
    cute_eyes(c, 0.32, head.y - 0.55, head.z + 0.2, size=0.24, glow=True)
    for k in range(7):
        a = -1.4 + k * 0.47
        role = ("CrestGlass1", "CrestGlass2", "CrestGlass3")[k % 3]
        d = Vector((math.sin(a) * 0.9, 0.55, math.cos(a)))
        c.b.box(role, head + Vector((math.sin(a) * 0.4, 0.4, math.cos(a) * 0.3)) + d.normalized() * 0.45,
                (0.08, 0.95, 0.42), basis_from_y(d, (0, 1, 0)), taper=(0.2, 0.2))
    for i, side in ((2, -1), (2, 1), (6, -1), (6, 1)):
        hip = path[i] + Vector((side * radii[i] * 0.8, 0, -0.1))
        knee = hip + Vector((side * 0.55, 0, 0.1))
        foot = knee + Vector((side * 0.15, -0.1, -knee.z + 0.1))
        c.b.chain("Scale", [hip, knee, foot], [0.28, 0.22], roll_hint=(0, 0, 1))
        c.b.box("ScaleLight", foot + Vector((0, -0.12, 0)), (0.42, 0.5, 0.18))
    c.socket("Head", tuple(head + Vector((0, 0, 0.8))))
    c.socket("Mouth", tuple(head + Vector((0, -1.05, -0.1))))
    c.socket("Back", tuple(path[3] + Vector((0, 0, 1.0))))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", tuple(path[1]))


# ---------------------------------------------------------------------------
# Lava family
# ---------------------------------------------------------------------------
def cinderpaw_pup(c):
    g = quadruped(c, L=1.9, W=1.2, H=1.0, leg_h=0.65, leg_r=0.22, head_r=0.68, head_up=0.5,
                  snout=(0.45, 0.42, 0.34), body="Fur", belly="Belly", leg="Fur", paw="EmberGlow",
                  eyes={"size": 0.32}, nose="Nose", snout_role="Belly")
    ears(c, "Fur", g, "pointy", size=0.5, inner="Belly", tilt=40)
    for side in (-1, 1):
        c.b.box("EmberGlow", (side * g["head_r"] * 0.75, g["hy"] + 0.1, g["hz"] + g["head_r"] + 0.45), (0.12, 0.1, 0.12))
    pts = tail(c, "Fur", (0, 0.95, g["zb"] + 0.2), (0, 1.15, g["zb"] + 0.45), (0, 1.2, g["zb"] + 0.8),
               (0, 1.1, g["zb"] + 1.0), 0.15, 0.12, n=4)
    ell(c, "EmberGlow", pts[-1], (0.17, 0.2, 0.17), step=0.1)
    spots_on(c, "EmberGlow", g["body_c"], g["body_r"], 3, 0.14, theta=(-0.6, 0.6))


def magmashell_crab(c):
    centre = Vector((0, 0, 0.92))
    ell(c, "Shell", centre, (1.5, 1.1, 0.55), step=0.24)
    ell(c, "ShellLight", (0, 0, 0.66), (1.3, 0.95, 0.3), step=0.24)
    cracks_on(c, "MagmaGlow", centre, (1.5, 1.1, 0.58), 5, segs=4, theta=(-1.3, 1.3))
    spots_on(c, "ShellLight", centre, (1.5, 1.1, 0.55), 8, 0.22, theta=(-1.1, 1.1))
    for side in (-1, 1):
        base = Vector((side * 0.35, -0.85, 1.2))
        top = base + Vector((side * 0.12, -0.15, 0.5))
        c.b.chain("Leg", [base, top], [0.1], roll_hint=(0, 0, 1))
        c.b.box("Eyes", top + Vector((0, 0, 0.12)), (0.3, 0.28, 0.3))
        c.b.box("Pupils", top + Vector((0, -0.15, 0.12)), (0.16, 0.06, 0.2))
        sh = Vector((side * 1.3, -0.55, 0.85))
        el = Vector((side * 1.75, -1.0, 0.9))
        c.b.chain("Leg", [sh, el], [0.2], roll_hint=(0, 0, 1))
        claw = el + Vector((0, -0.45, 0.1))
        c.b.box("Claw", claw, (0.62, 0.85, 0.45), euler_deg(-8, 0, side * 10), taper=(0.6, 0.6))
        c.b.box("Claw", claw + Vector((side * 0.05, -0.15, -0.35)), (0.4, 0.6, 0.18), euler_deg(10, 0, side * 10), taper=(0.6, 0.6))
        c.b.box("MagmaGlow", claw + Vector((0, 0.1, 0.24)), (0.3, 0.3, 0.06))
        for k, y in enumerate((-0.3, 0.15, 0.55)):
            hip = Vector((side * 1.2, y, 0.75))
            knee = Vector((side * 1.7, y + 0.05, 0.85))
            foot = Vector((side * 1.9, y + 0.1, 0.05))
            c.b.chain("Leg", [hip, knee, foot], [0.14, 0.1], roll_hint=(0, 0, 1), taper_last=(0.4, 0.4))
    smile(c, -1.1, 0.75, width=0.4)
    c.socket("Head", (0, -0.6, 1.9))
    c.socket("Mouth", (0, -1.15, 0.75))
    c.socket("Back", (0, 0.1, 1.6))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -1.0, 0.8))


def emberwing_drake(c):
    g = quadruped(c, L=2.4, W=1.4, H=1.25, leg_h=0.85, leg_r=0.26, head_r=0.62, head_up=0.75, head_fwd=0.25,
                  neck=0.45, snout=(0.5, 0.7, 0.42), body="Scale", belly="Belly", leg="Scale", paw="ScaleDark",
                  snout_role="Scale", nose="ScaleDark", eyes={"size": 0.28, "iris": "Iris"}, head_role="Scale")
    for side in (-1, 1):
        base = Vector((side * 0.32, g["hy"] + 0.2, g["hz"] + 0.5))
        chain_curve(c, "Horn", base, base + Vector((side * 0.1, 0.3, 0.3)), base + Vector((side * 0.15, 0.6, 0.4)),
                    base + Vector((side * 0.2, 0.85, 0.35)), 0.16, 0.06, n=4)
    spikes_on(c, "ScaleDark", g["body_c"], g["body_r"], 8, 0.45, 0.16, theta=(-0.12, 0.12), tspan=(-0.7, 0.85))
    wings(c, "ScaleDark", "WingGlass", (0.55, -0.4, g["zb"] + 0.55), span=2.4, height=1.5, back=0.7, fingers=3)
    pts = tail(c, "Scale", (0, 1.15, g["zb"]), (0, 1.9, g["zb"] - 0.2), (0.4, 2.5, g["zb"] - 0.5),
               (0.6, 2.9, g["zb"] - 0.55), 0.3, 0.12, n=6)
    c.b.crystal("EmberGlow", pts[-1], pts[-1] - pts[-2], 0.6, 0.18)
    cracks_on(c, "EmberGlow", g["body_c"] + Vector((0, -0.6, -0.2)), (0.6, 0.6, 0.55), 2, segs=3, width=0.1,
              theta=(2.4, 3.6), tspan=(-0.8, -0.2))


def obsidian_colossus(c):
    g = biped(c, torso=(2.2, 1.5, 2.0), hip_z=1.2, leg_r=0.55, arm_r=0.45, head_r=0.5, head_up=-0.25,
              body="Rock", limb="Rock", hand="Obsidian", foot="Obsidian", eyes={"glow": True}, fist=0.65,
              mouth=False, head_role="Obsidian")
    cracks_on(c, "MagmaGlow", g["body_c"], tuple(r + 0.28 for r in g["body_r"]), 7, segs=5, width=0.16,
              theta=(-2.6, 2.6), tspan=(-0.9, 0.9))
    c.b.box("Obsidian", (0, -0.78, g["tz"] + 0.25), (1.05, 0.2, 0.95))
    c.b.box("MagmaGlow2", (0, -0.86, g["tz"] + 0.25), (0.6, 0.12, 0.55))
    slats_around(c, ["RockLight", "Rock"], g["body_c"], 1.1, 0.76, g["hip_z"] + 0.2, g["hip_z"] + 1.6, 10, width=0.5, depth=0.2)
    for side in (-1, 1):
        sh = Vector((side * 1.25, 0.05, g["hip_z"] + 2.0))
        for k in range(3):
            c.b.crystal("Obsidian", sh, (side * (0.4 + 0.3 * k), -0.2 + 0.3 * k, 1), 0.9 - k * 0.15, 0.22)
        c.b.box("MagmaGlow", g["hands"][(side + 1) // 2] + Vector((0, -0.62, 0.1)), (0.7, 0.1, 0.3))
    spots_on(c, "Ash", g["body_c"], g["body_r"], 6, 0.3, theta=(-2.0, 2.0))


# ---------------------------------------------------------------------------
# Obsidian family
# ---------------------------------------------------------------------------
def ashen_imp(c):
    g = biped(c, torso=(1.0, 0.75, 1.0), hip_z=0.75, leg_r=0.22, arm_r=0.18, head_r=0.62, head_up=0.05,
              body="Skin", limb="Skin", hand="SkinDark", foot="SkinDark", eyes={"glow": True}, fist=0.22,
              head_role="Skin", mouth=False)
    hz, hr = g["hz"], g["head_r"]
    c.b.box("Mouth", (0, g["front"] + 0.02, hz - hr * 0.42), (0.55, 0.08, 0.12))
    for side in (-1, 1):
        c.b.box("Tooth", (side * 0.14, g["front"] - 0.01, hz - hr * 0.5), (0.1, 0.06, 0.12), taper=(1, 1))
        base = Vector((side * 0.32, -0.05, hz + hr * 0.75))
        chain_curve(c, "Horn", base, base + Vector((side * 0.2, 0, 0.3)), base + Vector((side * 0.35, 0.15, 0.5)),
                    base + Vector((side * 0.3, 0.3, 0.65)), 0.16, 0.05, n=4)
        c.b.box("Skin", (side * (hr + 0.12), -0.05, hz + 0.05), (0.45, 0.12, 0.22), euler_deg(0, side * -20, 0), taper=(0.2, 1))
    wings(c, "SkinDark", "Wing", (0.35, 0.35, g["tz"] + 0.3), span=1.2, height=0.8, back=0.4, fingers=2)
    pts = tail(c, "SkinDark", (0, 0.35, g["hip_z"]), (0, 0.9, g["hip_z"] - 0.2), (0.3, 1.2, g["hip_z"] + 0.3),
               (0.35, 1.1, g["hip_z"] + 0.7), 0.08, 0.06, n=5)
    c.b.box("Horn", pts[-1] + Vector((0, 0, 0.12)), (0.28, 0.1, 0.32), euler_deg(0, 0, 0), taper=(0.2, 0.2))
    spots_on(c, "EmberGlow", g["body_c"], g["body_r"], 3, 0.12, theta=(2.5, 3.6), tspan=(-0.9, -0.5))


def slagback_boar(c):
    g = quadruped(c, L=2.8, W=2.0, H=1.6, leg_h=0.7, leg_r=0.34, head_r=0.85, head_up=0.15,
                  snout=(0.85, 0.5, 0.6), body="Hide", belly="HideLight", leg="Hide", paw="Slag",
                  snout_role="Snout", nose="Slag", eyes={"glow": True}, head_role="Hide")
    ears(c, "Hide", g, "pointy", size=0.5, inner="HideLight", tilt=35)
    for side in (-1, 1):
        base = Vector((side * 0.36, g["front"] - 0.3, g["hz"] - 0.5))
        chain_curve(c, "Tusk", base, base + Vector((side * 0.2, -0.2, 0.05)), base + Vector((side * 0.32, -0.25, 0.45)),
                    base + Vector((side * 0.25, -0.05, 0.7)), 0.2, 0.09, n=5)
    plates_on(c, ["Slag", "Slag2"], g["body_c"], tuple(r + 0.06 for r in g["body_r"]), rows=4, per_row=5,
              theta=(-1.3, 1.3), size=(0.9, 0.9), thickness=0.26, lift=(3, 10))
    cracks_on(c, "SlagGlow", g["body_c"], tuple(r + 0.14 for r in g["body_r"]), 5, segs=4, theta=(-1.2, 1.2))
    spikes_on(c, "Mane", g["body_c"], g["body_r"], 9, 0.55, 0.18, theta=(-0.15, 0.15), tspan=(-0.9, 0.3))
    tail(c, "Hide", (0, 1.35, g["zb"] + 0.2), (0, 1.6, g["zb"] + 0.35), (0.15, 1.7, g["zb"] + 0.6),
         (0.05, 1.6, g["zb"] + 0.7), 0.1, 0.07, n=4)


def basalt_wyvern(c):
    ell(c, "Scale", (0, 0.2, 1.65), (0.8, 1.0, 0.85), step=0.26)
    ell(c, "ScaleLight", (0, -0.35, 1.45), (0.58, 0.6, 0.6), step=0.24)
    cracks_on(c, "Glow", (0, -0.35, 1.45), (0.6, 0.62, 0.62), 3, segs=3, width=0.1, theta=(2.3, 3.8), tspan=(-0.9, -0.2))
    c.b.chain("Scale", [Vector((0, -0.6, 2.15)), Vector((0, -0.95, 2.6)), Vector((0, -1.2, 2.9))], [0.5, 0.42], roll_hint=(0, 0, 1))
    head = Vector((0, -1.45, 3.05))
    ell(c, "Scale", head, (0.48, 0.6, 0.42), step=0.2)
    c.b.box("Scale", head + Vector((0, -0.62, -0.1)), (0.5, 0.6, 0.34))
    c.b.box("Basalt", head + Vector((0, -0.55, -0.32)), (0.46, 0.65, 0.14))
    cute_eyes(c, 0.28, head.y - 0.5, head.z + 0.15, size=0.22, glow=True)
    for side in (-1, 1):
        base = head + Vector((side * 0.28, 0.2, 0.3))
        chain_curve(c, "Horn", base, base + Vector((side * 0.15, 0.4, 0.25)), base + Vector((side * 0.2, 0.75, 0.3)),
                    base + Vector((side * 0.25, 1.0, 0.15)), 0.15, 0.05, n=4)
        thigh = Vector((side * 0.55, 0.35, 1.0))
        ell(c, "Scale", thigh, (0.36, 0.45, 0.42), step=0.2)
        foot = Vector((side * 0.62, 0.1, 0.12))
        c.b.chain("Scale", [thigh, Vector((side * 0.6, 0.55, 0.55)), foot], [0.28, 0.22], roll_hint=(0, 0, 1))
        c.b.box("Basalt", foot + Vector((0, -0.15, 0)), (0.5, 0.7, 0.24))
        for t in (-1, 0, 1):
            c.b.box("Horn", foot + Vector((t * 0.16, -0.55, -0.02)), (0.1, 0.25, 0.12), taper=(0.3, 0.3))
    plates_on(c, ["Basalt", "ScaleLight"], (0, 0.25, 1.75), (0.82, 1.0, 0.88), rows=3, per_row=5, theta=(-1.0, 1.0),
              tspan=(-0.4, 0.9), size=(0.6, 0.7), thickness=0.2, lift=(3, 10))
    wings(c, "Basalt", "Wing", (0.55, -0.1, 2.15), span=3.0, height=1.8, back=0.9, fingers=3)
    pts = tail(c, "Scale", (0, 1.15, 1.45), (0, 2.0, 1.0), (0.6, 2.8, 0.5), (1.1, 3.3, 0.45), 0.36, 0.12, n=7)
    c.b.crystal("Basalt", pts[-1], pts[-1] - pts[-2], 0.7, 0.2)
    c.socket("Head", tuple(head + Vector((0, 0, 0.8))))
    c.socket("Mouth", tuple(head + Vector((0, -0.95, -0.15))))
    c.socket("Back", (0, 0.4, 2.6))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -0.7, 1.5))


def molten_behemoth(c):
    g = quadruped(c, L=3.2, W=2.3, H=1.9, leg_h=1.0, leg_r=0.45, head_r=0.85, head_up=0.3,
                  snout=(0.9, 0.6, 0.7), body="Obsidian", belly="ObsidianLight", leg="Obsidian", paw="Gold",
                  snout_role="ObsidianLight", nose="Gold", eyes={"glow": True}, head_role="Obsidian", toes="Gold")
    plates_on(c, ["ObsidianLight", "Obsidian"], g["body_c"], tuple(r + 0.07 for r in g["body_r"]), rows=5, per_row=7,
              theta=(-1.7, 1.7), size=(0.9, 1.0), thickness=0.3, lift=(2, 9))
    cracks_on(c, "Magma", g["body_c"], tuple(r + 0.2 for r in g["body_r"]), 9, segs=6, width=0.16, theta=(-1.6, 1.6))
    cracks_on(c, "MagmaHot", g["body_c"], tuple(r + 0.22 for r in g["body_r"]), 4, segs=4, width=0.12, theta=(-1.2, 1.2))
    spikes_on(c, "Obsidian", g["body_c"], g["body_r"], 9, 0.95, 0.26, theta=(-0.2, 0.2), tspan=(-0.85, 0.85), crystal=True)
    for side in (-1, 1):
        base = Vector((side * 0.5, g["hy"] + 0.1, g["hz"] + 0.6))
        chain_curve(c, "Gold", base, base + Vector((side * 0.5, 0.0, 0.35)), base + Vector((side * 0.85, -0.3, 0.75)),
                    base + Vector((side * 0.75, -0.6, 1.15)), 0.3, 0.1, n=6)
    for k in range(3):
        c.b.crystal("Gold", (-0.3 + 0.3 * k, g["hy"] + 0.25, g["hz"] + 0.75), (0, 0.2, 1), 0.55 - abs(k - 1) * 0.15, 0.12)
    for k in range(10):
        a = -1.9 + k * 0.42
        p = Vector((math.sin(a) * 0.95, -1.45, g["zb"] + 0.45 + math.cos(a) * 0.55))
        fur_plate(c.b, p, (math.sin(a), -0.5, math.cos(a)), (0, 0.3, -1), c.rng, 0.45, 0.75,
                  "MagmaHot" if k % 3 == 0 else "Magma", thickness=0.12)
    for x in (-0.3, 0.1, 0.35):
        c.b.box("Magma", (x, g["front"] - 0.4, g["hz"] - 0.75), (0.1, 0.1, 0.3), taper=(0.5, 0.5))
    pts = tail(c, "Obsidian", (0, 1.6, g["zb"] + 0.2), (0, 2.3, g["zb"]), (0.4, 2.8, g["zb"] - 0.5),
               (0.6, 3.1, g["zb"] - 0.7), 0.42, 0.18, n=6)
    ell(c, "MagmaHot", pts[-1], (0.26, 0.3, 0.26), step=0.15)


# ---------------------------------------------------------------------------
# Void family
# ---------------------------------------------------------------------------
def voidmote_wisp(c):
    orb = Vector((0, 0, 1.75))
    ell(c, "VoidGlass", orb, (0.85, 0.85, 0.85), step=0.24, vertical=True)
    ell(c, "CoreGlow", orb, (0.42, 0.42, 0.42), step=0.18, vertical=True)
    cute_eyes(c, 0.28, -0.88, 1.85, size=0.24, glow=True)
    for k in range(5):
        a = 2 * math.pi * k / 5 + 0.3
        base = orb + Vector((math.cos(a) * 0.45, math.sin(a) * 0.45, -0.6))
        chain_curve(c, "Wisp" if k % 2 else "WispLight", base, base + Vector((math.cos(a) * 0.3, math.sin(a) * 0.3, -0.4)),
                    base + Vector((math.cos(a + 1) * 0.2, math.sin(a + 1) * 0.4, -0.8)),
                    base + Vector((math.cos(a + 1.6) * 0.5, math.sin(a + 1.6) * 0.5, -1.0)), 0.18, 0.05, n=5)
    for k in range(3):
        base = orb + Vector((-0.3 + 0.3 * k, 0.1, 0.75))
        chain_curve(c, "WispLight", base, base + Vector((0, 0.1, 0.25)), base + Vector((0.15, 0.2, 0.45)),
                    base + Vector((0.05, 0.3, 0.6 - abs(k - 1) * 0.15)), 0.14, 0.04, n=4)
    for k in range(4):
        a = 2 * math.pi * k / 4 + 0.6
        c.b.box("VoidGlass", orb + Vector((math.cos(a) * 1.35, math.sin(a) * 1.35, 0.2 * math.sin(3 * a))), (0.2, 0.2, 0.2),
                euler_deg(45, 35, 0))
    c.socket("Head", tuple(orb + Vector((0, 0, 1.2))))
    c.socket("Mouth", tuple(orb + Vector((0, -0.9, -0.1))))
    c.socket("Back", tuple(orb + Vector((0, 0.5, 0.5))))
    c.socket("Feet", (0, 0, 0.4))
    c.socket("Chest", tuple(orb))


def gloomfang_wolf(c):
    g = quadruped(c, L=2.6, W=1.35, H=1.2, leg_h=1.1, leg_r=0.24, head_r=0.68, head_up=0.55,
                  snout=(0.48, 0.75, 0.4), body="Fur", belly="FurLight", leg="Fur", paw="FurLight",
                  snout_role="Fur", nose="Nose", eyes={"glow": True}, head_role="Fur")
    ears(c, "Fur", g, "pointy", size=0.62, inner="Mane", tilt=10)
    plates_on(c, ["Mane", "FurLight"], g["body_c"] + Vector((0, -0.45, 0.2)), (g["W"] / 2 + 0.1, 0.8, g["H"] / 2 + 0.1),
              rows=3, per_row=7, theta=(-1.8, 1.8), tspan=(-0.95, 0.4), size=(0.5, 0.85), thickness=0.14, lift=(10, 25))
    for side in (-1, 1):
        c.b.box("Bone", (side * 0.16, g["front"] - 0.5, g["hz"] - g["head_r"] * 0.5), (0.1, 0.08, 0.22), taper=(0.3, 0.3))
    pts = tail(c, "Fur", (0, 1.2, g["zb"] + 0.2), (0, 1.8, g["zb"] + 0.3), (0.2, 2.2, g["zb"] + 0.6),
               (0.3, 2.4, g["zb"] + 0.95), 0.3, 0.2, n=5)
    ell(c, "WispGlow", pts[-1], (0.24, 0.3, 0.24), step=0.12)
    for k in range(3):
        c.b.box("WispGlow", pts[-1] + Vector((0.1 * k, 0.15 * k + 0.2, 0.25 + 0.2 * k)), (0.12, 0.12, 0.12))
    cracks_on(c, "Glow", g["body_c"], tuple(r + 0.02 for r in g["body_r"]), 2, segs=4, width=0.09, theta=(1.0, 1.6))
    cracks_on(c, "Glow", g["body_c"], tuple(r + 0.02 for r in g["body_r"]), 2, segs=4, width=0.09, theta=(-1.6, -1.0))


def nullhorn_beast(c):
    g = quadruped(c, L=2.9, W=2.2, H=1.8, leg_h=0.95, leg_r=0.42, head_r=0.82, head_up=0.25,
                  snout=(0.75, 0.55, 0.55), body="Hide", belly="HideLight", leg="Hide", paw="Bone",
                  snout_role="Bone", nose="Hide", eyes={"glow": True}, head_role="Hide", toes="Bone")
    c.b.box("Bone", (0, g["front"] + 0.1, g["hz"] + 0.35), (1.0, 0.3, 0.45), euler_deg(-15, 0, 0))
    for side in (-1, 1):
        base = Vector((side * 0.55, g["hy"], g["hz"] + 0.45))
        chain_curve(c, "Bone", base, base + Vector((side * 0.55, -0.1, 0.25)), base + Vector((side * 0.85, -0.55, 0.65)),
                    base + Vector((side * 0.6, -0.95, 1.05)), 0.32, 0.1, n=7)
        base2 = Vector((side * 0.4, g["hy"] + 0.4, g["hz"] + 0.55))
        chain_curve(c, "Bone", base2, base2 + Vector((side * 0.2, 0.3, 0.3)), base2 + Vector((side * 0.3, 0.7, 0.35)),
                    base2 + Vector((side * 0.25, 0.95, 0.2)), 0.18, 0.06, n=4)
    plates_on(c, ["Mane", "HideLight"], g["body_c"] + Vector((0, -0.6, 0.25)), (g["W"] / 2 + 0.1, 0.9, g["H"] / 2 + 0.1),
              rows=3, per_row=7, theta=(-1.7, 1.7), tspan=(-0.95, 0.35), size=(0.6, 0.9), thickness=0.16, lift=(10, 22))
    for t, th in ((-0.1, 0.0), (0.35, 0.5), (0.55, -0.45), (0.1, -0.7)):
        p, n = surf(g["body_c"], g["body_r"], th, t)
        crystals(c, "VoidGlass", p, n, size=0.55, count=3, alt_role="Glow", alt_chance=0.25)
    cracks_on(c, "Glow", g["body_c"], tuple(r + 0.03 for r in g["body_r"]), 4, segs=4, width=0.1, theta=(-1.7, 1.7))
    pts = tail(c, "Hide", (0, 1.45, g["zb"] + 0.2), (0, 2.0, g["zb"]), (0.3, 2.4, g["zb"] + 0.1),
               (0.4, 2.6, g["zb"] + 0.4), 0.26, 0.12, n=5)
    crystals(c, "VoidGlass", pts[-1], pts[-1] - pts[-2], size=0.4, count=2)


def abyssbone_leviathan(c):
    path = [Vector(p) for p in ((1.7, 2.4, 0.32), (0.9, 2.8, 0.45), (-0.5, 2.5, 0.55), (-1.4, 1.4, 0.62),
                                (-1.1, 0.0, 0.7), (0.0, -0.45, 0.8), (0.75, 0.3, 1.25), (0.45, 0.2, 2.1),
                                (0.15, -0.5, 2.8), (0.0, -1.2, 3.15))]
    radii = [0.22, 0.32, 0.45, 0.58, 0.68, 0.74, 0.72, 0.66, 0.6, 0.56]
    for i in range(len(path) - 1):
        a, b_ = path[i], path[i + 1]
        d = b_ - a
        r = (radii[i] + radii[i + 1]) / 2
        mid = (a + b_) / 2
        ell(c, "Body" if i % 2 else "BodyLight", mid, (r, d.length * 0.62, r * 0.9), step=0.24, rot=basis_from_y(d, (0, 0, 1)))
        c.b.box("Belly", mid + Vector((0, 0, -r * 0.62)), (r * 1.2, d.length * 1.02, 0.18), basis_from_y(d, (0, 0, 1)))
        if 2 <= i <= 7:
            side_axis = d.normalized().cross(Vector((0, 0, 1)))
            if side_axis.length > 1e-3:
                side_axis.normalize()
                for s in (-1, 1):
                    rib_base = mid + side_axis * s * r * 0.75
                    c.b.box("Bone", rib_base + Vector((0, 0, r * 0.35)), (0.14, 0.16, r * 1.2),
                            basis_from_y(d, side_axis * s), taper=(0.5, 0.5))
            c.b.box("FinGlass", mid + Vector((0, 0, r * 0.95)), (0.08, d.length * 0.9, r * 0.9), basis_from_y(d, (0, 0, 1)),
                    taper=(1.0, 0.4))
            if i % 2 == 0:
                cracks_on(c, "Glow", mid, (r, d.length * 0.6, r * 0.9), 1, segs=3, width=0.09)
    head = Vector((0, -1.75, 3.2))
    ell(c, "Body", head, (0.7, 0.95, 0.6), step=0.24)
    c.b.box("Bone", head + Vector((0, -0.35, 0.35)), (1.05, 1.25, 0.25), euler_deg(-6, 0, 0))
    c.b.box("Bone", head + Vector((0, -0.75, -0.45)), (0.85, 0.9, 0.2))
    for x in (-0.3, -0.1, 0.1, 0.3):
        c.b.box("Bone", head + Vector((x, -1.15, -0.25)), (0.09, 0.08, 0.2), taper=(0.3, 0.3))
    cute_eyes(c, 0.36, head.y - 0.9, head.z + 0.12, size=0.26, glow=True)
    for side in (-1, 1):
        base = head + Vector((side * 0.45, 0.2, 0.4))
        chain_curve(c, "Bone", base, base + Vector((side * 0.3, 0.4, 0.3)), base + Vector((side * 0.45, 0.85, 0.5)),
                    base + Vector((side * 0.4, 1.2, 0.35)), 0.2, 0.06, n=5)
        c.b.box("Fin", head + Vector((side * 0.72, 0.3, 0.0)), (0.1, 0.9, 0.8), euler_deg(0, 0, side * 25), taper=(1.0, 0.3))
    for k in range(3):
        a = 1.2 + k * 1.9
        crystals(c, "FinGlass", (math.cos(a) * 2.2, 1.0 + math.sin(a) * 1.4, 0.2), (0, 0, 1), size=0.5, count=2, alt_role="Glow",
                 alt_chance=0.3)
    c.socket("Head", tuple(head + Vector((0, 0, 1.0))))
    c.socket("Mouth", tuple(head + Vector((0, -1.2, -0.3))))
    c.socket("Back", tuple(path[6] + Vector((0, 0, 1.0))))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", tuple(path[7]))


# ---------------------------------------------------------------------------
# Celestial family
# ---------------------------------------------------------------------------
def starfrost_owl(c):
    ell(c, "FeatherBlue", (0, 0.05, 1.35), (0.95, 1.25, 0.9), step=0.26, vertical=True)
    ell(c, "Feather", (0, -0.45, 1.25), (0.68, 0.95, 0.5), step=0.24, vertical=True)
    spots_on(c, "FeatherDark", (0, -0.45, 1.25), (0.68, 0.5, 0.95), 9, 0.14, theta=(2.0, 4.3), tspan=(-0.95, -0.55))
    ell(c, "FeatherBlue", (0, -0.05, 2.65), (0.85, 0.7, 0.75), step=0.22, vertical=True)
    for side in (-1, 1):
        c.b.box("Feather", (side * 0.36, -0.8, 2.68), (0.62, 0.1, 0.62))
        c.b.box("FeatherDark", (side * 0.62, -0.25, 3.35), (0.22, 0.2, 0.55), euler_deg(0, side * -25, 0), taper=(0.3, 0.6))
        for r_ in range(3):
            fur_plate(c.b, Vector((side * 0.88, -0.1 + r_ * 0.3, 2.0 - r_ * 0.15)), (side, 0.2, 0.2), (0, 0.4, -1), c.rng,
                      0.6, 1.1 - r_ * 0.15, c.pick("FeatherBlue", "FeatherDark"), thickness=0.12, lift=(2, 6))
        c.b.box("Talon", (side * 0.32, -0.45, 0.12), (0.32, 0.45, 0.24))
        for t in (-1, 0, 1):
            c.b.box("Talon", (side * 0.32 + t * 0.12, -0.75, 0.08), (0.08, 0.22, 0.12), taper=(0.4, 0.4))
        crystals(c, "StarGlass", (side * 1.0, 0.55, 1.15), (side * 0.3, 0.6, -0.4), size=0.3, count=1)
    cute_eyes(c, 0.36, -0.86, 2.7, size=0.42, iris="Iris")
    c.b.box("Beak", (0, -0.88, 2.4), (0.2, 0.2, 0.3), euler_deg(20, 0, 0), taper=(0.3, 0.3))
    for k in range(3):
        fur_plate(c.b, Vector((-0.25 + k * 0.25, 0.85, 0.9)), (0, 1, 0), (0, 0.5, -1), c.rng, 0.35, 0.7,
                  c.pick("FeatherBlue", "FeatherDark"), thickness=0.1)
    crystals(c, "StarGlass", (0, -0.15, 3.35), (0, 0, 1), size=0.55, count=3, alt_role="StarGlass2", alt_chance=0.4)
    c.socket("Head", (0, -0.05, 3.8))
    c.socket("Mouth", (0, -0.95, 2.4))
    c.socket("Back", (0, 0.6, 2.2))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -0.8, 1.4))


def glacierhorn_elk(c):
    g = quadruped(c, L=2.6, W=1.45, H=1.35, leg_h=1.6, leg_r=0.22, head_r=0.62, head_up=1.05, head_fwd=0.35,
                  neck=0.55, snout=(0.5, 0.7, 0.45), body="Body", belly="Belly", leg="Body", paw="Hoof",
                  snout_role="Body", nose="Nose", eyes={"size": 0.27}, head_role="Body")
    plates_on(c, ["FurWhite", "FurIce", "FurBlue", "FurNavy"], g["body_c"], tuple(r + 0.06 for r in g["body_r"]),
              rows=5, per_row=8, theta=(-1.9, 1.9), size=(0.6, 0.95), thickness=0.16, lift=(5, 16))
    for k in range(6):
        a = -1.2 + k * 0.48
        fur_plate(c.b, Vector((math.sin(a) * 0.4, -1.35 + abs(a) * 0.1, g["zb"] + 0.65 + math.cos(a) * 0.2)),
                  (math.sin(a), -0.6, math.cos(a)), (0, -0.2, -1), c.rng, 0.4, 0.9, "FurWhite", thickness=0.12)
    antlers(c, "AntlerGlass", g, spread=0.4, height=1.55, tines=3, tip_roles=("AntlerGlass",), glass=True, size=0.15)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * g["W"] * 0.32, sy * g["L"] * 0.3
            for k in range(6):
                a = 2 * math.pi * k / 6
                fur_plate(c.b, Vector((x + math.cos(a) * 0.24, y + math.sin(a) * 0.24, 0.75)), (math.cos(a), math.sin(a), 0),
                          (0, 0, -1), c.rng, 0.22, 0.45, "FurWhite", thickness=0.08, lift=(4, 10))
    ell(c, "FurWhite", (0, 1.35, g["zb"] + 0.3), (0.28, 0.25, 0.3), step=0.14)


def frostroot_wyrmling(c):
    ell(c, "Scale", (0, 0.15, 1.15), (1.1, 1.05, 1.0), step=0.26, vertical=True)
    ell(c, "Belly", (0, -0.55, 1.05), (0.75, 0.85, 0.45), step=0.24, vertical=True)
    for k in range(5):
        c.b.box("ScaleLight", (0, -0.98, 0.45 + k * 0.32), (0.9 - abs(k - 2) * 0.12, 0.08, 0.1))
    head = Vector((0, -0.35, 2.6))
    ell(c, "Scale", head, (0.85, 0.75, 0.8), step=0.22, vertical=True)
    c.b.box("Scale", head + Vector((0, -0.85, -0.25)), (0.75, 0.55, 0.5))
    for side in (-1, 1):
        c.b.box("Mouth", head + Vector((side * 0.18, -1.13, -0.1)), (0.1, 0.06, 0.08))
    cute_eyes(c, 0.38, head.y - 0.76, head.z + 0.12, size=0.38, iris="Iris")
    smile(c, head.y - 1.13, head.z - 0.38, width=0.45)
    for side in (-1, 1):
        base = head + Vector((side * 0.45, 0.15, 0.6))
        pts = chain_curve(c, "Root", base, base + Vector((side * 0.25, 0.25, 0.4)), base + Vector((side * 0.5, 0.55, 0.65)),
                          base + Vector((side * 0.6, 0.85, 0.6)), 0.16, 0.07, n=5)
        tip = pts[2] + Vector((side * 0.1, -0.2, 0.4))
        c.b.chain("Root", [pts[2], tip], [0.08], roll_hint=(0, 0, 1), taper_last=(0.5, 0.5))
        c.b.box("Scale", (side * 0.55, -0.85, 1.2), (0.3, 0.35, 0.55))
        c.b.box("ScaleLight", (side * 0.55, -1.05, 0.95), (0.32, 0.18, 0.15))
        ell(c, "Scale", (side * 0.75, -0.2, 0.45), (0.4, 0.5, 0.42), step=0.2)
        c.b.box("ScaleLight", (side * 0.8, -0.85, 0.12), (0.5, 0.55, 0.24))
    wings(c, "Scale", "WingGlass", (0.5, 0.4, 1.75), span=1.6, height=1.2, back=0.5, fingers=3, raise_deg=35)
    for k in range(5):
        crystals(c, "CrystalGlass", (0, 0.75 + k * 0.05, 2.1 - k * 0.35), (0, 0.7, 1), size=0.45 - k * 0.05, count=2,
                 alt_role="CrystalViolet", alt_chance=0.3)
    pts = tail(c, "Scale", (0, 1.05, 0.5), (0.4, 1.6, 0.25), (1.3, 1.2, 0.2), (1.5, 0.3, 0.2), 0.36, 0.14, n=7)
    crystals(c, "CrystalGlass", pts[-1], (0.3, -0.5, 0.8), size=0.5, count=3, alt_role="CrystalViolet", alt_chance=0.4)
    for k in range(5):
        fur_plate(c.b, Vector((-0.4 + k * 0.2, -0.85, 1.85)), (0, -1, 0.3), (0, 0, -1), c.rng, 0.28, 0.45, "FurWhite",
                  thickness=0.1)
    c.socket("Head", tuple(head + Vector((0, 0, 1.0))))
    c.socket("Mouth", tuple(head + Vector((0, -1.15, -0.25))))
    c.socket("Back", (0, 0.6, 2.2))
    c.socket("Feet", (0, 0, 0.05))
    c.socket("Chest", (0, -0.9, 1.2))


# ---------------------------------------------------------------------------
# Eggs (sit on the ground; decoration grows with rarity)
# ---------------------------------------------------------------------------
def egg_body(c, height, R, pattern, layers=11):
    def rad(t):
        s = 2 * t - 1
        return R * math.sqrt(max(0.0, 1 - s * s)) * (1 - 0.16 * s)
    for i in range(layers):
        t = (i + 0.5) / layers
        r = rad(t)
        th = height / layers * 1.04
        role = pattern(i, t)
        for w, d, depth in ((2.0, 1.25, 1.0), (1.25, 2.0, 0.86), (1.68, 1.68, 0.74)):
            c.b.box(role, (0, 0, t * height), (r * w, r * d, th * depth))
    c.socket("EggCenter", (0, 0, height * 0.45))
    c.socket("Ground", (0, 0, 0.05))
    c.socket("Crown", (0, 0, height + 0.7))
    c.socket("Feet", (0, 0, 0.05))
    return rad


def egg_point(rad, height, t, a, out=0.0):
    r = rad(t) + out
    slope = (rad(min(t + 0.02, 1)) - rad(max(t - 0.02, 0))) / (0.04 * height)
    n = Vector((math.cos(a), math.sin(a), -slope)).normalized()
    return Vector((math.cos(a) * r, math.sin(a) * r, t * height)), n


def egg_ring(c, role, rad, height, t, count, size=(0.45, 0.3, 0.2), out=0.03, dash=1.0):
    for k in range(count):
        a = 2 * math.pi * k / count
        p, n = egg_point(rad, height, t, a, out)
        c.b.box(role, p, (size[0] * dash, size[1], size[2]), basis(n, (0, 0, 1)))


def egg_spots(c, role, rad, height, count, size, tmin=0.15, tmax=0.85, out=0.04):
    for _ in range(count):
        p, n = egg_point(rad, height, c.rng.uniform(tmin, tmax), c.rng.uniform(0, 2 * math.pi), out)
        s = size * c.rng.uniform(0.75, 1.25)
        c.b.box(role, p, (s, s, s * 0.4), basis(n, (0, 0, 1)))


def egg_cracks(c, role, rad, height, count, segs=6, width=0.16, tmin=0.08, tmax=0.92, out=0.05):
    """Zig-zag glowing seams that follow the egg's real surface top to bottom."""
    rng = c.rng
    for _ in range(count):
        a = rng.uniform(0, 2 * math.pi)
        t = rng.uniform(tmax - 0.25, tmax)
        prev, n = egg_point(rad, height, t, a, out)
        for _ in range(segs):
            a += rng.choice((-1, 1)) * rng.uniform(0.12, 0.3)
            t = max(tmin, t - rng.uniform(0.08, 0.14))
            cur, n = egg_point(rad, height, t, a, out)
            d = cur - prev
            if d.length > 1e-3:
                c.b.box(role, (prev + cur) / 2, (width, d.length * 1.15, width * 0.6), basis_from_y(d, n))
            prev = cur


def fernleaf_egg(c):
    h = 4.3
    rad = egg_body(c, h, 1.55, lambda i, t: "ShellLight" if i % 3 == 1 else "Shell")
    egg_spots(c, "Speckle", rad, h, 8, 0.2)
    for k in range(3):
        a = 2 * math.pi * k / 3 + 0.4
        d = Vector((math.cos(a), math.sin(a), 0))
        base = d * 1.2 + Vector((0, 0, 0.15))
        frond(c, "Frond", base, base + d * 0.75 + Vector((0, 0, 1.0)), base + d * 0.7 + Vector((0, 0, 2.0)),
              base + d * 0.3 + Vector((0, 0, 2.6)), leaflets=6, size=0.58, alt="FrondLight")
    top = Vector((0, 0, h - 0.05))
    frond(c, "Frond", top, top + Vector((0, 0, 0.4)), top + Vector((0.2, 0, 0.75)), top + Vector((0.45, 0, 0.85)),
          leaflets=3, size=0.32)


def toadstool_egg(c):
    h = 4.5
    rad = egg_body(c, h, 1.6, lambda i, t: ("Cap" if i % 3 else "CapDark") if t > 0.55 else ("Stem" if i % 2 else "StemShade"))
    ell(c, "CapDark", (0, 0, h * 0.55), (1.6 * 1.12, 0.12, 1.6 * 1.12), step=0.12, vertical=True)
    egg_ring(c, "Gill", rad, h, 0.5, 14, size=(0.5, 0.35, 0.14), out=0.0)
    egg_spots(c, "Spots", rad, h, 11, 0.32, tmin=0.6, tmax=0.95, out=0.06)
    for k in range(2):
        a = 0.9 + k * 2.6
        base = Vector((math.cos(a) * 1.6, math.sin(a) * 1.6, 0))
        c.b.box("Stem", base + Vector((0, 0, 0.18)), (0.18, 0.18, 0.36))
        ell(c, "Cap", base + Vector((0, 0, 0.42)), (0.3, 0.14, 0.3), step=0.07, vertical=True, profile=DOME)
        c.b.box("Spots", base + Vector((0.05, -0.05, 0.53)), (0.08, 0.08, 0.04))


def crystal_egg(c):
    h = 4.5
    rad = egg_body(c, h, 1.6, lambda i, t: "ShellLight" if i % 3 == 1 else "Shell")
    egg_spots(c, "Facet", rad, h, 10, 0.32)
    for k in range(3):
        a = 2 * math.pi * k / 3 + 0.2
        p, n = egg_point(rad, h, 0.35 + 0.15 * (k % 2), a, -0.1)
        crystals(c, "CrystalGlass", p, n + Vector((0, 0, 0.4)), size=0.55, count=3, alt_role="CrystalGlass2", alt_chance=0.35)
    crystals(c, "CrystalGlass", (0, 0, h - 0.1), (0, 0, 1), size=0.7, count=4, alt_role="CrystalGlass2", alt_chance=0.4)


def geode_egg(c):
    h = 4.8
    rad = egg_body(c, h, 1.7, lambda i, t: ("RockLight", "Rock", "RockDark")[i % 3])
    egg_spots(c, "Crust", rad, h, 12, 0.35)
    egg_spots(c, "Gold", rad, h, 8, 0.12, out=0.06)
    a = -math.pi / 2  # opening faces front (-Y)
    centre, n = egg_point(rad, h, 0.45, a, 0.0)
    side = n.cross(Vector((0, 0, 1))).normalized()
    for k in range(12):
        ang = 2 * math.pi * k / 12
        offset = side * math.cos(ang) * 0.75 + Vector((0, 0, 1)) * math.sin(ang) * 0.85
        c.b.box("RockLight", centre + offset + n * 0.08, (0.4, 0.4, 0.3), basis(n, (0, 0, 1)))
    c.b.box("CoreGlow", centre - n * 0.1, (1.0, 1.1, 0.12), basis(n, (0, 0, 1)))
    for k in range(7):
        ang = 2 * math.pi * k / 7
        p = centre + side * math.cos(ang) * 0.4 + Vector((0, 0, math.sin(ang) * 0.45)) - n * 0.05
        c.b.crystal("CrystalGlass" if k % 2 else "CrystalGlass2", p, n + (p - centre) * 0.6, 0.55, 0.13)
    crystals(c, "CrystalGlass", (0, 0, h - 0.1), (0, 0, 1), size=0.5, count=3)


def lava_egg(c):
    h = 4.8
    rad = egg_body(c, h, 1.7, lambda i, t: "Char" if i % 3 == 1 else "Basalt")
    egg_cracks(c, "MagmaGlow", rad, h, 6, segs=7, width=0.18)
    egg_cracks(c, "MagmaHot", rad, h, 3, segs=4, width=0.13, out=0.08)
    egg_ring(c, "MagmaGlow", rad, h, 0.06, 12, size=(0.5, 0.2, 0.18), out=0.05)
    for k in range(3):
        a = 2 * math.pi * k / 3
        c.b.crystal("Basalt", (math.cos(a) * 0.35, math.sin(a) * 0.35, h - 0.15), (math.cos(a) * 0.4, math.sin(a) * 0.4, 1), 0.7, 0.18)
    for k in range(4):
        a = 2 * math.pi * k / 4 + 0.4
        c.b.box("MagmaHot", (math.cos(a) * 0.2, math.sin(a) * 0.2, h + 0.1), (0.16, 0.16, 0.16), euler_deg(30, 20, 0))


def obsidian_egg(c):
    h = 5.1
    rad = egg_body(c, h, 1.8, lambda i, t: "ObsidianLight" if i % 3 == 1 else "Obsidian")
    for t in (0.28, 0.68):
        egg_ring(c, "Gold", rad, h, t, 16, size=(0.6, 0.28, 0.16), out=0.04)
    for k in range(6):
        a = 2 * math.pi * k / 6 + 0.25
        prev = None
        for j in range(7):
            t = 0.15 + j * 0.11
            p, n = egg_point(rad, h, t, a + 0.08 * math.sin(j * 1.7), 0.03)
            if prev is not None:
                d = p - prev
                c.b.box("MagmaGlow", (p + prev) / 2, (0.12, d.length * 1.1, 0.08), basis_from_y(d, n))
            prev = p
    for k in range(6):
        a = 2 * math.pi * k / 6
        c.b.crystal("Obsidian", (math.cos(a) * 0.45, math.sin(a) * 0.45, h - 0.25), (math.cos(a) * 0.5, math.sin(a) * 0.5, 1), 0.95, 0.2)
    c.b.crystal("MagmaGlow", (0, 0, h - 0.2), (0, 0, 1), 0.9, 0.18)
    egg_spots(c, "Gold", rad, h, 6, 0.12, out=0.05)


def void_egg(c):
    h = 5.1
    rad = egg_body(c, h, 1.8, lambda i, t: ("Void", "Dusk", "Void", "Plum")[i % 4])
    for t in (0.33, 0.66):
        egg_ring(c, "Glow", rad, h, t, 18, size=(0.3, 0.16, 0.12), out=0.05, dash=1.0)
    egg_spots(c, "Plum", rad, h, 8, 0.3)
    crystals(c, "VoidGlass", (0, 0, h - 0.1), (0, 0, 1), size=0.8, count=5, alt_role="Glow", alt_chance=0.3)
    for k in range(5):
        a = 2 * math.pi * k / 5 + 0.5
        p, n = egg_point(rad, h, 0.55 + 0.08 * (k % 2), a, 0.65)
        c.b.box("VoidGlass", p, (0.24, 0.24, 0.24), euler_deg(45, 35, k * 20))
    for side in (-1, 1):
        p, n = egg_point(rad, h, 0.72, math.pi / 2 + side * math.pi / 2, -0.1)
        chain_curve(c, "Bone", p, p + n * 0.4 + Vector((0, 0, 0.2)), p + n * 0.6 + Vector((0, 0, 0.6)),
                    p + n * 0.45 + Vector((0, 0, 0.95)), 0.2, 0.06, n=5)


# ---------------------------------------------------------------------------
# The bestiary: stats from the game config, palettes, builders, idle style
# ---------------------------------------------------------------------------
def M(asset, display, rarity, chance, cash, strength, luck, builder, colors, idle="Breathe", scale=None):
    spec = dict(kind="Monster", asset=asset, display=display, rarity=rarity, builder=builder, colors=colors, idle=idle,
                attributes=dict(MonsterName=display, Rarity=rarity, HatchChance=chance, CashPerSecond=cash,
                                StrengthMultiplier=strength, LuckMultiplier=luck))
    if scale:
        spec["scale"] = scale
    return spec


def E(asset, display, rarity, hatch_seconds, sell, areas, builder, colors):
    return dict(kind="Egg", asset=asset, display=display, rarity=rarity, builder=builder, colors=colors, idle="Rock",
                scale=1.0, attributes=dict(EggName=display, Rarity=rarity, HatchSeconds=hatch_seconds, SellPrice=sell,
                                           DropAreas=areas))


WOOD = dict(Leaf="#7CC242", LeafLight="#B5E36A", LeafDark="#4F8A2E", Moss="#4F8A2E")
FERN = dict(Frond="#3E8E3A", FrondLight="#7CC242")
CELESTIAL = dict(FurWhite="#EEF5FF", FurIce="#A9D3FF", FurBlue="#4C8FE6", FurNavy="#1C3F8F")

FAMILIES = [
    dict(family="Mossbark", theme="Wood", egg=None, monsters=[
        M("TwigrootBoar", "Twigroot Boar", "Uncommon", 0.28, 5, 1.2, 1.05, twigroot_boar,
          dict(Body="#8A5A3B", Belly="#C9A27A", Snout="#E8A98A", Nose="#5A3B22", Paw="#4A3020", Tusk="#EFE3C2",
               Twig="#6B4A2B", **WOOD), idle="Hop"),
        M("BarkhornStag", "Barkhorn Stag", "Rare", 0.10, 14, 1.35, 1.1, barkhorn_stag,
          dict(Body="#B07A4A", Belly="#F1E2C4", Snout="#8A5A3B", Nose="#3A2516", Hoof="#4A3020", Bark="#6B4A2B",
               Bark2="#7A5230", Antler="#7A5230", Spots="#FFF7EC", Paw="#4A3020", **WOOD)),
        M("OakheartGolem", "Oakheart Golem", "Epic", 0.02, 40, 1.6, 1.2, oakheart_golem,
          dict(Bark="#6B4A2B", BarkLight="#8A5A3B", Root="#5A3B22", CoreGlow="#B8FF7A", EyeGlow="#B8FF7A",
               Shroom="#E5402F", ShroomSpots="#FFF7EC", **WOOD)),
    ]),
    dict(family="Fernleaf", theme="Fern", egg=E("FernleafEgg", "Fernleaf Egg", "Uncommon", 25, 80, "1-2", fernleaf_egg,
                                                  dict(Shell="#5FA83A", ShellLight="#8ED160", Speckle="#EFE6C8", **FERN)),
         monsters=[
        M("FernlingSnail", "Fernling Snail", "Common", 0.58, 6, 1.2, 1.0, fernling_snail,
          dict(Body="#F1E2C4", Shell="#4E9A3A", ShellLight="#8ED160", **FERN), idle="Hop"),
        M("LeafwingBeetle", "Leafwing Beetle", "Uncommon", 0.29, 15, 1.3, 1.05, leafwing_beetle,
          dict(Body="#2F5D2B", Shell="#6DBE45", ShellLight="#B5E36A", Leg="#2B2B22", Horn="#3E4A2B"), idle="Hop"),
        M("ThornbackHedgehog", "Thornback Hedgehog", "Rare", 0.11, 40, 1.45, 1.12, thornback_hedgehog,
          dict(Body="#8A5A3B", Face="#F1E2C4", Spike="#5A3B22", SpikeTip="#EFE3C2", Leaf="#66B84A", Berry="#E5402F",
               Nose="#1B1B1B"), idle="Hop"),
        M("ElderfernTreant", "Elderfern Treant", "Epic", 0.02, 115, 1.75, 1.25, elderfern_treant,
          dict(Bark="#5E4127", BarkLight="#7A5434", Root="#4A321E", Moss="#3E8E3A", Beard="#5FA83A", EyeGlow="#CFFF8A",
               Hand="#7A5434", Foot="#4A321E", **FERN)),
    ]),
    dict(family="Toadstool", theme="Toadstool", egg=E("ToadstoolEgg", "Toadstool Egg", "Rare", 40, 300, "1-3", toadstool_egg,
                                                      dict(Stem="#F1E2C4", StemShade="#E0CFAE", Cap="#E5402F", CapDark="#B8321F",
                                                           Spots="#FFF7EC", Gill="#E8D7B5")),
         monsters=[
        M("SpotcapFrog", "Spotcap Frog", "Common", 0.56, 18, 1.4, 1.05, spotcap_frog,
          dict(Body="#4FB3A0", Belly="#F1E7C2", Toes="#7FD3C0", Cap="#A0522D", Spots="#FFF7EC"), idle="Hop"),
        M("PuffballBunny", "Puffball Bunny", "Uncommon", 0.30, 45, 1.55, 1.1, puffball_bunny,
          dict(Fur="#FFF7EC", Belly="#FFFFFF", Inner="#FFB3C1", Nose="#FF8FA3", Puff="#E9D9B8", PuffSpots="#C9B48A"),
          idle="Hop"),
        M("SporecloakFox", "Sporecloak Fox", "Rare", 0.11, 120, 1.75, 1.2, sporecloak_fox,
          dict(Fur="#E8772E", Belly="#FFF7EC", Dark="#3A2516", Nose="#2A1A12", Cape="#E5402F", CapeDark="#B8321F",
               CapeSpots="#FFF7EC", Gill="#F1E2C4", Iris="#7A4A1E", Paw="#3A2516")),
        M("ToadstoolTitan", "Toadstool Titan", "Legendary", 0.03, 380, 2.1, 1.35, toadstool_titan,
          dict(Stem="#F1E2C4", StemShade="#E0CFAE", Cap="#D93A2B", CapDark="#A82A1F", Spots="#FFF7EC", SpotGlow="#FFF2B0",
               Gill="#E8D7B5", Root="#8A5A3B", Moss="#4F8A2E", EyeGlow="#FFE27A", Hand="#8A5A3B", Foot="#8A5A3B")),
    ]),
    dict(family="Crystal", theme="Crystal", egg=E("CrystalEgg", "Crystal Egg", "Rare", 60, 2500, "2-4", crystal_egg,
                                                  dict(Shell="#B79CEB", ShellLight="#D9CCF5", Facet="#F2E9FF",
                                                       CrystalGlass="#C9A0FF", CrystalGlass2="#F2E9FF")),
         monsters=[
        M("QuartzpawKit", "Quartzpaw Kit", "Common", 0.55, 150, 2.0, 1.1, quartzpaw_kit,
          dict(Fur="#CBB8F0", Belly="#F2E9FF", Paw="#F2E9FF", Nose="#7B5CD6", Iris="#7B5CD6", CrystalGlass="#E9DDFF"),
          idle="Hop"),
        M("AmethystMoth", "Amethyst Moth", "Uncommon", 0.30, 400, 2.4, 1.2, amethyst_moth,
          dict(Body="#6B4FA0", Fuzz="#F2E9FF", WingGlass="#B48CFF", WingVein="#7B5CD6", Antenna="#3B2A5E", Iris="#3B2A5E"),
          idle="Hover"),
        M("PrismhornRam", "Prismhorn Ram", "Rare", 0.12, 1100, 3.0, 1.3, prismhorn_ram,
          dict(Wool="#F2E9FF", WoolShade="#D9CCF5", Face="#8C93A3", Hoof="#4A4458", HornGlass="#C9A0FF")),
        M("GeodebackTortoise", "Geodeback Tortoise", "Legendary", 0.03, 3500, 4.0, 1.5, geodeback_tortoise,
          dict(Skin="#8C93A3", SkinDark="#6E7585", Shell="#5E5966", ShellRim="#A39E8F", CrystalGlass="#B48CFF",
               CrystalGlass2="#E9DDFF", CoreGlow="#C9A0FF", Gold="#F3C64A")),
    ]),
    dict(family="Geode", theme="Geode", egg=E("GeodeEgg", "Geode Egg", "Epic", 90, 40000, "2-5", geode_egg,
                                              dict(Rock="#7F7A86", RockDark="#5E5966", RockLight="#A39E8F", Crust="#C8C1B4",
                                                   Gold="#F3C64A", CrystalGlass="#8A4FD8", CrystalGlass2="#6FE3FF",
                                                   CoreGlow="#C9A0FF")),
         monsters=[
        M("ShardlingMole", "Shardling Mole", "Uncommon", 0.55, 1500, 3.2, 1.25, shardling_mole,
          dict(Fur="#6E6577", Belly="#9A92A8", Nose="#FF9FB0", ClawGlass="#B48CFF"), idle="Hop"),
        M("DruzyLynx", "Druzy Lynx", "Rare", 0.30, 4200, 3.8, 1.35, druzy_lynx,
          dict(Fur="#9A92A8", Belly="#E8E2EC", Spots="#5E5966", Tuft="#3B3346", Nose="#3B3346", Iris="#D9A23A",
               DruzyGlass="#8A4FD8", DruzyGlass2="#6FE3FF")),
        M("GemhornRhino", "Gemhorn Rhino", "Epic", 0.12, 12000, 4.6, 1.5, gemhorn_rhino,
          dict(Hide="#7F7A86", HideDark="#5E5966", Plate="#A39E8F", GemGlass="#6FE3FF", GemGlow="#C8FAFF", Gold="#F3C64A")),
        M("PrismaticBasilisk", "Prismatic Basilisk", "Mythic", 0.03, 38000, 6.0, 1.8, prismatic_basilisk,
          dict(Scale="#2E6E8E", ScaleLight="#4FB3C8", Belly="#E8E2D4", CrestGlass1="#FF7BD5", CrestGlass2="#7FEAFF",
               CrestGlass3="#F3E37A", SpineGlow="#FFFFFF", EyeGlow="#F3E37A")),
    ]),
    dict(family="Lava", theme="Lava", egg=E("LavaEgg", "Lava Egg", "Epic", 120, 400000, "3-5", lava_egg,
                                            dict(Basalt="#2B2422", Char="#4A3A33", MagmaGlow="#FF7A1A", MagmaHot="#FFC24A")),
         monsters=[
        M("CinderpawPup", "Cinderpaw Pup", "Uncommon", 0.55, 15000, 5.0, 1.3, cinderpaw_pup,
          dict(Fur="#4A3A33", Belly="#7A6E68", EmberGlow="#FF7A1A", Nose="#1B1B1B"), idle="Hop"),
        M("MagmashellCrab", "Magmashell Crab", "Rare", 0.30, 40000, 6.5, 1.4, magmashell_crab,
          dict(Shell="#2B2422", ShellLight="#4A3A33", Claw="#C2461B", MagmaGlow="#FF7A1A", Leg="#3A2E2A"), idle="Hop"),
        M("EmberwingDrake", "Emberwing Drake", "Epic", 0.12, 120000, 8.0, 1.6, emberwing_drake,
          dict(Scale="#C2461B", ScaleDark="#7A2A12", Belly="#F2A33A", Horn="#2B2422", WingGlass="#FF8A2A",
               EmberGlow="#FFC24A", Iris="#FFC24A")),
        M("ObsidianColossus", "Obsidian Colossus", "Mythic", 0.03, 400000, 11.0, 2.0, obsidian_colossus,
          dict(Rock="#2B2422", RockLight="#4A3A33", Obsidian="#17141C", MagmaGlow="#FF7A1A", MagmaGlow2="#FFC24A",
               Ash="#7A6E68", EyeGlow="#FFC24A", Hand="#17141C", Foot="#17141C")),
    ]),
    dict(family="Obsidian", theme="Obsidian", egg=E("ObsidianEgg", "Obsidian Egg", "Legendary", 180, 6000000, "3-5",
                                                    obsidian_egg, dict(Obsidian="#17141C", ObsidianLight="#2C2633",
                                                                       Gold="#E8B04A", MagmaGlow="#FF5A1F")),
         monsters=[
        M("AshenImp", "Ashen Imp", "Rare", 0.55, 150000, 9.0, 1.6, ashen_imp,
          dict(Skin="#5B5560", SkinDark="#3A353F", Horn="#17141C", EyeGlow="#FF5A1F", Wing="#2C2633", Tooth="#F4F0E8",
               EmberGlow="#FF5A1F", Hand="#3A353F", Foot="#3A353F"), idle="Hop"),
        M("SlagbackBoar", "Slagback Boar", "Epic", 0.30, 420000, 10.5, 1.8, slagback_boar,
          dict(Hide="#3A353F", HideLight="#5B5560", Snout="#5B5560", Slag="#17141C", Slag2="#2C2633", SlagGlow="#FF5A1F",
               Tusk="#E8B04A", Mane="#2C2633", EyeGlow="#FF5A1F", Paw="#17141C")),
        M("BasaltWyvern", "Basalt Wyvern", "Legendary", 0.12, 1200000, 12.5, 2.1, basalt_wyvern,
          dict(Scale="#2C2633", ScaleLight="#4A4452", Basalt="#17141C", Glow="#FF5A1F", Wing="#1F1A24", Horn="#E8B04A",
               EyeGlow="#FF5A1F")),
        M("MoltenBehemoth", "Molten Behemoth", "Divine", 0.03, 4000000, 16.0, 2.6, molten_behemoth,
          dict(Obsidian="#17141C", ObsidianLight="#2C2633", Magma="#FF5A1F", MagmaHot="#FFC24A", Gold="#E8B04A",
               EyeGlow="#FFC24A")),
    ]),
    dict(family="Void", theme="Void", egg=E("VoidEgg", "Void Egg", "Legendary", 240, 60000000, "4-5", void_egg,
                                            dict(Void="#1E1630", Dusk="#3B2A5E", Plum="#6A3FA0", Glow="#B98CFF",
                                                 VoidGlass="#9B5CFF", Bone="#E6E0D2")),
         monsters=[
        M("VoidmoteWisp", "Voidmote Wisp", "Rare", 0.55, 1500000, 12.0, 1.8, voidmote_wisp,
          dict(VoidGlass="#9B5CFF", CoreGlow="#E6D2FF", Wisp="#3B2A5E", WispLight="#6A3FA0", EyeGlow="#FFFFFF"),
          idle="Hover"),
        M("GloomfangWolf", "Gloomfang Wolf", "Epic", 0.30, 4000000, 15.0, 2.2, gloomfang_wolf,
          dict(Fur="#2A1F3D", FurLight="#3B2A5E", Mane="#6A3FA0", Bone="#E6E0D2", Nose="#120C1E", EyeGlow="#B98CFF",
               WispGlow="#9B5CFF", Glow="#B98CFF")),
        M("NullhornBeast", "Nullhorn Beast", "Legendary", 0.12, 11000000, 19.0, 2.7, nullhorn_beast,
          dict(Hide="#1E1630", HideLight="#3B2A5E", Bone="#E6E0D2", Mane="#6A3FA0", VoidGlass="#9B5CFF", Glow="#D7B8FF",
               EyeGlow="#D7B8FF")),
        M("AbyssboneLeviathan", "Abyssbone Leviathan", "Divine", 0.03, 35000000, 25.0, 3.5, abyssbone_leviathan,
          dict(Body="#1E1630", BodyLight="#3B2A5E", Belly="#4A3A6E", Bone="#E6E0D2", Fin="#6A3FA0", FinGlass="#9B5CFF",
               Glow="#D7B8FF", EyeGlow="#D7B8FF")),
    ]),
    dict(family="Celestial", theme="Celestial", egg=None, monsters=[
        M("StarfrostOwl", "Starfrost Owl", "Epic", 0.60, 50000000, 26.0, 3.5, starfrost_owl,
          dict(Feather="#EEF5FF", FeatherBlue="#4C8FE6", FeatherDark="#23489E", Beak="#F3C64A", Talon="#1C3F8F",
               Iris="#F3C64A", StarGlass="#7FEAFF", StarGlass2="#B48CFF")),
        M("GlacierhornElk", "Glacierhorn Elk", "Legendary", 0.30, 90000000, 32.0, 4.5, glacierhorn_elk,
          dict(Body="#23489E", Belly="#CFE6FF", Hoof="#1C3F8F", Nose="#0E1630", AntlerGlass="#7FEAFF", Paw="#1C3F8F",
               **CELESTIAL)),
        M("FrostrootWyrmling", "Frostroot Wyrmling", "Mythic", 0.10, 160000000, 40.0, 6.0, frostroot_wyrmling,
          dict(Scale="#2E5FB8", ScaleLight="#4C8FE6", Belly="#CFE6FF", Root="#8A5A3B", WingGlass="#8FDDFF",
               CrystalGlass="#7FEAFF", CrystalViolet="#B48CFF", Iris="#5FD8FF", FurWhite="#EEF5FF")),
    ]),
]

FAMILY_EGG_NAME = {"Mossbark": "Mossbark Egg", "Celestial": "Celestial Egg"}


# ---------------------------------------------------------------------------
# Pipeline: build, preview, export, data module
# ---------------------------------------------------------------------------
_materials = {}


def preview_material(key, hex_value, look):
    if key in _materials and _materials[key].name in bpy.data.materials:
        return _materials[key]
    mat = bpy.data.materials.new("BM_" + key)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    color = linear_rgba(hex_value)
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.55
    if look == "Neon":
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 3.0
    elif look == "Glass":
        bsdf.inputs["Roughness"].default_value = 0.12
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 0.6
        bsdf.inputs["Transmission Weight"].default_value = 0.55
    elif look == "Plastic":
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = stud_image()
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["A"].default_value = color
        links.new(tex.outputs["Alpha"], mix.inputs["Factor"])
        links.new(tex.outputs["Color"], mix.inputs["B"])
        links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    _materials[key] = mat
    return mat


def flat_material(key, hex_value, look):
    name = "BX_" + key
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = linear_rgba(hex_value)
        if look == "Neon":
            bsdf.inputs["Emission Color"].default_value = linear_rgba(hex_value)
            bsdf.inputs["Emission Strength"].default_value = 1.0
    return mat


def add_asset_socket(coll, asset, name, location):
    obj = add_socket(coll, name, location)
    obj.name = obj.data.name = "%s_Socket_%s" % (asset, name)
    return obj


def build_asset(spec):
    scene, coll = make_scene(spec["asset"])
    c = Ctx(spec)
    spec["builder"](c)
    objects = c.b.to_objects(coll, name_prefix=spec["asset"] + "_")
    parts = {}
    for role, obj in objects.items():
        if role not in c.colors:
            raise KeyError("%s: no colour for part role '%s'" % (spec["asset"], role))
        look = look_of(role)
        obj.data.materials.append(preview_material(spec["asset"] + "_" + role, c.colors[role], look))
        obj["Role"] = role
        parts[obj.name] = dict(Color=c.colors[role], Look=look)
    sockets = [add_asset_socket(coll, spec["asset"], name, pos * c.s) for name, pos in c.sockets.items()]
    volumes = {o.name: o.dimensions.x * o.dimensions.y * o.dimensions.z for o in objects.values() if look_of(o["Role"]) == "Plastic"}
    root = max(volumes, key=volumes.get) if volumes else next(iter(objects.values())).name
    tris = sum(tri_count(o) for o in objects.values())
    for o in objects.values():
        if tri_count(o) > MAX_TRIS_PER_PART:
            log("  !! %s has %d tris" % (o.name, tri_count(o)))
    log("Built %-20s %-9s %2d parts %6d tris" % (spec["asset"], spec["rarity"], len(objects), tris))
    return dict(spec=spec, scene=scene, coll=coll, objects=list(objects.values()), sockets=sockets, parts=parts, root=root,
                socket_names=list(c.sockets.keys()), tris=tris)


def world_bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
            hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
    return lo, hi


def make_stage(scene):
    purge_collection("Bestiary_Stage")
    stage = bpy.data.collections.new("Bestiary_Stage")
    scene.collection.children.link(stage)
    world = bpy.data.worlds.get("Bestiary_World") or bpy.data.worlds.new("Bestiary_World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = linear_rgba("#BFE3FF")
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9
    scene.world = world
    sun_data = bpy.data.lights.new("Bestiary_Sun", "SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(8)
    sun = bpy.data.objects.new("Bestiary_Sun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(-12), math.radians(-35))
    stage.objects.link(sun)
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=80)
    uv = bm.loops.layers.uv.active
    for face in bm.faces:
        for loop in face.loops:
            loop[uv].uv = (loop.vert.co.x, loop.vert.co.y)
    mesh = bpy.data.meshes.new("Bestiary_Ground")
    bm.to_mesh(mesh)
    bm.free()
    ground = bpy.data.objects.new("Bestiary_Ground", mesh)
    ground.data.materials.append(preview_material("Ground", "#5FC23A", "Plastic"))
    stage.objects.link(ground)
    cam = bpy.data.objects.new("Bestiary_Cam", bpy.data.cameras.new("Bestiary_Cam"))
    cam.data.lens = 50
    stage.objects.link(cam)
    scene.camera = cam
    return stage, cam, ground


def render_asset(scene, stage, cam, ground, built, path):
    for child in scene.collection.children:
        child.hide_render = not (child is built["coll"] or child is stage)
    lo, hi = world_bounds(built["objects"])
    centre = (lo + hi) / 2
    ground.location = (centre.x, centre.y, 0)
    size = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
    dist = size * 2.1 + 2.0
    az, el = math.radians(-35), math.radians(16)
    cam.location = centre + Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * dist
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.resolution_x = scene.render.resolution_y = PREVIEW_SIZE
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.cycles.samples = PREVIEW_SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.transparent_max_bounces = 64
    scene.cycles.transmission_bounces = 32
    scene.render.filepath = path
    scene.render.image_settings.file_format = "PNG"
    with bpy.context.temp_override(scene=scene):
        bpy.ops.render.render(write_still=True, scene=scene.name)


def contact_sheet(paths, out_name, columns=3):
    import numpy as np
    tiles = []
    for p in paths:
        img = bpy.data.images.load(p)
        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1]
        bpy.data.images.remove(img)
        tiles.append(px)
    if not tiles:
        return
    th, tw = tiles[0].shape[:2]
    rows = (len(tiles) + columns - 1) // columns
    sheet = np.ones((rows * th, columns * tw, 4), dtype=np.float32)
    for i, t in enumerate(tiles):
        r, col = divmod(i, columns)
        sheet[r * th:(r + 1) * th, col * tw:(col + 1) * tw] = t
    save_rgba(out_name, sheet)
    os.replace(os.path.join(TEXTURE_DIR, out_name + ".png"), os.path.join(PREVIEW_DIR, out_name + ".png"))


def export_family(scene, built_list, path):
    objs = []
    swapped = []
    for b in built_list:
        for o in b["objects"]:
            role = o["Role"]
            spec = b["spec"]
            colors = dict(DEFAULT_COLORS)
            colors.update(spec["colors"])
            swapped.append((o, o.data.materials[0]))
            o.data.materials[0] = flat_material(spec["asset"] + "_" + role, colors[role], look_of(role))
            objs.append(o)
        objs.extend(b["sockets"])
    view_layer = scene.view_layers[0]
    for o in view_layer.objects:
        o.select_set(False, view_layer=view_layer)
    for o in objs:
        o.select_set(True, view_layer=view_layer)
    view_layer.objects.active = objs[0]
    with bpy.context.temp_override(scene=scene, view_layer=view_layer, active_object=objs[0], selected_objects=objs):
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True,
                                  export_yup=True, export_materials="EXPORT", export_texcoords=True, export_normals=True)
    for o, mat in swapped:
        o.data.materials[0] = mat
    log("Exported %s (%d objects)" % (path, len(objs)))


def lua(value, indent=1):
    pad = "\t" * indent
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
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


def write_data_module(entries):
    body = lua(entries, 2)
    text = ("-- BestiaryData (ModuleScript) - GENERATED by blender/GenerateBestiary.py. Do not edit by hand:\n"
            "-- change the generator and re-run it. Location: ReplicatedStorage.BestiaryData\n"
            "-- Per asset: Kind, DisplayName, Family, Theme, Rarity, Idle, Root part, part colours/looks,\n"
            "-- socket names and the attributes CreatureKit writes onto the model (your game stats).\n"
            "return {\n\tAssets = " + body + ",\n}\n")
    path = os.path.join(OUTPUT_DIR, "BestiaryData.lua")
    with open(path, "w") as handle:
        handle.write(text)
    log("Wrote %s" % path)


def write_bestiary_textures():
    import numpy as np
    n = 256
    x, y = grid(n)
    r = np.sqrt(x * x + y * y)

    def pixel_art(rows):
        g = np.array([[1.0 if ch == "#" else (0.55 if ch == "+" else 0.0) for ch in row] for row in rows], dtype=np.float32)
        return np.kron(g, np.ones((n // g.shape[0], n // g.shape[1]), dtype=np.float32))

    save_rgba("Ember", white_alpha(pixel_art([
        "................",
        "................",
        "......+##+......",
        ".....+####+.....",
        "....+######+....",
        "....########....",
        "...+########+...",
        "...##########...",
        "...##########...",
        "...+########+...",
        "....########....",
        "....+######+....",
        ".....+####+.....",
        "......+##+......",
        "................",
        "................",
    ])))
    rng = np.random.default_rng(SEED)
    wisp = np.zeros_like(r)
    for _ in range(14):
        cx, cy = rng.uniform(-0.3, 0.3), rng.uniform(-0.5, 0.4)
        s = rng.uniform(0.12, 0.28)
        wisp += rng.uniform(0.4, 0.9) * np.exp(-(((x - cx) ** 2) / (s * s * 0.5) + ((y - cy) ** 2) / (s * s * 2.5)))
    wisp = np.clip(wisp / wisp.max() * 1.3, 0, 1) * np.clip(1.1 - r, 0, 1)
    save_rgba("VoidWisp", white_alpha(wisp))
    glint = np.maximum(np.exp(-(x / 0.04) ** 2) * np.clip(1 - np.abs(y), 0, 1) ** 2,
                       np.exp(-(y / 0.04) ** 2) * np.clip(1 - np.abs(x), 0, 1) ** 2) + np.exp(-(r / 0.12) ** 2)
    save_rgba("Glint", white_alpha(glint))
    log("Wrote Ember, VoidWisp, Glint")


def build_shards(scene):
    _, coll = make_scene("BestiaryVFX")
    rng = random.Random(SEED)
    objs = []
    for i in range(10):
        b = PartBuilder()
        size = rng.uniform(0.55, 0.9)
        for _ in range(rng.randint(2, 3)):
            off = Vector((rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25), rng.uniform(-0.15, 0.15))) * size
            b.box("Shard", off, (size * rng.uniform(0.5, 0.9), size * rng.uniform(0.5, 0.9), 0.24),
                  euler_deg(0, 0, rng.uniform(-20, 20)))
        made = b.to_objects(coll, name_prefix="EggShard%02d_" % (i + 1))
        for o in made.values():
            o.data.materials.append(flat_material("Shard", "#FFFFFF", "Plastic"))
            o.location = ((i % 5) * 1.3, -6 - (i // 5) * 1.3, 0.3)
            o["Role"] = "Shard"
            objs.append(o)
    return dict(objects=objs, sockets=[], spec=dict(asset="Shards", colors=dict(Shard="#FFFFFF")), coll=coll)


def selected(spec, family):
    return not ONLY or family in ONLY or spec["asset"] in ONLY


def main():
    log("Blender %s - building %s" % (bpy.app.version_string, SET_NAME))
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    write_stud_overlay()
    write_bestiary_textures()
    scene = work_scene()
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.view_settings.view_transform = "Standard"
    data = {}
    manifest = {}
    families_done = []
    for fam in FAMILIES:
        specs = ([fam["egg"]] if fam["egg"] else []) + fam["monsters"]
        specs = [s for s in specs if selected(s, fam["family"])]
        if not specs:
            continue
        built = [build_asset(s) for s in specs]
        # Lay the family out in a row (one row per family) so one GLB holds it
        # all without overlaps, and the .blend shows every family side by side.
        x = 0.0
        row_y = -22.0 * len(families_done)
        for b in built:
            lo, hi = world_bounds(b["objects"])
            shift = x - lo.x
            for o in b["objects"] + b["sockets"]:
                o.location.x += shift
                o.location.y += row_y
            x += (hi.x - lo.x) + 3.0
        families_done.append((fam, built))
        for b in built:
            spec = b["spec"]
            attrs = dict(spec["attributes"])
            attrs["Family"] = fam["family"]
            attrs["Theme"] = fam["theme"]
            if spec["kind"] == "Monster":
                attrs["SourceEgg"] = fam["egg"]["display"] if fam["egg"] else FAMILY_EGG_NAME.get(fam["family"], "")
            data[spec["asset"]] = dict(Kind=spec["kind"], DisplayName=spec["display"], Family=fam["family"],
                                       Theme=fam["theme"], Rarity=spec["rarity"], Idle=spec["idle"], Root=b["root"],
                                       Parts=b["parts"], Sockets=b["socket_names"], Attributes=attrs)
            manifest[spec["asset"]] = dict(tris=b["tris"], parts=len(b["parts"]), family=fam["family"])
    stage, cam, ground = make_stage(scene)
    if RENDER_PREVIEWS:
        for fam, built in families_done:
            paths = []
            for b in built:
                path = os.path.join(PREVIEW_DIR, b["spec"]["asset"] + ".png")
                render_asset(scene, stage, cam, ground, b, path)
                paths.append(path)
            contact_sheet(paths, "Family_" + fam["family"])
            log("Rendered %s previews" % fam["family"])
    for child in scene.collection.children:
        set_collection_visible(scene, child, child is not stage)
    for fam, built in families_done:
        export_family(scene, built, os.path.join(OUTPUT_DIR, "Family_%s.glb" % fam["family"]))
    shards = build_shards(scene)
    export_family(scene, [shards], os.path.join(OUTPUT_DIR, "BestiaryVFXMeshes.glb"))
    if data:
        write_data_module(data)
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
