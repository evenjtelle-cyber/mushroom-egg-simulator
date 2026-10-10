"""
GenerateFrostmaneSet.py  -  Blender 4.x
"+1 Chop Mushrooms for Eggs": end-game Celestial set, blocky stud style

Builds three things, each in its own scene and collection:

  FrostmaneWyrm   Secret Celestial dragon (~19 studs tall, ~33 long). Its
                  mammoth traits are layered shaggy fur slabs in white/ice/blue/navy
                  stripes, curling segmented tusks, white fur leg cuffs, crystal
                  toes and spine spikes, and glowing cyan eyes. The dragon parts
                  are horns, translucent ice-crystal wings and a long tail ending
                  in a crystal cluster.
  FrostmaneEgg    Stacked-slab egg with a frosted fur cap, glowing crack seams
                  and a crystal crown. Two tusks curl around it out of a blocky ice nest.
  FrostmaneVFX    Particle textures (white RGB, shape in alpha), a Cycles-rendered
                  4x4 frost-breath flipbook, a trail strip, the stud overlay
                  texture, and VFX meshes (ice nova ring, crystal burst, hatch
                  shell shards).

Style: blocky stud style. Everything is built from boxes, with silhouettes from
stacked cross-slab layers. Studs come from one tiling overlay texture
(StudOverlay.png, one tile = one stud). UVs are box-projected per slab, so the
studs line up with every slab like on Roblox bricks. Each colour is its own mesh
part. In Studio, set MeshPart.Color from the palette and add a SurfaceAppearance
(AlphaMode = Overlay, ColorMap = StudOverlay). FrostmaneVFX.lua does this
automatically.

Exports (in ~/Documents/FrostmaneSet/):
  FrostmaneWyrm.glb, FrostmaneEgg.glb, FrostmaneVFXMeshes.glb
  Textures/*.png, Previews/*.png, FrostmaneSet.blend, FrostmaneSet_Manifest.json

Small "Socket_*" meshes mark VFX anchor points (mouth, wing tips, feet...).
FrostmaneVFX.lua turns them into Attachments and hides them.

Run: paste into Blender's Text Editor and press Alt+P, or headless:
    blender --background --python GenerateFrostmaneSet.py
Facing: heads point toward Blender -Y. If a model imports facing backwards in
Studio, rotate its pivot 180 degrees (or set FACE_POSITIVE_Y = True and re-run).
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
SET_NAME = "FrostmaneSet"
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", SET_NAME)
TEXTURE_DIR = os.path.join(OUTPUT_DIR, "Textures")
PREVIEW_DIR = os.path.join(OUTPUT_DIR, "Previews")
LOG_NAME = SET_NAME + "_Log"

BUILD_MONSTER = True
BUILD_EGG = True
BUILD_VFX = True
RENDER_PREVIEWS = True
PREVIEW_SAMPLES = 48
FACE_POSITIVE_Y = False  # rotate exports 180 degrees if Studio shows them backwards
SEED = 7

MAX_TRIS_PER_PART = 20000
STUD_TILE_PX = 128
STUDS_PER_UNIT = 2.0  # stud tiles per Blender unit: 2 = half-size studs, closer to the reference monsters

# sRGB hex palette. Mirrored in src/ReplicatedStorage/FrostmaneVFX.lua (PALETTE).
PALETTE = {
    "Body": "#23489E",        # sapphire hide
    "Belly": "#CFE6FF",       # pale icy belly scutes
    "FurWhite": "#EEF5FF",
    "FurIce": "#A9D3FF",
    "FurBlue": "#4C8FE6",
    "FurNavy": "#1C3F8F",
    "Tusks": "#BDE3FF",       # segmented ice-ivory tusks and horns
    "Claws": "#F4F8FF",
    "WingFrame": "#163577",
    "WingMembrane": "#6FCBFF",  # translucent ice (Glass in Studio)
    "Crystals": "#7FEAFF",    # glowing crystals (Glass + Highlight in Studio)
    "CrystalsViolet": "#B48CFF",
    "Eyes": "#9CFFFF",        # Neon in Studio
    "Mouth": "#0E1630",
    # Egg / nest
    "Shell": "#23489E",
    "ShellBlue": "#4C8FE6",
    "Frost": "#EEF5FF",
    "FrostIce": "#A9D3FF",
    "Cracks": "#5FF4FF",
    "Crown": "#7FEAFF",
    "CrownViolet": "#B48CFF",
    "Nest": "#6F8FB8",
    "NestLight": "#9DB8D8",
    "NestSnow": "#EEF5FF",
    "NestCrystals": "#7FEAFF",
    "NestViolet": "#B48CFF",
    "NestTusks": "#BDE3FF",
}

# Parts that render as glowing translucent ice / neon rather than studded plastic.
GLOW_PARTS = {"Crystals", "CrystalsViolet", "WingMembrane", "Eyes", "Cracks", "Crown", "CrownViolet", "NestCrystals", "NestViolet"}
NO_STUD_PARTS = GLOW_PARTS | {"Mouth"}

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
def purge_scene(name):
    scene = bpy.data.scenes.get(name)
    if scene is not None:
        for obj in list(scene.collection.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for child in list(scene.collection.children_recursive):
            bpy.data.collections.remove(child)
        if len(bpy.data.scenes) > 1:
            bpy.data.scenes.remove(scene)
    for coll in list(bpy.data.collections):
        if coll.name.startswith(name) and coll.users == 0:
            bpy.data.collections.remove(coll)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def purge_collection(name):
    coll = bpy.data.collections.get(name)
    if coll is not None:
        for obj in list(coll.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(coll)


def make_scene(name):
    """Own scene + collection per asset (brief 6.1). Headless (--background)
    runs build every asset as a collection in the window's scene instead:
    there, Blender 4.2's glTF exporter crashes once it has switched the stub
    window between scenes. Other assets' collections are hidden from renders."""
    if bpy.app.background:
        scene = bpy.context.scene
        purge_collection(name + "_Parts")
        coll = bpy.data.collections.new(name + "_Parts")
        scene.collection.children.link(coll)
        for child in scene.collection.children:
            child.hide_render = child is not coll
    else:
        purge_scene(name)
        scene = bpy.data.scenes.new(name)
        coll = bpy.data.collections.new(name + "_Parts")
        scene.collection.children.link(coll)
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
    world = bpy.data.worlds.new(scene.name + "_World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = linear_rgba("#BFE3FF")
    bg.inputs["Strength"].default_value = 0.9
    scene.world = world

    sun_data = bpy.data.lights.new(scene.name + "_Sun", "SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(8)
    sun = bpy.data.objects.new(scene.name + "_Sun", sun_data)
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
        mesh = bpy.data.meshes.new(scene.name + "_Ground")
        bm.to_mesh(mesh)
        bm.free()
        ground_obj = bpy.data.objects.new(scene.name + "_Ground", mesh)
        PALETTE.setdefault("PreviewGrass", "#5FC23A")
        ground_obj.data.materials.append(material_for("PreviewGrass"))
        coll.objects.link(ground_obj)

    cam_data = bpy.data.cameras.new(scene.name + "_Cam")
    cam_data.lens = lens
    cam = bpy.data.objects.new(scene.name + "_Cam", cam_data)
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
# 1. Frostmane Wyrm
# ---------------------------------------------------------------------------
BODY_C = Vector((0.0, 0.0, 9.6))
BODY_R = Vector((3.7, 7.0, 3.6))  # half-width, half-length, half-height


def body_point(theta, t, inflate=0.0):
    """Surface point/normal on the torso. theta: 0 = spine, +-pi/2 = flanks,
    t: -1 chest .. +1 rump. Includes a mammoth shoulder hump."""
    hump = 1.0 + 0.16 * math.exp(-((t + 0.35) / 0.35) ** 2) * max(0.0, math.cos(theta))
    k = math.sqrt(max(0.0, 1.0 - (t * 0.96) ** 2))
    rx, rz = (BODY_R.x + inflate) * k, (BODY_R.z + inflate) * k * hump
    p = BODY_C + Vector((math.sin(theta) * rx, t * (BODY_R.y + inflate), math.cos(theta) * rz))
    n = Vector((math.sin(theta) / max(rx, 0.1), t / (BODY_R.y + inflate) * 0.6, math.cos(theta) / max(rz, 0.1))).normalized()
    return p, n


def build_wyrm(coll):
    rng = random.Random(SEED)
    b = PartBuilder()
    forward = Vector((0, -1, 0))

    # --- Torso core (stacked cross slabs) with a shoulder hump ---------------
    b.blob("Body", BODY_C, BODY_R, step=1.0,
           profile=lambda t: math.sqrt(max(0.0, 1.0 - (t * 0.96) ** 2)))
    b.blob("Body", BODY_C + Vector((0, -2.6, 2.6)), (2.8, 3.0, 1.8), step=0.9)  # hump mass

    # Belly scutes: pale slabs in rows under the torso.
    for i in range(9):
        t = -0.75 + i * 0.19
        p, n = body_point(math.pi, t, inflate=0.05)
        k = math.sqrt(max(0.0, 1 - t * t))
        b.box("Belly", p + Vector((0, 0, 0.2)), (4.4 * k + 1.0, 1.35, 0.5))

    # --- Shaggy coat over the torso -------------------------------------------
    rows = 15
    for r in range(rows):
        t = -0.92 + r * (1.84 / (rows - 1))
        ring_count = 18
        for j in range(ring_count):
            theta = -2.05 + j * (4.1 / (ring_count - 1)) + rng.uniform(-0.06, 0.06)
            p, n = body_point(theta, t + rng.uniform(-0.03, 0.03), inflate=0.1)
            down = Vector((0, 0.45, -1.0))  # hang down and slightly back
            if abs(theta) < 0.35:
                down = Vector((math.copysign(0.7, theta if theta != 0 else 1), 0.9, -0.2))
            flank = abs(theta) > 1.35
            length = rng.uniform(2.2, 3.2) * (1.45 if flank else 1.0)
            width = rng.uniform(1.25, 1.95)
            part = fur_colour(p, rng, white_bias=0.35 * math.cos(theta) - (0.25 if flank else 0.0))
            fur_plate(b, p, n, down, rng, width, length, part)

    # Long hanging skirt along the lower flanks (the mammoth's fringe).
    for side in (-1, 1):
        for i in range(13):
            t = -0.8 + i * 0.13
            p, n = body_point(side * 1.95, t, inflate=0.2)
            length = rng.uniform(3.4, 4.6)
            part = fur_colour(p, rng, white_bias=-0.2)
            fur_plate(b, p, Vector((side, 0, -0.15)), Vector((0, 0.15, -1)), rng, rng.uniform(1.3, 1.8), length, part, lift=(2, 8))

    # White chest bib hanging under the neck.
    for i in range(10):
        a = -1.1 + i * 0.24
        p = BODY_C + Vector((math.sin(a) * 2.6, -BODY_R.y * 0.86, 1.2 + math.cos(a) * 0.8))
        fur_plate(b, p, Vector((math.sin(a), -1, 0.1)), Vector((0, -0.2, -1)), rng, 1.5, rng.uniform(3.0, 4.2),
                  "FurWhite" if rng.random() < 0.75 else "FurIce", lift=(4, 12))

    # --- Spine crystals ------------------------------------------------------
    for i in range(9):
        t = -0.82 + i * 0.2
        p, n = body_point(0.0, t, inflate=0.3)
        size = 1.25 - abs(t + 0.3) * 0.45
        up = (n + Vector((0, 0.45, 0))).normalized()
        crystal_cluster(b, p, up, rng, size=size, count=3 if i % 2 == 0 else 2, violet_chance=0.25)

    # --- Neck -----------------------------------------------------------------
    neck_pts = bezier(BODY_C + Vector((0, -5.6, 1.6)), BODY_C + Vector((0, -8.6, 3.4)),
                      BODY_C + Vector((0, -10.2, 6.0)), Vector((0, -12.2, 17.0)), 7)
    for i in range(len(neck_pts) - 1):
        a, c = neck_pts[i], neck_pts[i + 1]
        d = c - a
        r = lerp(2.5, 1.75, i / (len(neck_pts) - 2))
        b.blob("Body", (a + c) / 2, (r, d.length * 0.62, r * 0.95), step=0.6, rot=basis_from_y(d, (0, 0, 1)))
        # Mane: white/ice plates down the top and sides of the neck.
        for side in (-1, 0, 1):
            base = (a + c) / 2 + Vector((side * r * 0.8, 0, r * (0.95 if side == 0 else 0.55)))
            normal = Vector((side * 0.9, 0, 1.0))
            fur_plate(b, base, normal, Vector((side * 0.6, 0.8, -0.8)), rng, rng.uniform(1.3, 1.8), rng.uniform(2.2, 3.0),
                      "FurWhite" if rng.random() < 0.6 else "FurIce")
        if i % 2 == 0:
            crystal_cluster(b, (a + c) / 2 + Vector((0, 0.3, r + 0.2)), Vector((0, 0.6, 1)), rng, size=0.75, count=2)

    # --- Head ------------------------------------------------------------------
    head = Vector((0.0, -13.3, 17.8))

    def hb(part, off, size, rot_deg=(0, 0, 0), taper=(1.0, 1.0)):
        # off = (x, forward, up) relative to the head; forward is -Y.
        b.box(part, head + Vector((off[0], -off[1], off[2])), size, euler_deg(*rot_deg), taper)

    hb("Body", (0, 0, 0.3), (3.4, 3.4, 2.8))
    hb("Body", (0, 0.6, 1.3), (2.9, 2.6, 1.2))
    hb("FurWhite", (0, 1.25, 1.75), (3.7, 1.4, 0.7), (-12, 0, 0))  # frosted brow
    hb("Body", (0, 3.3, -0.15), (2.5, 4.0, 1.7))  # long snout
    hb("FurIce", (0, 3.4, 0.8), (1.8, 3.8, 0.45))  # snout ridge
    for i in range(3):
        hb("FurWhite", (0, 2.2 + i * 1.2, 1.15), (0.5, 0.8, 0.6), (-20, 0, 0), (0.5, 0.4))  # ridge spikes
    hb("Body", (0, 5.35, -0.05), (2.2, 0.8, 1.45))  # nose
    for x in (-0.55, 0.55):
        hb("Mouth", (x, 5.77, 0.3), (0.38, 0.12, 0.28))  # nostrils
    hb("Mouth", (0, 3.1, -1.2), (2.1, 3.6, 0.35))  # mouth interior
    hb("Body", (0, 2.9, -1.8), (2.3, 3.9, 0.8), (9, 0, 0))  # jaw, slightly open
    for side in (-1, 1):
        for i in range(5):
            hb("Claws", (side * 1.0, 1.6 + i * 0.85, -1.12), (0.28, 0.32, 0.5), (0, 0, 0), (0.5, 0.4))  # fangs
        hb("Mouth", (side * 1.71, 1.05, 0.72), (0.1, 1.0, 0.72))  # eye socket
        hb("Eyes", (side * 1.75, 1.05, 0.72), (0.12, 0.72, 0.42))  # glowing eye
        hb("Eyes", (side * 1.77, 1.25, 0.82), (0.1, 0.22, 0.16))  # eye glint
        # Cheek frills fanning back (the mammoth's big ear, made spiky).
        for k in range(3):
            frill_rot = euler_deg(0, side * (18 + k * 16), side * (-28 - k * 10))
            b.box("FurBlue" if k == 1 else "FurNavy", head + Vector((side * (1.9 + k * 0.25), 1.0 + k * 0.5, 0.2 + k * 0.45)),
                  (0.35, 2.6 - k * 0.3, 1.5 - k * 0.2), frill_rot, taper=(0.6, 0.45))
        # Horns: segmented, sweeping back and up, crystal tips.
        horn = bezier(head + Vector((side * 1.0, 0.9, 1.6)), head + Vector((side * 1.5, 2.6, 3.0)),
                      head + Vector((side * 1.9, 4.6, 3.6)), head + Vector((side * 2.3, 6.0, 4.7)), 7)
        b.chain("Tusks", horn, [0.95 - 0.08 * i for i in range(7)], roll_hint=(side, 0, 0), taper_last=(0.55, 0.55))
        b.crystal("Crystals", horn[-1], horn[-1] - horn[-2], 1.4, 0.3)
        # Mammoth tusks: curl down, forward and up from the jaw sides.
        tusk = bezier(head + Vector((side * 1.2, -2.2, -1.2)), head + Vector((side * 1.9, -3.4, -4.4)),
                      head + Vector((side * 2.1, -7.0, -4.2)), head + Vector((side * 1.2, -7.6, -1.6)), 10)
        b.chain("Tusks", tusk, [0.95 - 0.06 * i for i in range(10)], roll_hint=(side, 0, 0), taper_last=(0.5, 0.5))
        b.box("FurWhite", head + Vector((side * 1.25, -2.2, -1.25)), (0.9, 0.9, 1.2))  # tusk root sheath
    # Head mane and crest crystals.
    for i in range(7):
        a = -1.2 + i * 0.4
        base = head + Vector((math.sin(a) * 1.6, 0.4 + abs(a) * 0.2, 1.7 + math.cos(a) * 0.4))
        fur_plate(b, base, Vector((math.sin(a), 0.2, 1.0)), Vector((math.sin(a) * 0.7, 1.0, -0.4)), rng, 1.3, 2.6,
                  "FurWhite" if i % 3 else "FurIce")
    for i, (y, s) in enumerate(((0.2, 0.8), (1.1, 0.65), (2.0, 0.5))):
        crystal_cluster(b, head + Vector((0, y, 2.05 - i * 0.1)), Vector((0, 0.5, 1)), rng, size=s, count=2, violet_chance=0.0)

    # --- Legs -------------------------------------------------------------------
    legs = {"FL": (-2.7, -3.9), "FR": (2.7, -3.9), "BL": (-2.7, 4.3), "BR": (2.7, 4.3)}
    feet = {}
    for key, (x, y) in legs.items():
        side = 1 if x > 0 else -1
        hip = Vector((x, y, 8.4))
        knee = Vector((x * 1.05, y - 0.2, 4.6))
        b.blob("Body", (hip + knee) / 2, (1.75, (hip - knee).length * 0.6, 1.75), step=0.55,
               rot=basis_from_y(hip - knee, (0, 1, 0)))
        b.blob("FurNavy", Vector((x * 1.05, y - 0.2, 2.6)), (1.35, 1.9, 1.35), step=0.5,
               rot=basis_from_y((0, 0, 1), (0, 1, 0)))
        # Fur cuff around the knee, plus a short white cuff above the foot.
        for k in range(14):
            a = 2 * math.pi * k / 14 + rng.uniform(-0.1, 0.1)
            radial = Vector((math.cos(a), math.sin(a), 0))
            fur_plate(b, knee + radial * 1.55 + Vector((0, 0, 1.0)), radial, Vector((0, 0, -1)), rng,
                      1.0, rng.uniform(2.0, 2.6), "FurWhite" if rng.random() < 0.7 else "FurIce", lift=(4, 14))
            if k % 2 == 0:
                fur_plate(b, Vector((x * 1.05, y - 0.2, 1.75)) + radial * 1.3, radial, Vector((0, 0, -1)), rng,
                          1.1, 1.2, "FurWhite", lift=(10, 20))
        foot = Vector((x * 1.05, y - 0.55, 0.6))
        feet[key] = foot
        b.box("FurNavy", foot, (2.9, 3.2, 1.2))
        b.box("Body", foot + Vector((0, -0.2, 0.75)), (2.4, 2.5, 0.5))
        for c in (-0.85, 0.0, 0.85):
            b.box("Claws", foot + Vector((c, -1.75, -0.15)), (0.62, 1.1, 0.75), euler_deg(-18, 0, 0), taper=(0.45, 0.35))
        crystal_cluster(b, foot + Vector((side * 0.9, 1.0, 0.4)), Vector((side * 0.7, 0.6, 0.5)), rng, size=0.45, count=2)

    # --- Wings ------------------------------------------------------------------
    wing_tips = {}
    for side in (-1, 1):
        root = Vector((side * 2.9, -2.4, 12.6))
        elbow = root + Vector((side * 4.2, 1.2, 4.0))
        wrist = elbow + Vector((side * 3.2, 2.8, 1.6))
        tips = [wrist + Vector((side * 3.2, 0.8, 4.2)),
                wrist + Vector((side * 5.4, 4.0, 0.6)),
                wrist + Vector((side * 3.6, 7.2, -3.0))]
        trailing_root = root + Vector((side * 1.6, 7.0, -0.4))
        wing_tips[side] = tips[1]
        for a, c, s0, s1 in ((root, elbow, 1.1, 0.9), (elbow, wrist, 0.9, 0.7)):
            b.chain("WingFrame", [a, (a + c) / 2, c], [s0, s1], roll_hint=(0, 0, 1))
        b.blob("WingFrame", elbow, (0.75, 0.75, 0.75), step=0.5)
        for t in tips:
            b.chain("WingFrame", [wrist, lerp(wrist, t, 0.5), t], [0.6, 0.42], roll_hint=(0, 0, 1), taper_last=(0.5, 0.5))
            b.crystal("Crystals", t, t - wrist, 1.5, 0.28)
        crystal_cluster(b, wrist + Vector((0, 0, 0.4)), Vector((side * 0.4, -0.3, 1)), rng, size=0.6, count=3, violet_chance=0.4)
        # Shoulder fur over the wing root.
        for k in range(5):
            fur_plate(b, root + Vector((side * 0.3 * k, -0.6 + 0.5 * k, 0.9)), Vector((side * 0.5, 0, 1)),
                      Vector((side, 0.4, -0.6)), rng, 1.4, 2.4, "FurWhite" if k % 2 else "FurIce")
        # Membrane: overlapping ice tiles filled between spars.
        edges = [(root, wrist, wrist, tips[0])]
        edges += [(wrist, tips[i], wrist, tips[i + 1]) for i in range(2)]
        edges += [(wrist, tips[2], root + Vector((side * 1.2, 1.6, 0.2)), trailing_root)]
        edges.insert(0, (root, elbow, root, wrist))
        for a0, a1, b0, b1 in edges:
            nu, nv = 6, 5
            for iu in range(nu):
                for iv in range(nv):
                    u, v = (iu + 0.5) / nu, (iv + 0.5) / nv
                    pa, pb = lerp(a0, a1, u), lerp(b0, b1, u)
                    p = lerp(pa, pb, v)
                    du = lerp(a1 - a0, b1 - b0, v)
                    dv = pb - pa
                    if dv.length < 0.7 or du.length < 0.25:
                        continue  # fan apex: tiles would pile up on each other
                    normal = du.cross(dv).normalized()
                    rot = basis_from_y(du, normal)
                    w = dv.length / nv * 1.35 + 0.2
                    l = du.length / nu * 1.35 + 0.2
                    p += normal * rng.uniform(-0.08, 0.08)
                    rot = rot @ Matrix.Rotation(math.radians(rng.uniform(-6, 6)), 3, "Z")
                    b.box("WingMembrane", p, (w, l, 0.16), rot)

    # --- Tail -------------------------------------------------------------------
    tail = bezier(BODY_C + Vector((0, 6.2, -0.6)), Vector((0, 13.0, 7.0)), Vector((2.6, 17.5, 3.6)), Vector((6.0, 19.0, 4.6)), 12)
    for i in range(len(tail) - 1):
        a, c = tail[i], tail[i + 1]
        d = c - a
        r = lerp(2.2, 0.55, i / (len(tail) - 2))
        b.blob("Body", (a + c) / 2, (r, d.length * 0.62, r * 0.9), step=0.55, rot=basis_from_y(d, (0, 0, 1)))
        if i < len(tail) - 3:
            mid = (a + c) / 2
            for side in (-1, 1):
                fur_plate(b, mid + Vector((side * r * 0.7, 0, r * 0.6)), Vector((side, 0, 0.8)), d + Vector((side * 0.4, 0, -0.5)),
                          rng, 0.9 + r * 0.4, 1.4 + r * 0.6, fur_colour(mid, rng))
            crystal_cluster(b, mid + Vector((0, 0, r * 0.9)), Vector((0, 0.5, 1)), rng, size=0.35 + r * 0.25, count=2)
    tail_tip = tail[-1]
    tip_dir = (tail[-1] - tail[-2]).normalized()
    crystal_cluster(b, tail_tip, tip_dir + Vector((0, 0, 0.4)), rng, size=1.3, count=6, violet_chance=0.5)

    objects = b.to_objects(coll)
    assign_materials(objects)

    sockets = [
        add_socket(coll, "Mouth", head + Vector((0, -4.8, -0.9))),
        add_socket(coll, "Head", head + Vector((0, 0, 2.2))),
        add_socket(coll, "Chest", BODY_C + Vector((0, -5.0, 0.0))),
        add_socket(coll, "Spine", BODY_C + Vector((0, 0.5, 4.2))),
        add_socket(coll, "TailTip", tail_tip + tip_dir * 1.2),
        add_socket(coll, "WingTipL", wing_tips[-1]),
        add_socket(coll, "WingTipR", wing_tips[1]),
    ]
    for key, foot in feet.items():
        sockets.append(add_socket(coll, "Foot" + key, foot - Vector((0, 0, 0.6))))
    return objects, sockets


# ---------------------------------------------------------------------------
# 2. Frostmane Egg
# ---------------------------------------------------------------------------
EGG_BASE_Z = 1.55
EGG_HEIGHT = 5.1
EGG_RADIUS = 2.05


def egg_radius(t):
    """t: 0 bottom .. 1 top. Classic egg: fuller below the middle."""
    s = 2 * t - 1
    return EGG_RADIUS * math.sqrt(max(0.0, 1 - s * s)) * (1 - 0.16 * s)


def build_egg(coll):
    rng = random.Random(SEED + 11)
    shell = PartBuilder()  # the part that spins and bobs
    nest = PartBuilder()  # static base

    # Shell: horizontal layers of cross slabs, alternating hues.
    layers = 13
    for i in range(layers):
        t = (i + 0.5) / layers
        r = egg_radius(t)
        z = EGG_BASE_Z + t * EGG_HEIGHT
        part = "ShellBlue" if (noise.noise(Vector((0, 0, i * 0.7))) + (i % 3 == 1) * 0.6) > 0.25 else "Shell"
        thickness = EGG_HEIGHT / layers * 1.04
        for w, d, depth in ((2.0, 1.25, 1.0), (1.25, 2.0, 0.86), (1.68, 1.68, 0.74)):
            shell.box(part, (0, 0, z), (r * w, r * d, thickness * depth))

    # Frosted fur cap draping from the crown.
    for ring_i, t in enumerate((0.93, 0.82, 0.7)):
        count = 9 + ring_i * 3
        for k in range(count):
            a = 2 * math.pi * (k + 0.5 * ring_i) / count
            r = egg_radius(t)
            z = EGG_BASE_Z + t * EGG_HEIGHT
            radial = Vector((math.cos(a), math.sin(a), 0))
            normal = (radial + Vector((0, 0, 0.9 - ring_i * 0.3))).normalized()
            part = "Frost" if rng.random() < 0.7 else "FrostIce"
            fur_plate(shell, radial * r * 0.92 + Vector((0, 0, z)), normal, Vector((0, 0, -1)), rng,
                      rng.uniform(0.75, 1.05), rng.uniform(1.0, 1.6) + ring_i * 0.25, part, thickness=0.22, lift=(4, 12), spin=8)

    # Glowing crack seams: zig-zag chains of thin slabs on the lower shell.
    for crack in range(3):
        a = crack * 2 * math.pi / 3 + 0.4
        t = 0.66
        points = []
        while t > 0.12:
            r = egg_radius(t) + 0.06
            points.append(Vector((math.cos(a) * r, math.sin(a) * r, EGG_BASE_Z + t * EGG_HEIGHT)))
            a += rng.choice((-1, 1)) * rng.uniform(0.18, 0.32)
            t -= rng.uniform(0.08, 0.12)
        for i in range(len(points) - 1):
            d = points[i + 1] - points[i]
            outward = Vector((points[i].x, points[i].y, 0)).normalized()
            shell.box("Cracks", (points[i] + points[i + 1]) / 2, (0.3, d.length * 1.1, 0.2), basis_from_y(d, outward))
            if rng.random() < 0.4:  # branching hairline
                branch = Matrix.Rotation(rng.choice((-0.9, 0.9)), 3, outward) @ d * 0.5
                shell.box("Cracks", points[i] + branch / 2, (0.14, branch.length, 0.12), basis_from_y(branch, outward))

    # Crystal crown.
    top = Vector((0, 0, EGG_BASE_Z + EGG_HEIGHT - 0.1))
    crystal_cluster(shell, top, Vector((0, 0, 1)), rng, size=1.2, count=6, violet_chance=0.45, part="Crown", violet_part="CrownViolet")

    # Nest: chunky ice-rock ring with snow on top and crystals jutting out.
    nest.blob("Nest", (0, 0, 0.35), (2.9, 2.9, 0.35), step=0.7, rot=basis_from_y((0, 0, 1), (0, 1, 0)))
    for k in range(16):
        a = 2 * math.pi * k / 16 + rng.uniform(-0.08, 0.08)
        radial = Vector((math.cos(a), math.sin(a), 0))
        h = rng.uniform(1.1, 1.9)
        part = "NestLight" if rng.random() < 0.4 else "Nest"
        rot = basis_from_y(radial.cross(Vector((0, 0, 1))), Vector((0, 0, 1))) @ euler_deg(rng.uniform(-8, 8), 0, 0)
        nest.box(part, radial * 2.75 + Vector((0, 0, h / 2)), (1.2, 1.35, h), rot)
        nest.box("NestSnow", radial * 2.75 + Vector((0, 0, h + 0.12)), (1.25, 1.4, 0.3), rot)
        if k % 4 == 1:
            crystal_cluster(nest, radial * 3.1 + Vector((0, 0, 0.6)), radial + Vector((0, 0, 0.9)), rng, size=0.55, count=2,
                            violet_chance=0.3, part="NestCrystals", violet_part="NestViolet")
    # Two tusks spiralling up around the egg.
    for start in (0.0, math.pi):
        pts = []
        for i in range(12):
            s = i / 11
            a = start + s * 2.3
            r = 2.65 - 0.25 * s + 0.35 * math.sin(s * math.pi)
            pts.append(Vector((math.cos(a) * r, math.sin(a) * r, 0.9 + s * 4.6 - 1.1 * s * s)))
        pts[-1] = pts[-1] + (Vector((0, 0, 4.5)) - pts[-1]) * 0.18  # tips curl inward
        nest.chain("NestTusks", pts, [0.62 - 0.03 * i for i in range(12)], roll_hint=(0, 0, 1), taper_last=(0.5, 0.5))

    shell_objects = shell.to_objects(coll)
    nest_objects = nest.to_objects(coll)  # part names never overlap the shell's
    objects = dict(shell_objects)
    objects.update(nest_objects)
    assign_materials(objects)
    for part, obj in objects.items():
        obj["EggGroup"] = "Shell" if part in shell_objects else "Nest"

    sockets = [
        add_socket(coll, "EggCenter", (0, 0, EGG_BASE_Z + EGG_HEIGHT * 0.45)),
        add_socket(coll, "Crown", top + Vector((0, 0, 1.6))),
        add_socket(coll, "NestRim", (0, 0, 1.6)),
    ]
    return objects, sockets


# ---------------------------------------------------------------------------
# 3. VFX: textures (numpy), flipbook (Cycles), meshes
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


def write_particle_textures():
    import numpy as np
    rng = np.random.default_rng(SEED)
    n = 256
    x, y = grid(n)
    r = np.sqrt(x * x + y * y)
    out = {}

    out["SoftGlow"] = save_rgba("SoftGlow", white_alpha(np.exp(-(r / 0.45) ** 2)))
    out["FrostMote"] = save_rgba("FrostMote", white_alpha(np.exp(-(r / 0.12) ** 2) + 0.55 * np.exp(-(r / 0.4) ** 2)))

    streak = lambda a, b: np.exp(-(a / 0.035) ** 2) * np.clip(1 - np.abs(b), 0, 1) ** 2.2
    glint = np.maximum(streak(x, y), streak(y, x)) + np.exp(-(r / 0.13) ** 2)
    out["Sparkle"] = save_rgba("Sparkle", white_alpha(glint))

    # Blocky pixel sparkle and snowflake to match the stud style (drawn on a
    # coarse grid, then upscaled with hard edges).
    def pixel_art(rows):
        g = np.array([[1.0 if ch == "#" else (0.55 if ch == "+" else 0.0) for ch in row] for row in rows], dtype=np.float32)
        scale = n // g.shape[0]
        return np.kron(g, np.ones((scale, scale), dtype=np.float32))

    out["BlockSparkle"] = save_rgba("BlockSparkle", white_alpha(pixel_art([
        "................",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        "......+##+......",
        "......+##+......",
        ".##+++####+++##.",
        ".##############.",
        ".##############.",
        ".##+++####+++##.",
        "......+##+......",
        "......+##+......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        "................",
    ])))
    out["BlockSnowflake"] = save_rgba("BlockSnowflake", white_alpha(pixel_art([
        "................",
        ".......##.......",
        "..#...+##+...#..",
        "...#...##...#...",
        "....#..##..#....",
        ".+...#.##.#...+.",
        "..+...####...+..",
        ".##############.",
        ".##############.",
        "..+...####...+..",
        ".+...#.##.#...+.",
        "....#..##..#....",
        "...#...##...#...",
        "..#...+##+...#..",
        ".......##.......",
        "................",
    ])))

    shard = np.clip(1 - (np.abs(x) / 0.32 + np.abs(y) / 0.95), 0, 1) ** 0.6
    out["IceShard"] = save_rgba("IceShard", white_alpha(shard))

    ring = np.exp(-((r - 0.82) / 0.05) ** 2) + 0.25 * np.exp(-((r - 0.7) / 0.12) ** 2)
    out["ShockwaveRing"] = save_rgba("ShockwaveRing", white_alpha(ring))

    # Mist puff: sum of soft blobs, clipped to a round falloff.
    mist = np.zeros_like(r)
    for _ in range(26):
        cx, cy = rng.uniform(-0.45, 0.45, 2)
        s = rng.uniform(0.14, 0.32)
        mist += rng.uniform(0.3, 0.7) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (s * s)))
    mist = np.clip(mist / mist.max() * 1.3, 0, 1) * np.clip(1.15 - r, 0, 1) ** 1.5
    out["FrostMist"] = save_rgba("FrostMist", white_alpha(mist))

    # Mushroom chunk debris, used by AnimationController's impact burst.
    chunk = ((np.abs(x) < 0.55) & (np.abs(y) < 0.42)).astype(np.float32)
    chunk[(np.abs(x) < 0.2) & (y > 0.42) & (y < 0.62)] = 1.0
    out["MushroomChunk"] = save_rgba("MushroomChunk", white_alpha(chunk))

    # Trail strip: bright head on the left fading right, soft top/bottom edges.
    w, h = 256, 64
    u = np.linspace(0, 1, w)[None, :]
    v = np.linspace(-1, 1, h)[:, None]
    # Lengthwise frost streaks: a few bright lanes that thin out toward the tail.
    lanes = np.zeros((h, 1))
    for _ in range(5):
        lanes += rng.uniform(0.3, 0.8) * np.exp(-((v - rng.uniform(-0.6, 0.6)) / rng.uniform(0.06, 0.15)) ** 2)
    breakup = 0.55 + 0.45 * np.clip(lanes, 0, 1) ** (0.6 + 1.6 * u)
    trail = (1 - u) ** 1.4 * np.exp(-(v / 0.6) ** 2) * breakup
    out["FrostStreak"] = save_rgba("FrostStreak", white_alpha(trail))
    log("Wrote %d particle textures" % len(out))
    return out


