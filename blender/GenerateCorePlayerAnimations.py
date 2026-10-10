"""
GenerateCorePlayerAnimations.py  -  Blender 4.x
"+1 Chop Mushrooms for Eggs": core player motion suite

Builds an R15 skeleton (bones named after the R15 parts, one bone per
Motor6D) with a weapon bone under RightHand, bakes the player's weapon clips
at 60 fps, and exports them as FBX for Roblox Studio's Animation Editor.

    Attack1_Slash          0.55 s  forehand diagonal slice, high right -> low left
    Attack2_Backhand       0.55 s  flat backhand slice, left -> right
    Attack3_Uppercut       0.55 s  rising slice, low right -> overhead
    Attack4_OverheadChop   0.80 s  two-handed overhead chop finisher
    Idle_Weapon_Shoulder   2.80 s  loop, shaft resting on the right shoulder
    Run_Weapon_Drag        0.70 s  loop, deep forward lean, blade tip dragging the floor

The four attacks are cut from ONE cyclic combo timeline, so the end of each
hit flows (same pose, same velocity) into the start of the next, and Attack4
flows back into Attack1. Holding the mouse loops the chain seamlessly.
"Combo_FullLoop" holds the whole chain for previewing in Blender (not exported).
Slices and chops are mixed so the chain reads well for both swords and axes.

How the motion is built
  * Key poses -> cyclic cubic Hermite splines per channel, sampled every frame
    (C1-continuous: no velocity pops at keys or across loop seams).
  * The right hand is placed with 2-bone IK (shoulder -> target, elbow toward
    a pole), then the wrist is aimed so the weapon points along a direction
    given as (yaw, pitch). Arcs are interpolated in yaw/pitch, so blades
    travel on real arcs.
  * Weapon orientation lives on RightHand, NOT on the Handle bone, so it
    still reads in Roblox when the Tool is attached by the default RightGrip weld.
  * Anticipation keys ease to a hold, strikes accelerate through contact,
    impacts overshoot ~5% and settle with an elastic rebound, and child joints
    (head, free arm) trail their parents for follow-through.

Run it: paste into Blender's Text Editor and press Alt+P, or headless:
    blender --background --python GenerateCorePlayerAnimations.py
Output (~/Documents/CorePlayerAnimations/): one FBX per clip, a bundle FBX,
AnimationEvents.json (marker times) and the .blend.

Conventions (all bones point +Z with zero roll, so pose channels are in
character space):
    +X = character's left, -Y = character's forward, +Z = up. 1 Blender unit = 1 stud.
    rot = (pitch, yaw, roll) degrees: pitch+ leans forward / swings a hanging
    limb back, yaw+ turns left, roll+ tilts toward the character's left.
    loc = (left, up, forward) studs.  Offsets for IK targets use (left, up, forward).

Roblox notes
  * Blender markers do not survive FBX import: add the Animation Events listed
    in AnimationEvents.json in the Animation Editor (the controller also has
    timed fallbacks).
  * Attacks key the Waist and above only (CHOP_UPPER_BODY_ONLY) so the legs
    keep running/idling underneath a swing.
"""

import bpy  # noqa: I001  (bpy first: bmesh/mathutils need it loaded when run outside Blender's UI)
import bmesh
import json
import math
import os
import traceback
from mathutils import Matrix, Quaternion, Vector

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
ASSET_NAME = "CorePlayerAnimations"
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", ASSET_NAME)
SCENE_NAME = ASSET_NAME
COLLECTION_NAME = ASSET_NAME
RIG_NAME = "R15_Rig"
PROXY_NAME = "R15_Proxy"
LOG_NAME = ASSET_NAME + "_Log"

FPS = 60
WEAPON_BONE_NAME = "Handle"
CHOP_UPPER_BODY_ONLY = True
BUILD_PROXY_MESH = True  # blocky R15 preview body + axe, skinned to the rig (not exported)

# Grip-to-tip length of the weapon the drag run is tuned for. The run aims the
# tip at the floor behind the player: longer weapons sink a little into the
# floor and shorter ones hover. The in-hand Frostroot Cleaver is about 6.2.
WEAPON_DRAG_LENGTH = 4.5
LEFT_HAND_SHAFT_OFFSET = -0.55  # two-handed grip: left wrist this far along the shaft (negative = toward the pommel)

# Roblox is Y-up with -Z forward. If clips import facing backwards, set
# EXPORT_AXIS_FORWARD to "Z". If torso dips import far too big or small, change
# EXPORT_SCALE; rotations are not affected by scale.
EXPORT_AXIS_FORWARD = "-Z"
EXPORT_AXIS_UP = "Y"
EXPORT_SCALE = 1.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_lines = []


def log(message):
    print("[%s] %s" % (ASSET_NAME, message))
    _log_lines.append(message)


def flush_log():
    text = bpy.data.texts.get(LOG_NAME) or bpy.data.texts.new(LOG_NAME)
    text.clear()
    text.write("\n".join(_log_lines) + "\n")


# ---------------------------------------------------------------------------
# Easing / periodic shapes
# ---------------------------------------------------------------------------
def ease_in_out_sine(x):
    return -(math.cos(math.pi * x) - 1.0) / 2.0


def elastic_wave(phase, lag, harmonic=0.22):
    """Periodic sway that trails its driver by `lag` radians, with a second
    harmonic so it snaps past centre and settles like a spring."""
    return math.sin(phase - lag) + harmonic * math.sin(2.0 * phase - 1.8 * lag)


def bounce(phase, lag=0.0, sharpness=0.8):
    """0 at each foot contact (phase 0, pi), 1 mid-stride. Sharp dip, round top."""
    return (1.0 - abs(math.cos(phase - lag))) ** sharpness


# ---------------------------------------------------------------------------
# R15 skeleton (Motor6D-equivalent joints)
# name, parent, joint pivot (x, y, z), Motor6D name
# ---------------------------------------------------------------------------
R15_JOINTS = [
    ("HumanoidRootPart", None, (0.0, 0.0, 3.0), None),
    ("LowerTorso", "HumanoidRootPart", (0.0, 0.0, 2.8), "Root"),
    ("UpperTorso", "LowerTorso", (0.0, 0.0, 3.2), "Waist"),
    ("Head", "UpperTorso", (0.0, 0.0, 4.55), "Neck"),
    ("LeftUpperArm", "UpperTorso", (1.25, 0.0, 4.35), "LeftShoulder"),
    ("LeftLowerArm", "LeftUpperArm", (1.5, 0.0, 3.55), "LeftElbow"),
    ("LeftHand", "LeftLowerArm", (1.5, 0.0, 2.8), "LeftWrist"),
    ("RightUpperArm", "UpperTorso", (-1.25, 0.0, 4.35), "RightShoulder"),
    ("RightLowerArm", "RightUpperArm", (-1.5, 0.0, 3.55), "RightElbow"),
    ("RightHand", "RightLowerArm", (-1.5, 0.0, 2.8), "RightWrist"),
    (WEAPON_BONE_NAME, "RightHand", (-1.5, 0.0, 2.45), "WeaponGrip"),
    ("LeftUpperLeg", "LowerTorso", (0.5, 0.0, 2.6), "LeftHip"),
    ("LeftLowerLeg", "LeftUpperLeg", (0.5, 0.0, 1.45), "LeftKnee"),
    ("LeftFoot", "LeftLowerLeg", (0.5, 0.0, 0.4), "LeftAnkle"),
    ("RightUpperLeg", "LowerTorso", (-0.5, 0.0, 2.6), "RightHip"),
    ("RightLowerLeg", "RightUpperLeg", (-0.5, 0.0, 1.45), "RightKnee"),
    ("RightFoot", "RightLowerLeg", (-0.5, 0.0, 0.4), "RightAnkle"),
]
BONE_LENGTH = 0.35

