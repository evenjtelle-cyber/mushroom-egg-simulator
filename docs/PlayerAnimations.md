# Player motion suite

| File | Roblox location | Type |
|---|---|---|
| `src/StarterPlayer/StarterPlayerScripts/AnimationController.lua` | `StarterPlayer.StarterPlayerScripts.AnimationController` | LocalScript |
| `src/ReplicatedStorage/AnimationConfig.lua` | `ReplicatedStorage.AnimationConfig` | ModuleScript |
| `blender/GenerateCorePlayerAnimations.py` | Blender 4.x Text Editor (Alt+P) | bpy script |

## Pipeline

1. Run `GenerateCorePlayerAnimations.py` in Blender. Output lands in `~/Documents/CorePlayerAnimations/`.
2. In Studio, open an R15 rig in the Animation Editor and choose **Import → From FBX Animation**. Import each of `Weapon_Chop_Heavy.fbx`, `Idle_Weapon_Guard.fbx` and `Run_Weapon_Forward.fbx`. The bundle FBX has all three as takes, for archiving and other tools.
3. On `Weapon_Chop_Heavy`, add Animation Events `SwingWhoosh` at 0.1667 s and `Impact` at 0.2667 s (see `AnimationEvents.json`). FBX does not carry Blender markers. Without these events, the controller fires them on timers instead.
4. The chop keys only the Waist and above, so the legs keep running under a swing. If the import shows keyframes on `LowerTorso` or the legs, delete those tracks before publishing.
5. Turn on **Looping** for Idle and Run, then publish all three. Paste the asset ids into `AnimationConfig.Tracks`.
6. Give weapon Tools a `WeaponType` attribute and, optionally, `AttackSpeed` (1 = normal) and `Tier` (to set the particle colour).

## Optional extras

- **`ReplicatedStorage.VFXLibrary`:** add `MushroomChunk`, `Sparkle` and `ShockwaveRing` texture ids to get the impact burst.
- **`SwingTrail`:** a Trail inside the Tool, switched on between SwingWhoosh and Impact.
- **`ReplicatedStorage.Remotes.ChopImpact`:** a RemoteEvent that the default Impact hook fires as `(tool, swingId)`. The server must validate it.
- **Animating the weapon bone (`Handle`) in-game:** the server needs to replace `RightGrip` with a Motor6D (Part0 = RightHand, Part1 = Handle, same C0/C1). Without it, the weapon follows the hand rigidly and the clips still play.
