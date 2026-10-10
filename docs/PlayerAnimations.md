# Player motion suite

| File | Roblox location | Type |
|---|---|---|
| `src/StarterPlayer/StarterPlayerScripts/AnimationController.lua` | `StarterPlayer.StarterPlayerScripts.AnimationController` | LocalScript |
| `src/ReplicatedStorage/AnimationConfig.lua` | `ReplicatedStorage.AnimationConfig` | ModuleScript |
| `blender/GenerateCorePlayerAnimations.py` | Blender 4.x Text Editor (Alt+P) | bpy script |

## Clips

| Clip | Length | What it is |
|---|---|---|
| `Attack1_Slash` | 0.55 s | Forehand diagonal slice, high right to low left |
| `Attack2_Backhand` | 0.55 s | Flat backhand slice, left to right |
| `Attack3_Uppercut` | 0.55 s | Rising slice, low right to overhead |
| `Attack4_OverheadChop` | 0.80 s | Two-handed overhead chop finisher (heaviest shake and hit-stop) |
| `Idle_Weapon_Shoulder` | 2.8 s loop | Wide stance with a cocked hip; the shaft rests on the right shoulder with the head behind |
| `Run_Weapon_Drag` | 0.7 s loop | About 45° forward lean and a bouncy stride; the blade tip drags on the floor behind |

The four attacks are cut from one continuous combo, so each hit ends exactly where the next one starts, in both pose and speed, and Attack4 flows back into Attack1. Clicking or holding chains them into a seamless loop. The mix of slices and chops works for both swords and axes; `WeaponTypeOverrides.<Type>.ComboSteps` reorders or trims the combo for a weapon type.

## Pipeline

1. Run `GenerateCorePlayerAnimations.py` in Blender. Output lands in `~/Documents/CorePlayerAnimations/`.
2. In Studio, open an R15 rig in the Animation Editor and use **Import → From FBX Animation** for each clip FBX. The bundle FBX has all clips as takes, for archiving and other tools.
3. Add Animation Events `SwingWhoosh` and `Impact` to each attack at the times in `AnimationEvents.json`; FBX does not carry Blender markers. Without these events, the controller fires them on timers instead.
4. The attacks key only the Waist and above, so the legs keep running or idling under a swing. If the import shows keyframes on `LowerTorso` or the legs, delete those tracks before publishing.
5. Turn on **Looping** for Idle and Run, then publish all six clips. Paste the asset ids into `AnimationConfig.Tracks`.
6. Give weapon Tools a `WeaponType` attribute and, optionally, `AttackSpeed` (1 = normal) and `Tier` (to set the particle colour).

The weapon's direction is baked into the RightHand rotation, so swings, the shoulder rest and the floor drag all read with Roblox's default `RightGrip` weld. The drag run is tuned for a grip-to-tip length of 4.5 studs (`WEAPON_DRAG_LENGTH`). Longer weapons dip slightly into the floor and shorter ones hover.

## Optional extras

- **`ReplicatedStorage.VFXLibrary`:** add `MushroomChunk`, `Sparkle` and `ShockwaveRing` texture ids to get the impact burst.
- **`SwingTrail`:** a Trail inside the Tool, switched on between SwingWhoosh and Impact.
- **`ReplicatedStorage.Remotes.ChopImpact`:** a RemoteEvent that the default Impact hook fires as `(tool, swingId)`. The server must validate it.
- **Animating the weapon bone (`Handle`) in-game:** the server needs to replace `RightGrip` with a Motor6D (Part0 = RightHand, Part1 = Handle, same C0/C1). Without it, the weapon follows the hand rigidly and the clips still play.