UPPER_BODY = [
    "UpperTorso", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightUpperArm", "RightLowerArm", "RightHand", WEAPON_BONE_NAME,
]
FULL_BODY = [name for name, _, _, _ in R15_JOINTS if name != "HumanoidRootPart"]

# Proxy blocks: bone, centre, size (blocky R15 proportions in studs)
PROXY_BLOCKS = [
    ("LowerTorso", (0.0, 0.0, 2.75), (2.0, 1.0, 0.5)),
    ("UpperTorso", (0.0, 0.0, 3.85), (2.0, 1.0, 1.6)),
    ("Head", (0.0, 0.0, 5.2), (1.2, 1.2, 1.2)),
    ("LeftUpperArm", (1.5, 0.0, 3.95), (1.0, 1.0, 1.0)),
    ("LeftLowerArm", (1.5, 0.0, 3.2), (0.95, 0.95, 0.8)),
    ("LeftHand", (1.5, 0.0, 2.6), (0.9, 0.9, 0.45)),
    ("RightUpperArm", (-1.5, 0.0, 3.95), (1.0, 1.0, 1.0)),
    ("RightLowerArm", (-1.5, 0.0, 3.2), (0.95, 0.95, 0.8)),
    ("RightHand", (-1.5, 0.0, 2.6), (0.9, 0.9, 0.45)),
    ("LeftUpperLeg", (0.5, 0.0, 2.0), (1.0, 1.0, 1.2)),
    ("LeftLowerLeg", (0.5, 0.0, 0.95), (0.95, 0.95, 1.0)),
    ("LeftFoot", (0.5, -0.1, 0.2), (1.0, 1.2, 0.4)),
    ("RightUpperLeg", (-0.5, 0.0, 2.0), (1.0, 1.0, 1.2)),
    ("RightLowerLeg", (-0.5, 0.0, 0.95), (0.95, 0.95, 1.0)),
    ("RightFoot", (-0.5, -0.1, 0.2), (1.0, 1.2, 0.4)),
    # Axe, grip-to-tip = WEAPON_DRAG_LENGTH. With the arm hanging, a Roblox Tool
    # on the standard grip points forward (-Y), so the proxy does too.
    (WEAPON_BONE_NAME, (-1.5, -WEAPON_DRAG_LENGTH / 2 + 0.3, 2.45), (0.25, WEAPON_DRAG_LENGTH + 0.6, 0.25)),
    (WEAPON_BONE_NAME, (-1.5, -WEAPON_DRAG_LENGTH + 0.45, 2.85), (0.2, 0.9, 1.1)),
]


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------
ACTION_PREFIXES = (
    "Attack", "Combo_FullLoop", "Idle_Weapon", "Run_Weapon",
    "Weapon_Chop_Heavy",  # clip names from the first version of this script
)


def purge_previous_build():
    old_scene = bpy.data.scenes.get(SCENE_NAME)
    if old_scene is not None:
        # Empty the scene but keep it: deleting the scene you're looking at
        # (it's active after a previous run) crashes Blender.
        for obj in list(old_scene.collection.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
    # Objects orphaned by earlier runs keep their names and would make ours ".001".
    for obj in list(bpy.data.objects):
        if obj.users_scene == () and obj.name.startswith((RIG_NAME, PROXY_NAME)):
            bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        if action.name.startswith(ACTION_PREFIXES):
            bpy.data.actions.remove(action)
    for armature in list(bpy.data.armatures):
        if armature.users == 0:
            bpy.data.armatures.remove(armature)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is not None and coll.users == 0:
        bpy.data.collections.remove(coll)


def make_scene():
    scene = bpy.data.scenes.get(SCENE_NAME) or bpy.data.scenes.new(SCENE_NAME)
    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    coll = bpy.data.collections.get(COLLECTION_NAME) or bpy.data.collections.new(COLLECTION_NAME)
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)

    if bpy.context.window is not None and not bpy.app.background and bpy.context.window.scene != scene:
        bpy.context.window.scene = scene
    return scene, coll


def scene_override(scene, active=None, selected=None):
    """Context override so ops run against our scene, also in --background."""
    view_layer = scene.view_layers[0]
    kwargs = {"scene": scene, "view_layer": view_layer}
    if active is not None:
        kwargs["active_object"] = active
        kwargs["object"] = active
    if selected is not None:
        kwargs["selected_objects"] = selected
        kwargs["selected_editable_objects"] = selected
    return bpy.context.temp_override(**kwargs)


# ---------------------------------------------------------------------------
# Rig
# ---------------------------------------------------------------------------
def build_rig(scene, coll):
    armature = bpy.data.armatures.new(RIG_NAME)
    armature.display_type = "STICK"
    rig = bpy.data.objects.new(RIG_NAME, armature)
    rig.show_in_front = True
    coll.objects.link(rig)

    view_layer = scene.view_layers[0]
    view_layer.objects.active = rig
    rig.select_set(True, view_layer=view_layer)

    with scene_override(scene, active=rig, selected=[rig]):
        bpy.ops.object.mode_set(mode="EDIT")
        for name, parent, head, _motor in R15_JOINTS:
            bone = armature.edit_bones.new(name)
            bone.head = head
            bone.tail = (head[0], head[1], head[2] + BONE_LENGTH)
            bone.roll = 0.0
            bone.use_deform = name != "HumanoidRootPart"
            if parent:
                bone.parent = armature.edit_bones[parent]
                bone.use_connect = False
        bpy.ops.object.mode_set(mode="OBJECT")

    for name, parent, _head, motor in R15_JOINTS:
        pose_bone = rig.pose.bones[name]
        pose_bone.rotation_mode = "XYZ"
        if motor:
            # Documents the Roblox joint this bone stands in for (Part0 -> Part1).
            pose_bone.bone["Motor6D"] = motor
            pose_bone.bone["Part0"] = parent
            pose_bone.bone["Part1"] = name

    log("Rig built: %d bones (weapon bone '%s' under RightHand)" % (len(R15_JOINTS), WEAPON_BONE_NAME))
    return rig


