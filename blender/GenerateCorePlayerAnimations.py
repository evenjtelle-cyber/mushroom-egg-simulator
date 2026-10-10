"""
GenerateCorePlayerAnimations.py  -  Blender 4.x
"+1 Chop Mushrooms for Eggs": core player motion suite

Builds an R15 skeleton (bones named after the R15 parts, one bone per
Motor6D) with a weapon bone under RightHand. It then bakes three actions into
the Action Editor and exports them as FBX for Roblox Studio's Animation Editor.

    Weapon_Chop_Heavy   0-18  @30fps  markers SwingWhoosh @5, Impact @8
    Idle_Weapon_Guard   0-24  @30fps  seamless loop
    Run_Weapon_Forward  0-16  @30fps  seamless loop (right contact 0, left contact 8)

Run it: paste into Blender's Text Editor and press Alt+P, or run headless:
    blender --background --python GenerateCorePlayerAnimations.py

Output goes to ~/Documents/CorePlayerAnimations/:
    CorePlayerAnimations_Bundle.fbx  all three actions as separate takes
    Weapon_Chop_Heavy.fbx etc.       one clip per file (Animation Editor imports one clip at a time)
    AnimationEvents.json             marker times in frames and seconds
    CorePlayerAnimations.blend       the rig plus the actions, to tweak and re-run

Conventions (all bones point +Z with zero roll, so every pose channel is in
character space):
    +X = character's left, -Y = character's forward, +Z = up. 1 Blender unit = 1 stud.
    rot = (pitch, yaw, roll) in degrees
        pitch +  : head/torso lean forward, a hanging limb swings backward
        yaw   +  : turn to the character's left
        roll  +  : tilt toward the character's left (+X)
    loc = (left, up, forward) in studs

Notes for Roblox:
  * Roblox poses are CFrames only, so the idle "squash" is done with
    translation (chest rises and settles, shoulders lift) and not with bone scale.
  * The chop keys only the Waist and the joints above it by default, so a swing
    layered over the run keeps the legs running. Set CHOP_UPPER_BODY_ONLY = False
    for a planted full-body chop.
  * Blender markers are not carried into Roblox by FBX import. Add them in the
    Animation Editor as Animation Events at the times in AnimationEvents.json.
    AnimationConfig also has timed fallbacks for them.
  * The weapon bone is named "Handle" because Roblox matches poses to parts by
    name. It only animates in-game if a Motor6D joins RightHand to the Tool's
    Handle. Otherwise the weapon simply follows the hand through RightGrip.
"""

import json
import math
import os
import traceback

import bpy  # noqa: I001  (bpy first: bmesh/mathutils need it loaded when run outside Blender's UI)
import bmesh
from mathutils import Matrix

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

FPS = 30
WEAPON_BONE_NAME = "Handle"
CHOP_UPPER_BODY_ONLY = True
BUILD_PROXY_MESH = True  # blocky R15 preview body + axe, skinned to the rig (not exported)

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
# Easing (shapes the keys; Blender's matching interpolation modes are used
# on the chop so the curves stay editable in the Graph Editor)
# ---------------------------------------------------------------------------
def ease_in_out_sine(x):
    return -(math.cos(math.pi * x) - 1.0) / 2.0


def ease_out_back(x, overshoot=1.70158):
    c3 = overshoot + 1.0
    return 1.0 + c3 * (x - 1.0) ** 3 + overshoot * (x - 1.0) ** 2