def render_flipbook():
    """FrostBreath: a cold puff that swirls, swells and erodes away over 16
    frames. Rendered from a Cycles shader (4D noise, animated W and erosion),
    packed into a 4x4 grid (frame 0 top-left, row by row) at 1024x1024."""
    import numpy as np
    scene, coll = make_scene(SET_NAME + "_Flipbook")
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.render.film_transparent = True
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.image_settings.color_mode = "RGBA"

    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    mesh = bpy.data.meshes.new("FlipbookPlane")
    bm.to_mesh(mesh)
    bm.free()
    plane = bpy.data.objects.new("FlipbookPlane", mesh)
    coll.objects.link(plane)

    mat = bpy.data.materials.new("FM_FrostBreath")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixShader")
    transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
    emission = nt.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    coord = nt.nodes.new("ShaderNodeTexCoord")
    swirl = nt.nodes.new("ShaderNodeVectorRotate")
    swirl.rotation_type = "Z_AXIS"
    noise_node = nt.nodes.new("ShaderNodeTexNoise")
    noise_node.noise_dimensions = "4D"
    noise_node.inputs["Scale"].default_value = 3.2
    noise_node.inputs["Detail"].default_value = 6.0
    noise_node.inputs["Roughness"].default_value = 0.6
    length = nt.nodes.new("ShaderNodeVectorMath")
    length.operation = "LENGTH"
    radius = nt.nodes.new("ShaderNodeMath")
    radius.operation = "DIVIDE"
    falloff = nt.nodes.new("ShaderNodeMapRange")
    falloff.inputs["From Min"].default_value = 1.0
    falloff.inputs["From Max"].default_value = 0.2
    erode = nt.nodes.new("ShaderNodeMath")
    erode.operation = "SUBTRACT"
    density = nt.nodes.new("ShaderNodeMath")
    density.operation = "MULTIPLY"
    density.use_clamp = True
    gain = nt.nodes.new("ShaderNodeMath")
    gain.operation = "MULTIPLY"
    gain.use_clamp = True
    gain.inputs[1].default_value = 2.6

    links = nt.links
    links.new(coord.outputs["Object"], swirl.inputs["Vector"])
    links.new(swirl.outputs["Vector"], noise_node.inputs["Vector"])
    links.new(coord.outputs["Object"], length.inputs[0])
    links.new(length.outputs["Value"], radius.inputs[0])
    links.new(radius.outputs["Value"], falloff.inputs["Value"])
    links.new(noise_node.outputs["Fac"], erode.inputs[0])
    links.new(erode.outputs["Value"], density.inputs[0])
    links.new(falloff.outputs["Result"], density.inputs[1])
    links.new(density.outputs["Value"], gain.inputs[0])
    links.new(gain.outputs["Value"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    plane.data.materials.append(mat)

    cam_data = bpy.data.cameras.new("FlipbookCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 2.0
    cam = bpy.data.objects.new("FlipbookCam", cam_data)
    cam.location = (0, 0, 3)
    coll.objects.link(cam)
    scene.camera = cam

    frames = []
    tmp_dir = os.path.join(TEXTURE_DIR, "_flipbook_frames")
    os.makedirs(tmp_dir, exist_ok=True)
    for f in range(16):
        t = f / 15.0
        noise_node.inputs["W"].default_value = t * 1.6
        swirl.inputs["Angle"].default_value = t * 1.4
        radius.inputs[1].default_value = 0.35 + 0.6 * (1 - (1 - t) ** 2)  # puff swells, easing out
        erode.inputs[1].default_value = 0.22 + 0.42 * t ** 1.6  # then erodes away
        path = os.path.join(tmp_dir, "frame_%02d.png" % f)
        scene.render.filepath = path
        with bpy.context.temp_override(scene=scene):
            bpy.ops.render.render(write_still=True, scene=scene.name)
        img = bpy.data.images.load(path)
        px = np.array(img.pixels[:], dtype=np.float32).reshape(256, 256, 4)[::-1]  # top row first
        bpy.data.images.remove(img)
        frames.append(px)
        os.remove(path)
    os.rmdir(tmp_dir)

    atlas = np.zeros((1024, 1024, 4), dtype=np.float32)
    for f, px in enumerate(frames):
        row, col = divmod(f, 4)
        lum = px[..., :3].max(axis=2)
        atlas[row * 256:(row + 1) * 256, col * 256:(col + 1) * 256] = white_alpha(np.minimum(px[..., 3], lum))
    path = save_rgba("FrostBreathFlipbook", atlas)
    log("Rendered 16-frame flipbook -> %s" % path)

    if bpy.app.background:
        purge_collection(coll.name)
    else:
        bpy.data.scenes.remove(scene)
    return path


def build_vfx_meshes(coll):
    rng = random.Random(SEED + 23)
    b = PartBuilder()
    # Ice nova ring: shards around a circle, leaning outward (landing/hatch shockwave).
    for k in range(18):
        a = 2 * math.pi * k / 18
        radial = Vector((math.cos(a), math.sin(a), 0))
        b.crystal("NovaRing", radial * 3.0, (radial * 0.7 + Vector((0, 0, 1))).normalized(),
                  rng.uniform(1.2, 2.0), rng.uniform(0.22, 0.32), twist=rng.uniform(0, 1))
    # Crystal burst: shards radiating from a point (egg hatch, level-up flourish).
    for k in range(22):
        z = rng.uniform(-0.2, 1.0)
        a = rng.uniform(0, 2 * math.pi)
        d = Vector((math.cos(a) * math.sqrt(1 - z * z), math.sin(a) * math.sqrt(1 - z * z), z))
        b.crystal("CrystalBurst", d * 0.3, d, rng.uniform(1.0, 2.4), rng.uniform(0.15, 0.3))
    objects = b.to_objects(coll)
    PALETTE.setdefault("NovaRing", PALETTE["Crystals"])
    PALETTE.setdefault("CrystalBurst", PALETTE["Crystals"])
    GLOW_PARTS.update({"NovaRing", "CrystalBurst"})
    assign_materials(objects)

    # Hatch shell shards: chunky shell fragments, one mesh each, coloured like the shell.
    for i in range(12):
        sb = PartBuilder()
        part = ("Shell", "ShellBlue", "Frost")[i % 3]
        size = rng.uniform(0.7, 1.2)
        for _ in range(rng.randint(2, 4)):
            off = Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), rng.uniform(-0.2, 0.2))) * size
            sb.box(part, off, (size * rng.uniform(0.5, 0.9), size * rng.uniform(0.5, 0.9), 0.28), euler_deg(0, 0, rng.uniform(-20, 20)))
        shard_objects = sb.to_objects(coll, name_prefix="Shard%02d_" % (i + 1))
        for obj in shard_objects.values():
            obj.data.materials.append(material_for(part))
            obj.location.x = (i % 6) * 1.6 - 4
            obj.location.y = 6 + (i // 6) * 1.6
            objects[obj.name] = obj
    return objects


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
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


def main():
    log("Blender %s - building %s" % (bpy.app.version_string, SET_NAME))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    write_stud_overlay()
    manifest = {"palette": PALETTE, "stud_texture": "Textures/StudOverlay.png"}

    if BUILD_MONSTER:
        scene, coll = make_scene("FrostmaneWyrm")
        objects, sockets = build_wyrm(coll)
        check_budget(objects, "FrostmaneWyrm")
        manifest["FrostmaneWyrm"] = collect_manifest("FrostmaneWyrm", objects, sockets)
        export_glb(scene, list(objects.values()) + sockets, os.path.join(OUTPUT_DIR, "FrostmaneWyrm.glb"))
        setup_preview(scene, coll, target=(0, -1.5, 9.0), distance=48, height=9, angle_deg=-38)
        render_preview(scene, "FrostmaneWyrm_front.png")
        orbit_camera(scene, (0, 2.0, 8.5), 50, 14, 140)
        render_preview(scene, "FrostmaneWyrm_back.png")

    if BUILD_EGG:
        scene, coll = make_scene("FrostmaneEgg")
        objects, sockets = build_egg(coll)
        check_budget(objects, "FrostmaneEgg")
        manifest["FrostmaneEgg"] = collect_manifest("FrostmaneEgg", objects, sockets)
        export_glb(scene, list(objects.values()) + sockets, os.path.join(OUTPUT_DIR, "FrostmaneEgg.glb"))
        setup_preview(scene, coll, target=(0, 0, 3.6), distance=19, height=3.5, angle_deg=-30, size=(900, 900))
        render_preview(scene, "FrostmaneEgg.png")

    if BUILD_VFX:
        manifest["textures"] = {k: "Textures/%s.png" % k for k in write_particle_textures()}
        if RENDER_PREVIEWS:
            render_flipbook()
        manifest["textures"]["FrostBreathFlipbook"] = "Textures/FrostBreathFlipbook.png"
        manifest["textures"]["StudOverlay"] = "Textures/StudOverlay.png"
        scene, coll = make_scene("FrostmaneVFX")
        objects = build_vfx_meshes(coll)
        check_budget(objects, "FrostmaneVFXMeshes")
        manifest["FrostmaneVFXMeshes"] = collect_manifest("FrostmaneVFXMeshes", objects, [])
        export_glb(scene, list(objects.values()), os.path.join(OUTPUT_DIR, "FrostmaneVFXMeshes.glb"))
        setup_preview(scene, coll, target=(0, 2.5, 1.0), distance=22, height=9, angle_deg=-25, ground=True, size=(900, 700))
        render_preview(scene, "FrostmaneVFXMeshes.png")

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