def build_proxy(coll, rig):
    mesh = bpy.data.meshes.new(PROXY_NAME)
    proxy = bpy.data.objects.new(PROXY_NAME, mesh)
    coll.objects.link(proxy)

    bm = bmesh.new()
    groups = {}
    deform = bm.verts.layers.deform.verify()
    for bone, centre, size in PROXY_BLOCKS:
        if bone not in groups:
            groups[bone] = proxy.vertex_groups.new(name=bone).index
        matrix = Matrix.Translation(centre) @ Matrix.Diagonal((size[0], size[1], size[2], 1.0))
        result = bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)
        for vert in result["verts"]:
            vert[deform][groups[bone]] = 1.0
    bm.to_mesh(mesh)
    bm.free()

    proxy.parent = rig
    modifier = proxy.modifiers.new("Armature", "ARMATURE")
    modifier.object = rig
    proxy.hide_select = True
    log("Proxy body built: %d blocks" % len(PROXY_BLOCKS))
    return proxy


# ---------------------------------------------------------------------------
# Pose solving: FK body + right-arm IK + wrist aim + optional left-hand IK
# ---------------------------------------------------------------------------
def char_offset(left, up, forward):
    """(left, up, forward) in character space -> armature-space vector."""
    return Vector((left, -forward, up))


def weapon_direction(yaw, pitch):
    """yaw 0 = forward, +90 = character's left; pitch 0 = level, +90 = up,
    beyond 90 continues over the top toward the back (180 = straight back)."""
    y, p = math.radians(yaw), math.radians(pitch)
    return Vector((math.cos(p) * math.sin(y), -math.cos(p) * math.cos(y), math.sin(p))).normalized()


def rotate_about(pose_bone, pivot, rotation):
    """Rotate a pose bone's armature-space matrix about a pivot point."""
    pose_bone.matrix = (
        Matrix.Translation(pivot) @ rotation.to_matrix().to_4x4() @ Matrix.Translation(-pivot) @ pose_bone.matrix
    )


def two_bone_ik(view_layer, upper, lower, hand, target, pole):
    """Place `hand`'s joint at `target`, bending the elbow toward `pole`
    (an armature-space direction). Bone lengths come from the rest pose."""
    shoulder = upper.head.copy()
    a = (lower.bone.head_local - upper.bone.head_local).length
    b = (hand.bone.head_local - lower.bone.head_local).length

    to_target = target - shoulder
    dist = min(max(to_target.length, abs(a - b) + 1e-3), a + b - 1e-3)
    axis = to_target.normalized()
    along = (a * a - b * b + dist * dist) / (2.0 * dist)
    height = math.sqrt(max(a * a - along * along, 0.0))
    bend = pole - axis * pole.dot(axis)
    if bend.length < 1e-5:
        bend = Vector((0.0, 0.0, -1.0)) - axis * axis.z
    bend.normalize()
    elbow = shoulder + axis * along + bend * height
    wrist = shoulder + axis * dist

    rotate_about(upper, shoulder, (lower.head - shoulder).rotation_difference(elbow - shoulder))
    view_layer.update()
    rotate_about(lower, lower.head.copy(), (hand.head - lower.head).rotation_difference(wrist - lower.head))
    view_layer.update()


def aim_weapon(view_layer, hand, forearm_root, direction, twist_deg=0.0, up_hint=None):
    """Orient the wrist so the weapon (hand-local +Z, like the Handle bone)
    points along `direction`. The hand's +Y follows `up_hint` if given (the
    combo carries it frame to frame so the wrist never spins), otherwise it
    points back toward the elbow."""
    z_axis = direction.normalized()
    toward_elbow = up_hint if up_hint is not None else forearm_root.head - hand.head
    y_axis = toward_elbow - z_axis * toward_elbow.dot(z_axis)
    if y_axis.length < 1e-4:  # weapon in line with the forearm: fall back to world up
        y_axis = Vector((0.0, 0.0, 1.0)) - z_axis * z_axis.z
        if y_axis.length < 1e-4:
            y_axis = Vector((0.0, 1.0, 0.0))
    y_axis.normalize()
    x_axis = y_axis.cross(z_axis)
    rotation = Matrix((x_axis, y_axis, z_axis)).transposed()
    if abs(twist_deg) > 1e-4:
        rotation = Quaternion(z_axis, math.radians(twist_deg)).to_matrix() @ rotation
    matrix = rotation.to_4x4()
    matrix.translation = hand.head
    hand.matrix = matrix
    view_layer.update()


def apply_pose(rig, view_layer, pose):
    """pose: {"bones": {name: {"rot", "loc"}}, "hand": (l,u,f) offset from the
    right shoulder, "pole": (l,u,f), "weapon": (yaw, pitch[, twist]) or a
    Vector, "left_ik": 0..1, "left_pole": (l,u,f)}. Returns basis per bone."""
    for pose_bone in rig.pose.bones:
        pose_bone.rotation_mode = "XYZ"  # poses are authored as eulers
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.rotation_euler = (0.0, 0.0, 0.0)
        pose_bone.scale = (1.0, 1.0, 1.0)
    for name, entry in pose.get("bones", {}).items():
        pose_bone = rig.pose.bones[name]
        pose_bone.rotation_euler = [math.radians(v) for v in entry.get("rot", (0, 0, 0))]
        pose_bone.location = entry.get("loc", (0, 0, 0))
    view_layer.update()

    bones = rig.pose.bones
    r_upper, r_lower, r_hand = bones["RightUpperArm"], bones["RightLowerArm"], bones["RightHand"]
    weapon = bones[WEAPON_BONE_NAME]

    pole = char_offset(*pose.get("pole", (-1, -0.3, -0.3)))
    if "hand" in pose:
        # Start the IK from an arm held forward: overhead and low targets are
        # then both well under 180 degrees away, so the solve never flips.
        r_upper.rotation_euler = (math.radians(-90.0), 0.0, 0.0)
        r_lower.rotation_euler = (0.0, 0.0, 0.0)
        view_layer.update()
        target = r_upper.head + char_offset(*pose["hand"])
        two_bone_ik(view_layer, r_upper, r_lower, r_hand, target, pole)

    if "weapon" in pose:
        spec = pose["weapon"]
        if callable(spec):
            # Turning the wrist moves the grip, so re-aim until the target holds.
            for _ in range(4):
                aim_weapon(view_layer, r_hand, r_lower, spec(rig))
        else:
            twist = spec[2] if len(spec) > 2 else 0.0
            aim_weapon(view_layer, r_hand, r_lower, weapon_direction(spec[0], spec[1]), twist, pose.get("hand_up"))

    # Any pose that has "left_ik" (the combo) solves the left arm by IK every
    # frame, even at weight 0 where the target is the free-arm hand position,
    # so picking up and letting go of the shaft never switches solvers mid-swing.
    if "left_ik" in pose:
        left_ik = pose["left_ik"]
        l_upper, l_lower, l_hand = bones["LeftUpperArm"], bones["LeftLowerArm"], bones["LeftHand"]
        shaft = weapon.matrix.col[2].xyz.normalized()
        wrist_target = r_hand.head + shaft * LEFT_HAND_SHAFT_OFFSET
        target = l_hand.head.lerp(wrist_target, min(max(left_ik, 0.0), 1.0))
        # Solve from an arm held forward (see the right arm) so it never flips.
        l_upper.rotation_euler = (math.radians(-90.0), 0.0, 0.0)
        l_lower.rotation_euler = (0.0, 0.0, 0.0)
        view_layer.update()
        two_bone_ik(view_layer, l_upper, l_lower, l_hand, target, char_offset(*pose.get("left_pole", (1, -0.6, -0.2))))

    return {b.name: (b.matrix_basis.to_quaternion(), b.location.copy()) for b in rig.pose.bones}