def elastic_wave(phase, lag, harmonic=0.22):
    """Periodic sway that trails the driver by `lag` radians, with a second
    harmonic so it snaps past centre and settles like a spring."""
    return math.sin(phase - lag) + harmonic * math.sin(2.0 * phase - 1.8 * lag)


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
    # Axe: with the arm hanging, a Roblox Tool on the standard grip points forward (-Y).
    (WEAPON_BONE_NAME, (-1.5, -1.6, 2.45), (0.25, 3.8, 0.25)),
    (WEAPON_BONE_NAME, (-1.5, -3.2, 2.85), (0.2, 0.9, 1.1)),
]


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------
def purge_previous_build():
    old_scene = bpy.data.scenes.get(SCENE_NAME)
    if old_scene is not None:
        for obj in list(old_scene.collection.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        if len(bpy.data.scenes) > 1:
            bpy.data.scenes.remove(old_scene)
    # Objects orphaned by earlier runs keep their names and would make ours ".001".
    for obj in list(bpy.data.objects):
        if obj.users_scene == () and obj.name.startswith((RIG_NAME, PROXY_NAME)):
            bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        if action.name.startswith(("Weapon_Chop_Heavy", "Idle_Weapon_Guard", "Run_Weapon_Forward")):
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

    if bpy.context.window is not None:
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
# Pose keying
# ---------------------------------------------------------------------------
ZERO = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def channel(pose, bone):
    rot, loc = ZERO
    if bone in pose:
        entry = pose[bone]
        rot = entry.get("rot", rot)
        loc = entry.get("loc", loc)
    return rot, loc


def mix_pose(a, b, t, bones):
    """Per-channel lerp. t outside 0..1 extrapolates (overshoot / coil)."""
    out = {}
    for bone in bones:
        rot_a, loc_a = channel(a, bone)
        rot_b, loc_b = channel(b, bone)
        out[bone] = {
            "rot": tuple(x + (y - x) * t for x, y in zip(rot_a, rot_b)),
            "loc": tuple(x + (y - x) * t for x, y in zip(loc_a, loc_b)),
        }
    return out


def reset_pose(rig):
    for pose_bone in rig.pose.bones:
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.rotation_euler = (0.0, 0.0, 0.0)
        pose_bone.scale = (1.0, 1.0, 1.0)


def key_pose(rig, frame, pose, bones):
    for bone in bones:
        rot, loc = channel(pose, bone)
        pose_bone = rig.pose.bones[bone]
        pose_bone.rotation_euler = tuple(math.radians(v) for v in rot)
        # Bone axes: X = world X, Y = world up, Z = world -Y (character forward).
        pose_bone.location = loc
        pose_bone.keyframe_insert("rotation_euler", frame=frame, group=bone)
        pose_bone.keyframe_insert("location", frame=frame, group=bone)


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


def new_action(rig, name, frame_end, cyclic):
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    action.use_frame_range = True
    action.frame_start = 0
    action.frame_end = frame_end
    action.use_cyclic = cyclic
    if rig.animation_data is None:
        rig.animation_data_create()
    rig.animation_data.action = action
    reset_pose(rig)
    return action


def set_interpolation(action, segments):
    """segments: {frame: (interpolation, easing, extras)} applied to the key
    that starts each segment. Frames not listed get LINEAR."""
    for fcurve in action_fcurves(action):
        for point in fcurve.keyframe_points:
            frame = int(round(point.co.x))
            interp, easing, extras = segments.get(frame, ("LINEAR", "AUTO", {}))
            point.interpolation = interp
            point.easing = easing
            for key, value in extras.items():
                setattr(point, key, value)
        fcurve.update()


# ---------------------------------------------------------------------------
# 1. Weapon_Chop_Heavy
# ---------------------------------------------------------------------------
CHOP_GUARD = {
    "LowerTorso": {"rot": (2, -4, 0)},
    "UpperTorso": {"rot": (6, -6, 0)},
    "Head": {"rot": (-4, 6, 0)},
    "RightUpperArm": {"rot": (-35, 0, -8)},
    "RightLowerArm": {"rot": (-55, 0, 0)},
    "RightHand": {"rot": (-10, 0, 0)},
    WEAPON_BONE_NAME: {"rot": (0, 0, 0)},
    "LeftUpperArm": {"rot": (-40, 0, -12)},
    "LeftLowerArm": {"rot": (-60, 0, 0)},
    "LeftHand": {"rot": (0, 0, 0)},
    "RightUpperLeg": {"rot": (-6, 0, -6)},
    "RightLowerLeg": {"rot": (12, 0, 0)},
    "RightFoot": {"rot": (-6, 0, 6)},
    "LeftUpperLeg": {"rot": (-10, 0, 6)},
    "LeftLowerLeg": {"rot": (16, 0, 0)},
    "LeftFoot": {"rot": (-6, 0, -6)},
}

# Anticipation: chest leans back and twists right, axe cocked overhead with the
# head hanging down behind the back.
CHOP_WINDUP = {
    "LowerTorso": {"rot": (-4, -10, 0), "loc": (0, 0.06, 0)},
    "UpperTorso": {"rot": (-14, -22, 4)},
    "Head": {"rot": (10, 14, 0)},
    "RightUpperArm": {"rot": (-160, 0, -12)},
    "RightLowerArm": {"rot": (-50, 0, 0)},
    "RightHand": {"rot": (-10, 0, 0)},
    WEAPON_BONE_NAME: {"rot": (-6, 0, 4)},
    "LeftUpperArm": {"rot": (-155, 0, -16)},
    "LeftLowerArm": {"rot": (-55, 0, 0)},
    "LeftHand": {"rot": (-10, 0, 0)},
    "RightUpperLeg": {"rot": (-4, 0, -6)},
    "RightLowerLeg": {"rot": (6, 0, 0)},
    "RightFoot": {"rot": (-2, 0, 6)},
    "LeftUpperLeg": {"rot": (-8, 0, 6)},
    "LeftLowerLeg": {"rot": (8, 0, 0)},
    "LeftFoot": {"rot": (0, 0, -6)},
}

# Contact: chest crunches forward over the hit, wrists snap so the axe head
# lands forward-and-down in front of the player.
CHOP_STRIKE = {
    "LowerTorso": {"rot": (8, 4, 0), "loc": (0, -0.28, 0)},
    "UpperTorso": {"rot": (30, 8, -2)},
    "Head": {"rot": (-18, -6, 0)},
    "RightUpperArm": {"rot": (-78, 0, -4)},
    "RightLowerArm": {"rot": (-6, 0, 0)},
    "RightHand": {"rot": (50, 0, 0)},
    WEAPON_BONE_NAME: {"rot": (40, 0, -3)},
    "LeftUpperArm": {"rot": (-72, 0, -18)},
    "LeftLowerArm": {"rot": (-10, 0, 0)},
    "LeftHand": {"rot": (40, 0, 0)},
    "RightUpperLeg": {"rot": (-30, 0, -8)},
    "RightLowerLeg": {"rot": (48, 0, 0)},
    "RightFoot": {"rot": (-26, 0, 8)},
    "LeftUpperLeg": {"rot": (-34, 0, 8)},
    "LeftLowerLeg": {"rot": (52, 0, 0)},
    "LeftFoot": {"rot": (-26, 0, -8)},
}

CHOP_FRAME_END = 18
CHOP_MARKERS = {"SwingWhoosh": 5, "Impact": 8}


def bake_chop(rig):
    bones = UPPER_BODY if CHOP_UPPER_BODY_ONLY else FULL_BODY
    action = new_action(rig, "Weapon_Chop_Heavy", CHOP_FRAME_END, cyclic=False)

    guard, windup, strike = CHOP_GUARD, CHOP_WINDUP, CHOP_STRIKE
    coil = mix_pose(guard, windup, 1.03, bones)  # wind-up keeps creeping back 3%
    overshoot = mix_pose(windup, strike, 1.05, bones)  # 5% past contact
    rebound = mix_pose(windup, strike, 0.98, bones)  # elastic bounce back up

    keys = [
        (0, guard),  # 0-4   fast pull-back (expo out: snaps away, eases into the hold)
        (4, windup),  # 4-5   coil hold
        (5, coil),  # 5-7   ultra-fast strike (expo in: slow start, violent finish)
        (7, strike),  # 7-8   contact
        (8, overshoot),  # 8     impact frame, 5% overshoot
        (11, rebound),  # 8-11  elastic settle; 11-18 back-eased follow-through to guard
        (CHOP_FRAME_END, guard),
    ]
    for frame, pose in keys:
        key_pose(rig, frame, pose, bones)

    set_interpolation(action, {
        0: ("EXPO", "EASE_OUT", {}),
        4: ("SINE", "EASE_IN_OUT", {}),
        5: ("EXPO", "EASE_IN", {}),
        7: ("LINEAR", "AUTO", {}),
        8: ("ELASTIC", "EASE_OUT", {"amplitude": 0.35, "period": 1.6}),
        11: ("BACK", "EASE_IN_OUT", {"back": 1.2}),
        CHOP_FRAME_END: ("LINEAR", "AUTO", {}),
    })

    for name, frame in CHOP_MARKERS.items():
        marker = action.pose_markers.new(name)
        marker.frame = frame

    log("Baked Weapon_Chop_Heavy: %d keys on %d bones, markers %s"
        % (len(keys), len(bones), CHOP_MARKERS))
    return action


# ---------------------------------------------------------------------------
# 2. Idle_Weapon_Guard (24-frame loop)
# ---------------------------------------------------------------------------
IDLE_FRAME_END = 24


def idle_pose(frame):
    phase = 2.0 * math.pi * frame / IDLE_FRAME_END
    breath = ease_in_out_sine((1.0 - math.cos(phase)) / 2.0)  # 0 exhaled -> 1 inhaled at frame 12
    sway = elastic_wave(phase, lag=0.9)  # weapon trails the chest
    head_lag = math.sin(phase - 0.6)

    hip_roll = 4.0  # cocked hip
    right_leg_roll, left_leg_roll = -13.0, 5.0  # wide stance after the hip tilt
    knee_flex = 1.5 * breath

    return {
        # Hips settle as the chest rises: squash and stretch through translation.
        "LowerTorso": {"rot": (2.0, -8.0, hip_roll), "loc": (0.0, -0.08 - 0.02 * breath, 0.0)},
        "UpperTorso": {"rot": (5.0 - 2.5 * breath, 6.0, -3.0 + 0.6 * breath), "loc": (0.0, 0.035 * breath, 0.0)},
        "Head": {"rot": (-3.0 + 1.5 * head_lag, -4.0, 0.0)},
        # Shoulders lift on the inhale.
        "RightUpperArm": {"rot": (-35.0 + 2.0 * breath, 0.0, -8.0 - 1.5 * breath), "loc": (0.0, 0.03 * breath, 0.0)},
        "RightLowerArm": {"rot": (-55.0 + 1.5 * math.sin(phase - 0.5), 0.0, 0.0)},
        "RightHand": {"rot": (-10.0 + 2.0 * sway, 0.0, 0.0)},
        WEAPON_BONE_NAME: {"rot": (4.0 * sway, 2.0 * math.sin(phase - 1.0), 3.0 * elastic_wave(phase, lag=1.4))},
        "LeftUpperArm": {"rot": (-8.0 + 1.5 * breath, 0.0, 10.0 + 2.0 * breath), "loc": (0.0, 0.03 * breath, 0.0)},
        "LeftLowerArm": {"rot": (-22.0 - 2.0 * breath, 0.0, 0.0)},
        "LeftHand": {"rot": (5.0 + 1.5 * sway, 0.0, 0.0)},
        "RightUpperLeg": {"rot": (-14.0 - 0.75 * knee_flex, 0.0, right_leg_roll)},
        "RightLowerLeg": {"rot": (20.0 + knee_flex, 0.0, 0.0)},
        "RightFoot": {"rot": (-8.0 - 0.75 * knee_flex, 0.0, -(hip_roll + right_leg_roll))},
        "LeftUpperLeg": {"rot": (-10.0 - 0.75 * knee_flex, 0.0, left_leg_roll)},
        "LeftLowerLeg": {"rot": (16.0 + knee_flex, 0.0, 0.0)},
        "LeftFoot": {"rot": (-8.0 - 0.75 * knee_flex, 0.0, -(hip_roll + left_leg_roll))},
    }


def bake_idle(rig):
    action = new_action(rig, "Idle_Weapon_Guard", IDLE_FRAME_END, cyclic=True)
    for frame in range(IDLE_FRAME_END + 1):
        key_pose(rig, frame, idle_pose(frame), FULL_BODY)
    set_interpolation(action, {})
    log("Baked Idle_Weapon_Guard: %d frames" % (IDLE_FRAME_END + 1))
    return action


# ---------------------------------------------------------------------------
# 3. Run_Weapon_Forward (16-frame loop, right contact 0, left contact 8)
# ---------------------------------------------------------------------------
RUN_FRAME_END = 16


def run_leg(phase, side):
    """side = 0 right, pi left. Returns hip, knee, ankle pitch."""
    t = phase + side
    hip = -8.0 - 38.0 * math.cos(t)  # forward at contact
    swing = max(0.0, -math.sin(t)) ** 1.2  # leg travelling forward through the air
    absorb = max(0.0, math.sin(t)) * max(0.0, math.cos(t))  # knee gives just after contact
    knee = 14.0 + 80.0 * swing + 22.0 * absorb
    ankle = 14.0 * math.sin(t) - 0.3 * knee
    return hip, knee, ankle


def run_pose(frame):
    phase = 2.0 * math.pi * frame / RUN_FRAME_END
    # Lowest just after each contact (frames ~0.6 and ~8.6): the step dip.
    dip = 0.5 + 0.5 * math.cos(2.0 * phase - 0.5)
    r_hip, r_knee, r_ankle = run_leg(phase, 0.0)
    l_hip, l_knee, l_ankle = run_leg(phase, math.pi)

    return {
        "LowerTorso": {"rot": (8.0, 7.0 * math.cos(phase), 2.5 * math.sin(phase)),
                       "loc": (0.0, -0.22 - 0.12 * dip, 0.0)},
        "UpperTorso": {"rot": (12.0 + 2.5 * math.cos(2.0 * phase - 0.8), -10.0 * math.cos(phase), 0.0)},
        "Head": {"rot": (-14.0 - 1.5 * math.cos(2.0 * phase - 1.0), 3.0 * math.cos(phase), 0.0)},
        # Weapon arm holds the axe forward; each joint lags the one above it.
        "RightUpperArm": {"rot": (-40.0 + 5.0 * math.cos(2.0 * phase - 1.2), 0.0, -10.0)},
        "RightLowerArm": {"rot": (-50.0 + 6.0 * math.cos(2.0 * phase - 1.6), 0.0, 0.0)},
        "RightHand": {"rot": (-5.0 + 4.0 * math.cos(2.0 * phase - 2.0), 0.0, 0.0)},
        WEAPON_BONE_NAME: {"rot": (7.0 * elastic_wave(2.0 * phase, lag=2.2), 0.0,
                                   3.0 * elastic_wave(phase, lag=1.0))},
        # Free arm pumps opposite the left leg.
        "LeftUpperArm": {"rot": (-10.0 - 42.0 * math.cos(phase), 0.0, 8.0)},
        "LeftLowerArm": {"rot": (-65.0 - 10.0 * math.cos(phase), 0.0, 0.0)},
        "LeftHand": {"rot": (6.0 * math.cos(phase - 0.7), 0.0, 0.0)},
        "RightUpperLeg": {"rot": (r_hip, 0.0, 0.0)},
        "RightLowerLeg": {"rot": (r_knee, 0.0, 0.0)},
        "RightFoot": {"rot": (r_ankle, 0.0, 0.0)},
        "LeftUpperLeg": {"rot": (l_hip, 0.0, 0.0)},
        "LeftLowerLeg": {"rot": (l_knee, 0.0, 0.0)},
        "LeftFoot": {"rot": (l_ankle, 0.0, 0.0)},
    }


def bake_run(rig):
    action = new_action(rig, "Run_Weapon_Forward", RUN_FRAME_END, cyclic=True)
    for frame in range(RUN_FRAME_END + 1):
        key_pose(rig, frame, run_pose(frame), FULL_BODY)
    set_interpolation(action, {})
    log("Baked Run_Weapon_Forward: %d frames" % (RUN_FRAME_END + 1))
    return action


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def export_fbx(scene, rig, filepath, all_actions):
    view_layer = scene.view_layers[0]
    for obj in view_layer.objects:
        obj.select_set(False)
    rig.select_set(True)
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
            # Only bones that move get curves, so the upper-body chop never pins the legs.
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
        json.dump({"fps": FPS, "actions": events}, handle, indent=2)
    log("Wrote AnimationEvents.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log("Blender %s - building %s" % (bpy.app.version_string, ASSET_NAME))
    purge_previous_build()
    scene, coll = make_scene()

    rig = build_rig(scene, coll)
    if BUILD_PROXY_MESH:
        build_proxy(coll, rig)

    actions = [bake_chop(rig), bake_idle(rig), bake_run(rig)]

    # Save first: Blender can crash after heavy ops, and the .blend is the source of truth.
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    flush_log()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUTPUT_DIR, ASSET_NAME + ".blend"), copy=True)

    export_all(scene, rig, actions)

    # Leave the chop on the rig so it previews straight away.
    reset_pose(rig)
    rig.animation_data.action = actions[0]
    scene.frame_start, scene.frame_end = 0, CHOP_FRAME_END
    scene.frame_set(0)
    log("Done. Output: %s" % OUTPUT_DIR)


try:
    main()
except Exception:
    log("FAILED:\n" + traceback.format_exc())
    raise
finally:
    flush_log()