# ---------------------------------------------------------------------------
# Cyclic cubic spline over key poses
# ---------------------------------------------------------------------------
def flatten(pose):
    """Pose -> {channel_key: float} for every numeric channel."""
    out = {}
    for name, entry in pose.get("bones", {}).items():
        for kind in ("rot", "loc"):
            for i, value in enumerate(entry.get(kind, (0, 0, 0))):
                out[("bones", name, kind, i)] = float(value)
    for field in ("hand", "pole", "weapon", "left_pole"):
        if field in pose:
            for i, value in enumerate(pose[field]):
                out[(field, i)] = float(value)
    if "left_ik" in pose:
        out[("left_ik",)] = float(pose["left_ik"])
    return out


def unflatten(channels):
    pose = {"bones": {}}
    for key, value in channels.items():
        if key[0] == "bones":
            _, name, kind, i = key
            entry = pose["bones"].setdefault(name, {"rot": [0.0] * 3, "loc": [0.0] * 3})
            entry[kind][i] = value
        elif key[0] == "left_ik":
            pose["left_ik"] = value
        else:
            pose.setdefault(key[0], [0.0, 0.0, 0.0])
            pose[key[0]][key[1]] = value
    for field in ("weapon",):
        if field in pose:
            pose[field] = tuple(pose[field])
    return pose


def merge(base, **changes):
    """Copy of `base` with nested bone entries and top-level fields replaced."""
    out = {"bones": {k: dict(v) for k, v in base.get("bones", {}).items()}}
    for key, value in base.items():
        if key != "bones":
            out[key] = value
    for key, value in changes.items():
        if key == "bones":
            for name, entry in value.items():
                out["bones"].setdefault(name, {}).update(entry)
        else:
            out[key] = value
    return out


def mix(a, b, t):
    """Per-channel lerp of two poses; t outside 0..1 extrapolates (overshoot)."""
    fa, fb = flatten(a), flatten(b)
    keys = set(fa) | set(fb)
    return unflatten({k: fa.get(k, 0.0) + (fb.get(k, 0.0) - fa.get(k, 0.0)) * t for k in keys})


class PoseSpline:
    """keys: [(time_s, pose, mode)], mode "smooth" (Catmull-Rom tangent) or
    "ease" (zero velocity: anticipation holds, overshoot extremes).
    cyclic: the last key's pose must equal the first; tangents wrap."""

    def __init__(self, keys, cyclic):
        self.times = [k[0] for k in keys]
        self.modes = [k[2] for k in keys]
        flats = [flatten(k[1]) for k in keys]
        self.channels = sorted(set().union(*flats), key=str)
        self.values = [[f.get(c, 0.0) for c in self.channels] for f in flats]
        self.cyclic = cyclic
        self.period = self.times[-1] - self.times[0]
        self.tangents = [self._tangent(i) for i in range(len(keys))]

    def _tangent(self, i):
        n = len(self.times)
        if self.modes[i] == "ease":
            return [0.0] * len(self.channels)
        if self.cyclic and (i == 0 or i == n - 1):
            prev_i, next_i = n - 2, 1
            dt0 = self.times[-1] - self.times[-2]
            dt1 = self.times[1] - self.times[0]
        elif i == 0 or i == n - 1:
            return [0.0] * len(self.channels)
        else:
            prev_i, next_i = i - 1, i + 1
            dt0 = self.times[i] - self.times[i - 1]
            dt1 = self.times[i + 1] - self.times[i]
        p, c, nx = self.values[prev_i], self.values[i], self.values[next_i]
        # Non-uniform Catmull-Rom: time-weighted average of neighbouring slopes.
        return [((c[j] - p[j]) / dt0 * dt1 + (nx[j] - c[j]) / dt1 * dt0) / (dt0 + dt1)
                for j in range(len(self.channels))]

    def sample(self, t):
        if self.cyclic:
            t = self.times[0] + (t - self.times[0]) % self.period
        t = min(max(t, self.times[0]), self.times[-1])
        i = 0
        while i < len(self.times) - 2 and t > self.times[i + 1]:
            i += 1
        t0, t1 = self.times[i], self.times[i + 1]
        h = t1 - t0
        s = (t - t0) / h
        s2, s3 = s * s, s * s * s
        h00, h10, h01, h11 = 2 * s3 - 3 * s2 + 1, s3 - 2 * s2 + s, -2 * s3 + 3 * s2, s3 - s2
        p0, p1, m0, m1 = self.values[i], self.values[i + 1], self.tangents[i], self.tangents[i + 1]
        return unflatten({c: h00 * p0[j] + h10 * h * m0[j] + h01 * p1[j] + h11 * h * m1[j]
                          for j, c in enumerate(self.channels)})


# ---------------------------------------------------------------------------
# Baking
# ---------------------------------------------------------------------------
def action_fcurves(action):
    """F-curves for legacy (<=4.3) and slotted/layered (4.4+) actions."""
    layers = getattr(action, "layers", None)
    if layers is not None and len(layers) > 0:
        for layer in layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", []):
                    yield from bag.fcurves
    else:
        yield from action.fcurves


def bake_action(rig, view_layer, name, frame_count, pose_at, bones, cyclic, markers=None):
    """pose_at(frame) -> pose. Keys every frame 0..frame_count on `bones`."""
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    action.use_frame_range = True
    action.frame_start = 0
    action.frame_end = frame_count
    action.use_cyclic = cyclic
    if rig.animation_data is None:
        rig.animation_data_create()
    rig.animation_data.action = action

    previous = {}
    samples = []
    for frame in range(frame_count + 1):
        basis = apply_pose(rig, view_layer, pose_at(frame))
        for bone, (quat, _loc) in basis.items():
            # Quaternions avoid euler gimbal flips; keep each on the same
            # hemisphere as the previous frame so interpolation takes the short way.
            if bone in previous and quat.dot(previous[bone]) < 0.0:
                quat.negate()
            previous[bone] = quat
        samples.append(basis)

    # Cyclic clips: make the seam frame identical to frame 0.
    if cyclic:
        samples[-1] = samples[0]
    for pose_bone in rig.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"

    for frame, basis in enumerate(samples):
        for bone in bones:
            quat, loc = basis[bone]
            pose_bone = rig.pose.bones[bone]
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.rotation_quaternion = quat
            pose_bone.location = loc
            pose_bone.keyframe_insert("rotation_quaternion", frame=frame, group=bone)
            pose_bone.keyframe_insert("location", frame=frame, group=bone)

    for fcurve in action_fcurves(action):
        for point in fcurve.keyframe_points:
            point.interpolation = "LINEAR"  # dense 60 fps samples; keep exactly what was solved
        fcurve.update()

    for marker_name, frame in (markers or {}).items():
        marker = action.pose_markers.new(marker_name)
        marker.frame = frame

    log("Baked %s: %d frames (%.3f s)%s" % (
        name, frame_count + 1, frame_count / FPS, ", markers %s" % markers if markers else ""))
    return action


def frames(seconds):
    return int(round(seconds * FPS))


# ---------------------------------------------------------------------------
# Attack combo (one cyclic timeline cut into four clips)
# ---------------------------------------------------------------------------
def B(**bones):
    """Shorthand: B(UpperTorso=(p, y, r), LowerTorso=((p, y, r), (l, u, f)))"""
    out = {}
    for name, value in bones.items():
        if isinstance(value[0], (tuple, list)):
            out[name] = {"rot": value[0], "loc": value[1]}
        else:
            out[name] = {"rot": value}
    return out


GUARD = {
    "bones": B(
        LowerTorso=((3, -6, 0), (0, -0.05, 0)), UpperTorso=(6, -10, 0), Head=(-4, 10, 0),
        LeftUpperArm=(-25, 0, 18), LeftLowerArm=(-40, 0, 0), LeftHand=(0, 0, 0),
        RightUpperLeg=(-12, 0, -8), RightLowerLeg=(20, 0, 0), RightFoot=(-8, 0, 8),
        LeftUpperLeg=(-16, 0, 8), LeftLowerLeg=(24, 0, 0), LeftFoot=(-8, 0, -8),
    ),
    "hand": (0.45, -0.6, 1.15), "pole": (-1, -0.4, -0.2),
    "weapon": (-15, 65, 0), "left_ik": 0.0, "left_pole": (1, -0.6, -0.2),
}

# --- Hit 1: forehand diagonal slice (high right -> low left) ---
SLASH_WINDUP = merge(GUARD, bones=B(
    LowerTorso=((0, -16, 0), (0, -0.02, 0)), UpperTorso=(-8, -40, 6), Head=(6, 32, 0),
    LeftUpperArm=(-70, 0, 25), LeftLowerArm=(-30, 0, 0),
), hand=(-0.35, 0.75, 0.55), pole=(-1, 0.2, -0.3), weapon=(-135, 40, 0))
SLASH_HIT = merge(GUARD, bones=B(
    LowerTorso=((6, 6, 0), (0, -0.12, 0)), UpperTorso=(22, 10, -6), Head=(-14, -8, 0),
    LeftUpperArm=(20, 0, 30), LeftLowerArm=(-40, 0, 0),
), hand=(0.6, 0.0, 1.35), pole=(-1, -0.5, 0), weapon=(5, -5, 0))
SLASH_THROUGH = merge(GUARD, bones=B(
    LowerTorso=((8, 16, 0), (0, -0.16, 0)), UpperTorso=(26, 34, -8), Head=(-16, -28, 0),
    LeftUpperArm=(35, 0, 35), LeftLowerArm=(-30, 0, 0),
), hand=(1.1, -0.65, 0.9), pole=(-0.5, -1, 0.2), weapon=(80, -40, 0))
LINK_1 = merge(SLASH_THROUGH, bones=B(
    LowerTorso=((6, 12, 0), (0, -0.12, 0)), UpperTorso=(18, 30, -6), Head=(-12, -24, 0),
    LeftUpperArm=(25, 0, 30), LeftLowerArm=(-35, 0, 0),
), hand=(1.0, -0.5, 0.85), weapon=(70, -30, 0))

# --- Hit 2: flat backhand slice (left -> right) ---
BACK_WINDUP = merge(LINK_1, bones=B(
    LowerTorso=((2, 18, 0), (0, -0.06, 0)), UpperTorso=(-2, 42, 4), Head=(-4, -36, 0),
    LeftUpperArm=(30, 0, 40), LeftLowerArm=(-30, 0, 0),
), hand=(1.05, 0.05, 0.6), pole=(0.2, 0.4, -1), weapon=(120, 10, 0))
BACK_HIT = merge(LINK_1, bones=B(
    LowerTorso=((4, -4, 0), (0, -0.1, 0)), UpperTorso=(14, -8, 0), Head=(-10, 8, 0),
    LeftUpperArm=(-10, 0, 30), LeftLowerArm=(-45, 0, 0),
), hand=(0.2, -0.05, 1.45), pole=(-0.4, -1, -0.2), weapon=(-5, 5, 0))
BACK_THROUGH = merge(LINK_1, bones=B(
    LowerTorso=((6, -16, 0), (0, -0.12, 0)), UpperTorso=(16, -38, 2), Head=(-10, 32, 0),
    LeftUpperArm=(-60, 0, 15), LeftLowerArm=(-50, 0, 0),
), hand=(-0.7, 0.0, 1.1), pole=(-1, -0.6, 0), weapon=(-100, 15, 0))
LINK_2 = merge(BACK_THROUGH, bones=B(
    LowerTorso=((4, -12, 0), (0, -0.1, 0)), UpperTorso=(12, -32, 2), Head=(-8, 26, 0),
), hand=(-0.6, -0.25, 0.95), weapon=(-90, -5, 0))

# --- Hit 3: rising uppercut slice (low right -> overhead) ---
UPPER_WINDUP = merge(LINK_2, bones=B(
    LowerTorso=((10, -16, 0), (0, -0.22, 0)), UpperTorso=(24, -36, -6), Head=(-20, 28, 0),
    LeftUpperArm=(-40, 0, 20), LeftLowerArm=(-60, 0, 0),
), hand=(-0.45, -0.95, 0.75), pole=(-1, 0.3, -0.4), weapon=(-115, -45, 0))
UPPER_HIT = merge(LINK_2, bones=B(
    LowerTorso=((2, 0, 0), (0, -0.06, 0)), UpperTorso=(4, 0, 0), Head=(-4, 0, 0),
    LeftUpperArm=(10, 0, 30), LeftLowerArm=(-40, 0, 0),
), hand=(0.4, -0.1, 1.35), pole=(-1, -0.6, 0), weapon=(-10, 25, 0))
UPPER_THROUGH = merge(LINK_2, bones=B(
    LowerTorso=((-4, 10, 0), (0, 0.08, 0)), UpperTorso=(-14, 26, 6), Head=(10, -20, 0),
    LeftUpperArm=(25, 0, 45), LeftLowerArm=(-30, 0, 0),
), hand=(0.85, 0.95, 0.7), pole=(-1, -0.2, 0.3), weapon=(45, 90, 0), left_ik=0.35)
LINK_3 = merge(UPPER_THROUGH, bones=B(
    LowerTorso=((-3, 0, 0), (0, 0.04, 0)), UpperTorso=(-12, 4, 2), Head=(8, 0, 0),
), hand=(0.9, 1.05, 0.4), pole=(-1, 0.2, 0.4), weapon=(0, 120, 0), left_ik=1.0)

# --- Hit 4: two-handed overhead chop finisher ---
CHOP_WINDUP = merge(LINK_3, bones=B(
    LowerTorso=((-5, 0, 0), (0, 0.06, 0)), UpperTorso=(-18, 0, 0), Head=(12, 0, 0),
), hand=(0.95, 1.05, -0.1), pole=(-1, 0.3, 0.3), weapon=(0, 215, 0), left_ik=1.0)
CHOP_HIT = merge(LINK_3, bones=B(
    LowerTorso=((10, 0, 0), (0, -0.3, 0)), UpperTorso=(34, 0, 0), Head=(-22, 0, 0),
), hand=(0.9, -0.7, 0.95), pole=(-1, -0.4, -0.3), weapon=(0, -40, 0), left_ik=1.0)
CHOP_RECOVER = merge(CHOP_HIT, bones=B(
    LowerTorso=((6, -3, 0), (0, -0.16, 0)), UpperTorso=(18, -5, 0), Head=(-12, 4, 0),
), hand=(0.7, -0.65, 1.1), weapon=(-5, 0, 0), left_ik=0.5)

# (time_s, pose, mode). Strikes stay "smooth" so they carry speed through contact.
COMBO_KEYS = [
    (0.00, GUARD, "smooth"),
    # Attack1_Slash  0.00 - 0.55
    (0.15, SLASH_WINDUP, "ease"),
    (0.19, mix(GUARD, SLASH_WINDUP, 1.04), "ease"),  # coil: wind-up creeps back 4%
    (0.29, SLASH_HIT, "smooth"),
    (0.35, mix(SLASH_HIT, SLASH_THROUGH, 1.05), "ease"),  # 5% overshoot
    (0.43, mix(SLASH_HIT, SLASH_THROUGH, 0.97), "ease"),  # elastic rebound
    (0.55, LINK_1, "smooth"),
    # Attack2_Backhand  0.55 - 1.10
    (0.68, BACK_WINDUP, "ease"),
    (0.72, mix(LINK_1, BACK_WINDUP, 1.04), "ease"),
    (0.82, BACK_HIT, "smooth"),
    (0.88, mix(BACK_HIT, BACK_THROUGH, 1.05), "ease"),
    (0.96, mix(BACK_HIT, BACK_THROUGH, 0.97), "ease"),
    (1.10, LINK_2, "smooth"),
    # Attack3_Uppercut  1.10 - 1.65
    (1.23, UPPER_WINDUP, "ease"),
    (1.27, mix(LINK_2, UPPER_WINDUP, 1.04), "ease"),
    (1.37, UPPER_HIT, "smooth"),
    (1.44, mix(UPPER_HIT, UPPER_THROUGH, 1.05), "ease"),
    (1.52, mix(UPPER_HIT, UPPER_THROUGH, 0.97), "ease"),
    (1.65, LINK_3, "smooth"),
    # Attack4_OverheadChop  1.65 - 2.45
    (1.85, CHOP_WINDUP, "ease"),
    (1.90, mix(LINK_3, CHOP_WINDUP, 1.04), "ease"),
    (2.02, CHOP_HIT, "smooth"),
    (2.05, mix(CHOP_WINDUP, CHOP_HIT, 1.05), "ease"),  # heavy impact frame
    (2.12, mix(CHOP_WINDUP, CHOP_HIT, 0.97), "ease"),  # elastic bounce
    (2.19, mix(CHOP_WINDUP, CHOP_HIT, 1.01), "ease"),
    (2.31, CHOP_RECOVER, "smooth"),
    (2.45, GUARD, "smooth"),  # == first key: the chain loops
]

# (action name, start s, end s, {marker: absolute s})
COMBO_CLIPS = [
    ("Attack1_Slash", 0.00, 0.55, {"SwingWhoosh": 0.19, "Impact": 0.29}),
    ("Attack2_Backhand", 0.55, 1.10, {"SwingWhoosh": 0.72, "Impact": 0.82}),
    ("Attack3_Uppercut", 1.10, 1.65, {"SwingWhoosh": 1.27, "Impact": 1.37}),
    ("Attack4_OverheadChop", 1.65, 2.45, {"SwingWhoosh": 1.90, "Impact": 2.02}),
]


def slerp_vectors(a, b, t, detour):
    """Spherical blend between unit vectors. When they are nearly opposite
    (a backhand reversing the swing), go round via `detour`, i.e. the wrist
    turns over instead of snapping through zero."""
    if a.dot(b) < -0.8:
        via = detour - a * detour.dot(a)
        if via.length < 1e-4:
            via = a.orthogonal()
        via.normalize()
        return slerp_vectors(a, via, t * 2.0, detour) if t < 0.5 else slerp_vectors(via, b, t * 2.0 - 1.0, detour)
    omega = math.acos(min(max(a.dot(b), -1.0), 1.0))
    if omega < 1e-4:
        return a.copy()
    return (a * math.sin((1.0 - t) * omega) + b * math.sin(t * omega)) / math.sin(omega)


def solve_wrist_roll(rig, view_layer, spline, total):
    """Choose the hand's up-axis (the axe-head side, i.e. the cutting edge)
    for every frame of the combo loop. At each Impact the edge points along
    the strike's travel, so chops and slices land edge-first. Between hits
    the edge turns gradually toward the NEXT strike's direction, so during a
    wind-up the back of the blade leads, as in a real swing. Everything is
    smoothed cyclically: no wrist spin, and Attack4 -> Attack1 stays seamless."""
    hand = rig.pose.bones["RightHand"]
    lower = rig.pose.bones["RightLowerArm"]
    dirs, elbows = [], []
    for frame in range(total):
        apply_pose(rig, view_layer, spline.sample(frame / FPS))
        dirs.append(hand.matrix.col[2].xyz.normalized())
        elbows.append((lower.head - hand.head).normalized())

    impacts = [frames(markers["Impact"]) % total for _, _, _, markers in COMBO_CLIPS]
    # Each strike sweeps the weapon around an axis (the swing-plane normal).
    # "Edge leads" means the edge points along axis x weapon at every frame,
    # which is always perpendicular to the weapon and never collapses mid-arc.
    axes = []
    for f in impacts:
        velocity = dirs[(f + 1) % total] - dirs[f - 1]
        axes.append(dirs[f].cross(velocity).normalized())

    hints = []
    for frame in range(total):
        # Most recent impact n at or before this frame (cyclic) and the next one.
        n = max(range(len(impacts)), key=lambda i: -((frame - impacts[i]) % total))
        m = (n + 1) % len(impacts)
        span = (impacts[m] - impacts[n]) % total or total
        s = ((frame - impacts[n]) % total) / span
        t = min(max((s - 0.3) / 0.45, 0.0), 1.0)  # hold through follow-through, turn before the next wind-up
        t = t * t * (3.0 - 2.0 * t)
        axis = slerp_vectors(axes[n], axes[m], t, elbows[frame])
        hints.append(axis.cross(dirs[frame]) + elbows[frame] * 0.15)

    radius = int(round(0.08 * FPS))  # 80 ms cyclic gaussian
    kernel = [math.exp(-0.5 * (i / (radius / 2.0)) ** 2) for i in range(-radius, radius + 1)]
    ups = []
    for frame in range(total):
        acc = Vector()
        for offset, k in zip(range(-radius, radius + 1), kernel):
            acc += hints[(frame + offset) % total] * k
        d = dirs[frame]
        up = acc - d * acc.dot(d)
        if up.length < 1e-3:
            up = elbows[frame] - d * elbows[frame].dot(d)
        ups.append(up.normalized())
    log("Wrist roll solved over %d frames (edge leads each strike)" % total)
    return ups


def bake_combo(rig, view_layer):
    spline = PoseSpline(COMBO_KEYS, cyclic=True)
    total = frames(COMBO_KEYS[-1][0])
    hand_up = solve_wrist_roll(rig, view_layer, spline, total)

    def combo_pose(frame):
        pose = spline.sample(frame / FPS)
        pose["hand_up"] = hand_up[frame % total]
        return pose

    attack_bones = UPPER_BODY if CHOP_UPPER_BODY_ONLY else FULL_BODY
    actions = []
    for name, start, end, markers in COMBO_CLIPS:
        start_frame, end_frame = frames(start), frames(end)
        actions.append(bake_action(
            rig, view_layer, name, end_frame - start_frame,
            lambda f, s=start_frame: combo_pose(s + f),
            attack_bones, cyclic=False,
            markers={m: frames(t) - start_frame for m, t in markers.items()},
        ))

    def bake_preview():
        # Baked after export so the bundle FBX never picks it up.
        return bake_action(rig, view_layer, "Combo_FullLoop", total, combo_pose, FULL_BODY, cyclic=True)

    return actions, bake_preview


# ---------------------------------------------------------------------------
# Idle_Weapon_Shoulder (2.8 s loop): shaft resting on the right shoulder
# ---------------------------------------------------------------------------
IDLE_SECONDS = 2.8


def idle_pose(frame, frame_count):
    phase = 2.0 * math.pi * frame / frame_count
    breath = ease_in_out_sine((1.0 - math.cos(phase)) / 2.0)  # 0 exhaled -> 1 inhaled mid-loop
    shift = math.sin(phase)  # slow weight shift between the feet
    head_lag = math.sin(phase - 0.7)
    sway = elastic_wave(phase, lag=0.9)

    hip_roll = 4.0 + 1.5 * shift  # cocked hip
    right_leg_roll, left_leg_roll = -13.0, 5.0  # wide stance after the hip tilt
    knee_flex = 1.5 * breath

    def shoulder_rest(rig):
        # Aim the shaft from the grip through a point just above and behind the
        # right shoulder, so it lies on the shoulder with the head behind it.
        bones = rig.pose.bones
        rest_point = bones["RightUpperArm"].head + char_offset(0.3, 0.6 + 0.02 * sway, -0.45)
        return (rest_point - bones[WEAPON_BONE_NAME].head).normalized()

    return {
        "bones": B(
            LowerTorso=((2.0, -10.0 + 2.0 * shift, hip_roll), (0.08 * shift, -0.08 - 0.02 * breath, 0.0)),
            UpperTorso=(4.0 - 2.5 * breath, 8.0 - 1.5 * shift, -3.0 - 1.0 * shift + 0.6 * breath),
            Head=(-2.0 + 1.5 * head_lag, -6.0 + 2.0 * math.sin(phase - 1.1), 1.0 * shift),
            LeftUpperArm=(-6.0 + 2.0 * breath, 0.0, 12.0 + 2.0 * breath),
            LeftLowerArm=(-20.0 - 3.0 * breath, 0.0, 0.0),
            LeftHand=(6.0 + 2.0 * sway, 0.0, 0.0),
            RightUpperLeg=(-12.0 - 0.75 * knee_flex, 0.0, right_leg_roll),
            RightLowerLeg=(18.0 + knee_flex + 2.0 * max(0.0, -shift), 0.0, 0.0),
            RightFoot=(-8.0 - 0.75 * knee_flex, 0.0, -(hip_roll + right_leg_roll)),
            LeftUpperLeg=(-10.0 - 0.75 * knee_flex, 0.0, left_leg_roll),
            LeftLowerLeg=(14.0 + knee_flex + 2.0 * max(0.0, shift), 0.0, 0.0),
            LeftFoot=(-8.0 - 0.75 * knee_flex, 0.0, -(hip_roll + left_leg_roll)),
        ),
        # Hand holds the handle in front of the chest; it rides up with each breath.
        "hand": (0.45, -1.0 + 0.04 * breath, 0.9 + 0.02 * sway),
        "pole": (-0.8, -1.0, -0.3),
        "weapon": shoulder_rest,
    }


def bake_idle(rig, view_layer):
    count = frames(IDLE_SECONDS)
    return bake_action(rig, view_layer, "Idle_Weapon_Shoulder", count,
                       lambda f: idle_pose(f, count), FULL_BODY, cyclic=True)


# ---------------------------------------------------------------------------
# Run_Weapon_Drag (0.70 s loop): deep lean, weapon dragged behind
# Right foot contact at 0, left at 0.35 s.
# ---------------------------------------------------------------------------
RUN_SECONDS = 0.70


def run_leg(phase, side):
    """side = 0 right, pi left. Returns hip, knee, ankle pitch."""
    t = phase + side
    hip = -24.0 - 46.0 * math.cos(t)  # baseline cancels the pelvis lean
    swing = max(0.0, -math.sin(t)) ** 1.1  # leg travelling forward through the air
    absorb = max(0.0, math.sin(t)) * max(0.0, math.cos(t))  # knee gives just after contact
    knee = 16.0 + 100.0 * swing + 30.0 * absorb
    ankle = 16.0 * math.sin(t) - 0.3 * knee
    return hip, knee, ankle


def run_pose(frame, frame_count):
    phase = 2.0 * math.pi * frame / frame_count
    lift = bounce(phase, lag=0.35)  # body rises mid-stride, drops hard on contact
    r_hip, r_knee, r_ankle = run_leg(phase, 0.0)
    l_hip, l_knee, l_ankle = run_leg(phase, math.pi)

    def drag_direction(rig):
        # Aim the weapon so its tip lands on the floor behind and to the right.
        grip = rig.pose.bones[WEAPON_BONE_NAME].head
        height = grip.z - 0.1
        length = WEAPON_DRAG_LENGTH
        wobble = 0.08 * math.sin(2.0 * phase - 1.2)
        back = Vector((-0.28 + wobble, 1.0, 0.0)).normalized()  # +Y = behind, -X = right
        if height >= length:
            return Vector((0.0, 0.2, -1.0)).normalized()
        reach = math.sqrt(length * length - height * height)
        tip = Vector((grip.x + back.x * reach, grip.y + back.y * reach, 0.1))
        return (tip - grip).normalized()

    return {
        "bones": B(
            # ~45 degrees of total forward lean between pelvis and chest.
            LowerTorso=((20.0 + 3.0 * math.cos(2.0 * phase - 0.6), 9.0 * math.cos(phase), 3.0 * math.sin(phase)),
                        (0.0, -0.37 + 0.22 * lift, 0.0)),
            UpperTorso=(24.0 + 5.0 * math.cos(2.0 * phase - 0.9), -12.0 * math.cos(phase), -2.0 * math.sin(phase)),
            Head=(-36.0 - 4.0 * math.cos(2.0 * phase - 1.3), 4.0 * math.cos(phase), 0.0),
            # Free arm pumps hard, opposite the left leg; the forearm trails the upper arm.
            LeftUpperArm=(-15.0 - 58.0 * math.cos(phase), 0.0, 12.0),
            LeftLowerArm=(-80.0 - 18.0 * math.cos(phase - 0.5), 0.0, 0.0),
            LeftHand=(8.0 * math.sin(phase - 0.9), 0.0, 0.0),
            RightUpperLeg=(r_hip, 0.0, -3.0),
            RightLowerLeg=(r_knee, 0.0, 0.0),
            RightFoot=(r_ankle, 0.0, 3.0),
            LeftUpperLeg=(l_hip, 0.0, 3.0),
            LeftLowerLeg=(l_knee, 0.0, 0.0),
            LeftFoot=(l_ankle, 0.0, -3.0),
        ),
        # Weapon arm hangs back and slightly out, bobbing a beat behind the body.
        "hand": (-0.3, -1.2 + 0.06 * math.sin(2.0 * phase - 1.6), -0.7 + 0.08 * math.cos(2.0 * phase - 1.6)),
        "pole": (-0.6, 0.2, 1.0),
        "weapon": drag_direction,
    }


def bake_run(rig, view_layer):
    count = frames(RUN_SECONDS)
    count += count % 2  # even frame count so the two strides are identical
    return bake_action(rig, view_layer, "Run_Weapon_Drag", count,
                       lambda f: run_pose(f, count), FULL_BODY, cyclic=True)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def reset_pose(rig):
    for pose_bone in rig.pose.bones:
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pose_bone.rotation_euler = (0.0, 0.0, 0.0)
        pose_bone.scale = (1.0, 1.0, 1.0)


def export_fbx(scene, rig, filepath, all_actions):
    view_layer = scene.view_layers[0]
    for obj in view_layer.objects:
        obj.select_set(False, view_layer=view_layer)
    rig.select_set(True, view_layer=view_layer)
    view_layer.objects.active = rig

    with scene_override(scene, active=rig, selected=[rig]):
        bpy.ops.export_scene.fbx(
            filepath=filepath,
            use_selection=True,
            object_types={"ARMATURE"},
            global_scale=EXPORT_SCALE,
            apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_NONE",
            axis_forward=EXPORT_AXIS_FORWARD,
            axis_up=EXPORT_AXIS_UP,
            add_leaf_bones=False,
            primary_bone_axis="Y",
            secondary_bone_axis="X",
            use_armature_deform_only=False,
            armature_nodetype="NULL",
            bake_anim=True,
            # Only bones that move get curves, so the upper-body attacks never pin the legs.
            bake_anim_use_all_bones=False,
            bake_anim_use_nla_strips=False,
            bake_anim_use_all_actions=all_actions,
            bake_anim_force_startend_keying=True,
            bake_anim_step=1.0,
            bake_anim_simplify_factor=0.0,  # keep the impact snap; no curve simplification
        )
    log("Exported %s" % filepath)


def export_all(scene, rig, actions):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for action in actions:
        reset_pose(rig)  # bones the action doesn't key must sit at rest, not at a leftover pose
        rig.animation_data.action = action
        scene.frame_start = int(action.frame_start)
        scene.frame_end = int(action.frame_end)
        export_fbx(scene, rig, os.path.join(OUTPUT_DIR, action.name + ".fbx"), all_actions=False)

    reset_pose(rig)
    export_fbx(scene, rig, os.path.join(OUTPUT_DIR, ASSET_NAME + "_Bundle.fbx"), all_actions=True)

    events = {}
    for action in actions:
        events[action.name] = {
            "frame_start": int(action.frame_start),
            "frame_end": int(action.frame_end),
            "seconds": round((action.frame_end - action.frame_start) / FPS, 4),
            "looped": bool(action.use_cyclic),
            "markers": {m.name: {"frame": m.frame, "seconds": round(m.frame / FPS, 4)}
                        for m in action.pose_markers},
        }
    with open(os.path.join(OUTPUT_DIR, "AnimationEvents.json"), "w") as handle:
        json.dump({"fps": FPS, "combo_order": [c[0] for c in COMBO_CLIPS], "actions": events}, handle, indent=2)
    log("Wrote AnimationEvents.json")


def remove_stale_exports():
    """Delete FBX files from older runs whose clips no longer exist."""
    if not os.path.isdir(OUTPUT_DIR):
        return
    for stale in ("Weapon_Chop_Heavy.fbx", "Idle_Weapon_Guard.fbx", "Run_Weapon_Forward.fbx"):
        path = os.path.join(OUTPUT_DIR, stale)
        if os.path.exists(path):
            os.remove(path)
            log("Removed stale %s" % stale)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log("Blender %s - building %s" % (bpy.app.version_string, ASSET_NAME))
    purge_previous_build()
    scene, coll = make_scene()
    view_layer = scene.view_layers[0]

    rig = build_rig(scene, coll)
    if BUILD_PROXY_MESH:
        build_proxy(coll, rig)

    attacks, bake_preview = bake_combo(rig, view_layer)
    actions = attacks + [bake_idle(rig, view_layer), bake_run(rig, view_layer)]
    blend_path = os.path.join(OUTPUT_DIR, ASSET_NAME + ".blend")

    # Save first: Blender can crash after heavy ops, and the .blend is the source of truth.
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    flush_log()
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=True)

    remove_stale_exports()
    export_all(scene, rig, actions)

    # Leave the whole combo loop on the rig so it previews straight away.
    preview = bake_preview()
    reset_pose(rig)
    rig.animation_data.action = preview
    scene.frame_start, scene.frame_end = 0, int(preview.frame_end)
    scene.frame_set(0)
    flush_log()
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=True)
    log("Done. Output: %s" % OUTPUT_DIR)


try:
    main()
except Exception:
    log("FAILED:\n" + traceback.format_exc())
    raise
finally:
    flush_log()
