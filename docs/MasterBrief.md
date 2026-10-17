# MASTER BRIEF v2: "+1 Chop Mushrooms for Eggs" (Roblox)

> Paste this whole document at the start of a new session. It replaces the first master brief.
> **What changed from v1:**
> - Creatures, eggs, dummies, mushrooms, props and VFX meshes use one **blocky stud style**. **Weapons are the exception:** they're **smooth and cartoony** (see 4d).
> - The references are now the assets built in this repo:
>   - Frostmane Wyrm, Frostmane Egg and the Frostmane VFX set;
>   - the Wood starter set: the Mossbark Hatchet, the Mossbark Egg and the Mosscap Toad;
>   - the 4-hit weapon combo, the shoulder idle and the drag run.
> - Sections 6–8 record the pipeline that was actually proven to work, including the Blender crash rules.

---

## 0. Your role
Act as Executive Roblox Game Designer, Lead Systems Engineer, Technical Artist (Blender), Animator, VFX Artist and UI Designer for my Roblox simulator **"+1 Chop Mushrooms for Eggs"**. It's heavily inspired by the core loop, UI layout and map progression of "+1 Chop Trees for Treasure".

**All visual assets are made in Blender**: models, textures, icons, UI art, animations, and all VFX textures, flipbooks and effect meshes. Roblox Studio is used to import them, assemble them, run the effects (ParticleEmitters, Beams, Trails, lights) and write the game code.
- When you have Blender and Studio access, build things directly.
- Otherwise, write Blender Python (`bpy`) generator scripts plus Luau scripts I can run.
- Commit everything to the repo (layout in section 8).

---

## 1. Core gameplay & progression
- **Core loop:** players chop giant mushrooms with axes and swords. Chopping gives **Strength** and drops **Eggs** on the floor, which players collect into their inventory.
- **Map:** a linear corridor track like "+1 Chop Trees for Treasure" (sloped grass paths, brick borders, river bridges). Zones follow the egg tiers: **Wood → Crystal → Lava → Void → Celestial**, then the cosmic **Nebula → Solar → Astral** eggs (Areas 6–7, planned). Further along means rarer eggs, stronger mushrooms and stronger monsters.
- **Inventory:** base capacity is **3 Eggs**. When full, players can't pick up more until they place eggs in plot incubators or sell them.
- **Hatching & plots:** players carry eggs to incubators on their private plot. Eggs hatch after a cooldown, or instantly for Robux.
- **Monsters:** eggs hatch into 3D monsters by weighted luck rolls.
  - Hatched monsters stay on the plot earning **passive Cash/sec**.
  - One monster can be equipped to follow the player, giving Strength and Luck multipliers.
  - A follower also gives a rarity bonus: extra **WalkSpeed** from +1 (Common) to +12 (Secret) and extra **Cash** from +5% to +150%. The table is `CreatureKit.FOLLOWER_BONUS`.
- **Eggs and monsters:** 12 eggs (Mossbark → Celestial, then the cosmic Nebula, Solar and Astral eggs) with 4 monsters each. The Astral Egg's **Infinity Wyrm** is a 1 in 10,000 Secret. Every stat (hatch odds, Cash/s, Strength and Luck multipliers, hatch time, sell price, drop areas) is in `ReplicatedStorage.BestiaryData`, generated from the `FAMILIES` table in `blender/GenerateBestiary.py`. Hatch odds are before Luck.
- **Index discovery reward:** unlocking a new monster in the Index grants a one-time Cash reward scaled by rarity.
- **Strength & levels:**
  - Clicking gives +Strength and +XP.
  - Better weapons from the physical "Choppers" shop raise Strength per click and mushroom damage.
  - AFK training dummies give passive Strength: 1 free dummy at spawn, plus Cash-locked dummies deeper in the map.
  - Auto-chopping mushrooms also gives passive Strength and XP.
- **Level-up lightbeam:** on level-up, a skyward pillar of light (a Blender-made beam mesh plus Blender particle textures) crashes down on the player with camera shake and a particle burst.
- **Rebirth / prestige:** resets Strength and Cash in exchange for permanent multipliers and Rare Aura Roll Tokens. Each rebirth needs a minimum level (Rebirth 1 = Level 50, Rebirth 2 = Level 120, Rebirth 3 = Level 250).

### 1a. Mushroom health & 3 shrinking stages (required)
Every mushroom has health and visibly shrinks as it's chopped:

| Stage | Health range | Model scale | Notes |
|---|---|---|---|
| 3 – Full | 100% → above 2/3 | 1.00 | Spawn size |
| 2 – Damaged | at or below 2/3 | 0.80 | Shrinks when crossing 2/3 |
| 1 – Critical | at or below 1/3 | 0.60 | Shrinks when crossing 1/3 |
| Broken | 0 | — | Break burst, then respawn |

- **Server-authoritative health.**
  - Model attributes: `MaxHealth`, `Health`, `Stage` (3/2/1), `RespawnTime`, `StrengthReward`, `EggDrop`.
  - Damage comes from the player's equipped weapon (`Damage` attribute) multiplied by upgrades.
- **Shrink transition:** when health crosses a threshold, tween the scale down with a squash-and-bounce, using Back/Elastic easing over ~0.35 s.
  - Use `Model:ScaleTo()` driven by a NumberValue tween.
  - Keep the base planted on the ground.
  - Add a burst of Blender-made mushroom chunk debris in the cap's colors.
- **Every hit:** a quick white hit-flash (Highlight fill for ~0.08 s), a slight wobble, chunk particles from `VFXLibrary`, and a floating `+X 💪` number.
  - Hits are driven by the weapon combo's `Impact` animation event (section 5.6).
- **At 0 health:**
  - The mushroom pops into Blender-modeled break chunks and drops its egg(s) and Strength.
  - It hides for `RespawnTime`, then pops back in at full size and full health with an elastic grow from ~0.2 to 1.0.
- **Health bar:** a small rounded BillboardGui over the mushroom with fill color by stage (green, then yellow, then red). It shows only while the mushroom is damaged or targeted.
- Build each mushroom as **one model scaled at runtime**. Do not make three separate models.

---

## 2. HUD, input feedback & UI
- **Bottom-left stack:**
  - **Cash**: the largest, boldest element, in a green dollar frame.
  - **Rebirths** above it.
  - **Inventory capacity** above that, e.g. `📦 3/3 Full`.
- **Click feedback:** a floating `+1 💪` (or `+X 💪`) near screen center with a random ±50 px offset. It floats up, scales up elastically and fades out over 0.6 s.
- **Top-right settings (cog):** a squircle gear button that opens a modal with:
  - a Music Volume slider (0–100%);
  - an SFX toggle, which sets `LocalPlayer:SetAttribute("SFXEnabled", bool)`;
  - a Reduced Motion toggle, which sets `ReducedMotion` and disables camera shake;
  - a Promo Code box with a Redeem button and success/fail animations.
- **Left sidebar** of squircle buttons, styled like the approved Shop button (section 5.8):
  - **Shop** (red basket): Robux purchases only.
  - **Rebirth** (red/blue arrows).
  - **Index** (green book).
  - **Invite** (orange friends).
  - **Pets/Inventory** (brown paw).
  - **Quests** (scroll).
- **UI style:**
  - Rounded squircle containers and thick black 2-part outlines.
  - Bold readable type (Fredoka One / Luckiest Guy style) and soft drop shadows.
  - High-contrast call-to-action buttons.
  - Elastic Spring/Tween popups.
- **All button icons and art are rendered in Blender** as cartoon 3D objects with thick black outlines (see 6.6).
  - Icons of game objects (eggs, monsters, weapons) are rendered from the **same blocky models** used in game.

## 3. Shops, leaderboards & auras (gameplay)
- **UI Shop (red basket):** Robux only (2x Cash, 2x Strength, Instant Hatch, OP Auto-Clicker, Luck Boosts).
- **Physical map shops:**
  1. **"Choppers":** buy choppers with Cash or Robux. There are 10, from the free Mossbark Hatchet to the Eclipse Glaive: axes, a sickle, swords, a scythe, a halberd and a glaive (5.4d). Stats are in `ReplicatedStorage.ChopperData`.
  2. **"Upgrades":** Max Inventory Capacity, Player Luck, Weapon Hitbox Range, Movement Speed.
  3. **"Auras" shrine:** spin for permanent auras for 100k Cash, or a Robux bypass.
- **Hub leaderboards** (3D, SurfaceGui, OrderedDataStore): Top Cash, Top Strength, Top Rebirths, Top Time Played.
- **Aura rarities:** Common, Uncommon, Rare, Epic, Legendary, Mythic, Divine, Secret (1 in 100,000+). Effects escalate:
  - Common to Rare: faint glow.
  - Mythic and Secret: screen flash, roll cutscene, camera shake, lightning arcs, footstep trails and an overhead title.
  - All aura VFX art comes from Blender (see 6.5).

---

## 4. Art direction: blocky creatures and world, smooth cartoon weapons

Everything **except weapons** (world props, mushrooms, monsters, eggs, dummies, VFX meshes) is built like the reference screenshots (the ice mammoth and the orca), i.e. like Roblox bricks. Weapons follow 4d instead.

- **Built from boxes.** Chunky, mostly axis-aligned slabs. Organic shapes come from many slabs, never from smooth sculpting.
- **Studs on every surface,** at a consistent density.
  - The default is the shared tiling **`StudOverlay`** texture: 1 tile = 0.5 stud, box-projected per slab so studs follow each slab.
  - Real geometry studs are only for large flat world-prop tops seen from far away, and only within the triangle budget.
- **Flat saturated plastic colors from a fixed palette.** Each color is its own mesh part (see 6.3). There's no painted or baked color texture.
- **Rounded masses are stacked cross-slab layers.** Each layer is 3 overlapping slabs (wide-flat, narrow-tall, square-ish), and every slab in a layer has a **different depth**, so no faces are coplanar.
- **Glow lives in separate parts:** translucent **Glass** crystals and membranes, and **Neon** eyes, cracks and seams. They're never painted onto plastic.
- **Silhouettes stay chunky and readable.** Details are added by layering more slabs, not by shrinking them.

### 4a. Complexity ladder
Complexity grows with the zone tier and the rarity. Early content is simple; end-game content is dense and layered like the Frostmane Wyrm.

| Level | Typical asset | Slab count | Must have |
|---|---|---|---|
| Simple | Wood tier, Common–Uncommon | 30–120 | Cross-slab body, 2–3 colors, studs, chunky eyes |
| Detailed | Crystal/Lava tier, Rare–Epic | 120–350 | + crystal clusters or glowing seams, segmented horns/tails, 4–6 colors |
| Complex | Void tier, Legendary–Mythic | 350–700 | + layered draped plates, wings or frills, 2 glow materials, idle VFX |
| End-game | Celestial tier, Divine–Secret | 700+ (≤ 20k tris per part) | Everything above, plus a banded **fur-slab coat**, segmented tusks/horns, translucent membrane wings, spine crystal spikes, a crystal-cluster tail, full idle VFX and a hatch sequence. Matches the **Frostmane Wyrm** |

### 4b. Construction vocabulary
These are the shapes to build with. The code is in `blender/GenerateFrostmaneSet.py`.

| Shape | What it is | Use it for |
|---|---|---|
| `box` | One slab with stud UVs; can taper toward one end | Everything |
| `blob` | A rounded mass of stacked cross-slab layers | Bodies, heads, legs, egg shells |
| `chain` | Overlapping segment boxes along a curve | Tusks, horns, tails, necks, wing spars, handles |
| `crystal` | A faceted hexagonal prism with a point | Spikes, crowns, clusters |
| `fur_plate` | A draped, slightly lifted, tapered slab, sometimes with a notched tip | Mammoth-style fur, manes, cuffs, frost caps, leaves, scales |
| Membrane tiles | Overlapping thin slabs filling the space between spars | Wings, frills, fins |
| Banded colour | Diagonal stripes plus noise, whiter toward the top | Coats and plates |

### 4c. Tier theme guide (colours in sRGB hex)

| Tier | Main body | Plates / fur | Glow parts (Glass/Neon) | VFX colours |
|---|---|---|---|---|
| Wood | Bark `#6B4A2B`, moss `#4F8A2E` | Leaf `#7CC242`, light leaf `#B5E36A`, rope `#C9A66B` | Spore glow `#B8FF7A` | Soft green spores |
| Crystal | Birch `#E8E2D4`, stone `#8C93A3` | Lilac `#C9B3FF`, deep `#7B5CD6` | Amethyst `#B48CFF`, quartz `#F2E9FF` | Lavender sparkles |
| Lava | Basalt `#2B2422`, char `#4A3A33` | Ember `#C2461B`, ash `#7A6E68` | Magma Neon `#FF7A1A`, `#FFC24A` | Orange embers, heat haze |
| Void | Void-stone `#1E1630`, bone `#E6E0D2` | Dusk `#3B2A5E`, plum `#6A3FA0` | Void glass `#9B5CFF`, wisp `#D7B8FF` | Purple wisps, dark smoke |
| Celestial | Sapphire `#23489E`, navy `#1C3F8F` | Fur white `#EEF5FF`, ice `#A9D3FF`, blue `#4C8FE6`, belly `#CFE6FF` | Crystal `#7FEAFF`, violet `#B48CFF`, eyes/cracks `#9CFFFF`/`#5FF4FF` | Cyan frost, violet accents |
| Nebula | Space `#1B1446`, nebula `#2E2A7A`, plum `#8E3FB8` | Pink `#FF7AC8`, white `#EEF5FF` | Nebula glass `#FF8FE0`, star glass `#7FEAFF`, stars `#FFF6D6` | Pink and cyan sparkles |
| Solar | Sun `#FF8A1F`, gold `#FFC93C`, flare red `#E8452C` | Bronze `#B8732A`, band `#7A2E10` | Flare Neon `#FFD84A`, white-hot `#FFF3B0`, flare glass `#FF5A1F` | Golden embers |
| Astral | Midnight `#120E2E`, indigo `#2A2370`, violet `#4B3AA0` | Starlight `#E9E6FF`, gold `#F3C64A` | Astral glass `#9C8CFF`, moon `#FFF1B8`, stars `#FFF6D6` | Gold-white glints, violet |

A tier's weapon, monster, egg and dummy share palette and motifs. For example, every Celestial asset has frost fur slabs, ice tusks and cyan crystals.

### 4d. Weapons: smooth cartoon hero style (the exception)
Weapons are **not** blocky. They look like hand-painted cartoon toys: the in-game root-and-ice axe the user showed as a reference, shaped like a classic stylised game axe. The built reference is the **Mossbark Hatchet** (5.4).
- **Soft, chunky, readable shapes.** Use smooth subdivided geometry: tubes along curves for hafts, wraps and rings; Coons-patch blades that are thick at the socket and thin at the edge; small spheres for rivets.
- **Hand-painted look, baked into one texture per part:**
  - painted base colours (vertex colours);
  - procedural detail: hammered steel dents, wood grain, leather grain, brass speckle;
  - ambient occlusion in the crevices;
  - a bright rim on convex edges;
  - a sharpened, bright cutting edge.
- **Materials tell the tier story.** Starters are steel, wood, leather and brass. Higher tiers swap in their elemental hero material (ice crystal, magma rock, void-stone) and add glow parts. The glow is always a separate Glass/Neon part, never painted.
- **Details that sell it:** worn edge chips, crossed leather wraps, brass collars and rivets, chain rings, pommel spikes and slightly curved hafts.
- **No studs on weapons.**

---

## 5. Approved references (match this quality and feel)

The first four references are **built** and live in the repo. Open their preview renders before making anything new:
- `docs/images/FrostmaneWyrm_front.jpg`
- `docs/images/FrostmaneWyrm_back.jpg`
- `docs/images/FrostmaneEgg.jpg`
- `docs/images/FrostmaneVFXMeshes.jpg`
- `docs/images/MossbarkHatchet.jpg`
- `docs/images/MossbarkEgg.jpg`
- `docs/images/MosscapToad.jpg`
- `docs/images/Bestiary_<Family>.jpg`: every other egg and monster, one sheet per egg family (5.4c)

### 5.1 Frostmane Wyrm: end-game monster (Celestial, Secret) ✅ built
- **Built by:** `blender/GenerateFrostmaneSet.py` → `FrostmaneWyrm.glb`.
- **Size:** about 19 studs tall and 33 long. The pivot is at ground level under the body; the head points toward Blender −Y.
- **Mammoth traits:**
  - a shaggy coat of about 300 draped fur slabs in diagonal white, ice, blue and navy bands;
  - a long hanging fringe along the lower flanks and a white chest bib;
  - curling segmented ice tusks from the jaw;
  - white fur cuffs on thick pillar legs, with white claws and crystal toes.
- **Dragon traits:**
  - a long raised neck with a white mane;
  - a long snout with a frosted brow, fangs and glowing cyan eyes;
  - swept-back segmented horns with crystal tips;
  - spiky cheek frills;
  - half-raised wings with navy spars and translucent ice-tile membranes;
  - cyan and violet crystal clusters down the spine;
  - a long tail with plates and crystals, ending in a 6-crystal cluster.
- **Parts:** 14 colour parts, about 19k triangles in total: Body, Belly, FurWhite, FurIce, FurBlue, FurNavy, Tusks, Claws, WingFrame, WingMembrane, Crystals, CrystalsViolet, Eyes, Mouth.
- **Sockets:** Mouth, Head, Chest, Spine, TailTip, WingTipL/R, FootFL/FR/BL/BR.
- **VFX (`FrostmaneVFX.StartWyrm`):** a Highlight and PointLight glow pulse, block sparkles from the wings, a shimmer rising off the spine, cold mist creeping from the feet, drifting blocky snowflakes, motes from the tail tip, and frost-breath flipbook puffs every few seconds.

### 5.2 Frostmane Egg: end-game egg (Celestial, Secret) ✅ built
- **Built by:** `GenerateFrostmaneSet.py` → `FrostmaneEgg.glb`.
- **Size:** about 6.5 studs tall.
- **Shell:** 13 stacked cross-slab layers in alternating navy and blue bands.
- **Frost cap:** three rings of draped white and ice slabs.
- **Cracks:** three branching zig-zag seams in Neon cyan.
- **Crown:** a 6-crystal cluster in cyan and violet.
- **Nest:** a blocky ring of ice rock with a snow trim and jutting crystals, plus two segmented tusks spiralling up around the egg.
- **Parts:**
  - The egg-shell group spins and bobs on an `EggCore` part: Shell, ShellBlue, Frost, FrostIce, Cracks, Crown, CrownViolet.
  - The nest group stays still: Nest, NestLight, NestSnow, NestCrystals, NestViolet, NestTusks.
- **Sockets:** EggCenter, Crown, NestRim.
- **Label (BillboardGui):**
  - Egg name on top: white Fredoka One with a dark outline.
  - Rarity underneath: a vertical gradient (icy cyan to violet for Celestial/Secret).
  - An optional green price line.
- **VFX:**
  - `StartEgg`: spin and bob, crown sparkles, crack pulse, rising frost motes, glow.
  - `PlayHatch`:
    - a wobble that builds over 1.5 s while the cracks blaze;
    - a white flash, then a burst of shell shards, a crystal burst and an ice nova ring;
    - snowflakes, glints, ice shards and a shockwave;
    - an `onReveal(centre)` callback to spawn the monster.

### 5.3 Frostmane VFX set ✅ built
- **Textures** (white RGB with the shape in alpha; written by numpy in Blender):
  - SoftGlow, FrostMote, Sparkle, IceShard, ShockwaveRing, FrostMist, MushroomChunk;
  - **BlockSparkle** and **BlockSnowflake**, pixel-art drawn on a 16×16 grid so they match the stud style;
  - FrostStreak, a 256×64 trail strip;
  - StudOverlay, a 128 px stud tile in Overlay format.
- **Flipbook:** `FrostBreathFlipbook`, 4×4 at 1024², frame 0 top-left, rendered in Cycles from a 4D-noise puff that swells and erodes.
- **Meshes** (`FrostmaneVFXMeshes.glb`): NovaRing (18 shards), CrystalBurst (22 radiating shards), Shard01–12 (blocky shell fragments in shell colours).
- **Rule for every future tier:** make the same family of effects in that tier's palette and motifs.
  - Wood: leaf and spore pixel sprites.
  - Lava: ember sprites and a magma-crack flipbook.
  - Void: wisp sprites and a smoke flipbook.

### 5.4 Mossbark Hatchet: starter axe (Wood, Common) ✅ built
- **Built by:** `blender/GenerateStarterSet.py` → `MossbarkHatchet.glb`, smooth cartoon style (4d).
- **Size:** about 4.6 studs long. The parts are `Handle` (the Tool handle) and `Head`, each with its own baked 1024² colour texture and 8–13k triangles.
- **Head:**
  - a bearded steel blade with soft hammered dents, a bright sharpened edge and two small edge chips;
  - a brass eye collar with darker rims and two rivets per cheek;
  - a rounded steel poll with a brass chain ring and a hanging link.
- **Handle:**
  - a slightly S-curved wooden haft with grain and a small knot;
  - crossed green leather wraps and a green band under the head;
  - a brass lower collar with a rivet, a brass pommel cap and a small curved pommel spike.
- **Sockets:** `Tip` becomes `TipAttachment` (where the impact burst plays); `TrailTop` and `TrailBottom` carry the `SwingTrail`.
- **Studio:** `StarterSet.MakeTool` builds the Tool:
  - grip at 0.95 studs up from the bottom of the handle, with a `GRIP_YAW_DEGREES` switch if the blade faces the wrong way;
  - attributes `WeaponType = "Axe"`, Damage, AttackSpeed and so on.
- **Every future weapon** follows this pipeline and shape language. Higher tiers swap the steel for the tier's elemental material, add glow parts and get bigger silhouettes.

### 5.4b Mossbark Egg and Mosscap Toad: Common examples (Wood) ✅ built
- **Built by:** `GenerateStarterSet.py` → `MossbarkEgg.glb` and `MosscapToad.glb`.
- **They mark the bottom of the complexity ladder:**
  - Mossbark Egg: about 1.2k triangles, 8 parts.
  - Mosscap Toad: about 2.7k triangles, 10 parts.
- **Mossbark Egg:** a bark-brown banded shell, a draping moss-leaf cap, a sprout on top and a tiny red mushroom growing on its side, sitting straight on the ground (no nest).
- **Mosscap Toad:**
  - a chubby moss-green toad with big eyes, blushing cheeks and a smile;
  - folded legs and toes, and moss tufts down its back;
  - a red Amanita cap with white warts, which ties it to the Zone 1 mushroom.
- **Effects:**
  - Toad: idle hops with a landing squash and a dust puff, plus drifting spores.
  - Egg: rocks side to side on the ground (pivoting at its base), falling leaves, sprout spores, and a "Common" label.
  - Hatch: a wobble, then shell shards, a leaf burst and dust.
- **Studio:** `StarterSet.lua` (`Assemble`, `StartToad`, `StartEgg`, `PlayHatch`, `ResetEgg`).

### 5.4d Choppers: all 10 weapons ✅ built
- **Built by:** `GenerateChoppers.py` → `Choppers.glb` (the nine after the starter axe), `ChopperData.lua` and previews (`docs/images/Choppers_Lineup.jpg`). Same smooth, baked, hand-painted pipeline as the Mossbark Hatchet (4d).

  | # | Chopper | Tier | Type | Strength/hit | Cash | Robux | Signature details |
  |---|---|---|---|---|---|---|---|
  | 1 | Mossbark Hatchet | Wood | Axe | +1 | Free | – | 5.4 |
  | 2 | Stonebark Hatchet | Wood | Axe | +5 | $500 | 15 | Knapped stone head, rope lashing, bent branch with leaves |
  | 3 | Fernleaf Sickle | Wood | Sickle | +20 | $15K | 29 | Crescent blade, fern frond along the spine |
  | 4 | Amethyst Chopper | Crystal | Sword | +60 | $250K | 49 | Cleaver-sword, amethyst fuller, crystal spine (Glass) |
  | 5 | Magmaseam Axe | Lava | Axe | +600 | $50M | 99 | Double-bitted basalt, magma seams and edges (Neon) |
  | 6 | Voidglass Reaver | Void | Sword | +5,000 | $10B | 199 | Hooked void-stone blade, bone hilt, void orb, rune dots |
  | 7 | Frostroot Cleaver | Celestial | Axe | +25,000 | $1T | 399 | Ice cleaver, twisted-root haft, fur cuff, rune circle |
  | 8 | Stardust Scythe | Nebula | Scythe | +150,000 | $80T | 599 | Nebula gradient blade with stars, pink gems |
  | 9 | Sunburst Halberd | Solar | Halberd | +900,000 | $5Qa | 799 | Gilded axe and spear, glowing sun disc, flame tassels |
  | 10 | Eclipse Glaive | Astral | Glaive | +5,000,000 | $300Qa | 999 | Twin moon blades, two eclipse rings at the grip |

  Rows 3, 8, 9 and 10 were added to reach 10 and their numbers are placeholders.
- **Parts:** `Handle` and `Head` (baked texture each), plus a flat `Glow` (Neon) and/or `Crystal` (Glass) part from the Crystal tier up. Every chopper is 10k–22k triangles.
- **Studio:** `ChopperKit.lua` (`SetupAll`, `MakeTool`, `ShopList`, `GiveTool`) and `ChopperDemo.lua`. Tools get a tier-coloured swing trail, tier sparkles (Crystal+) and a light on the Glow part (Lava+).

### 5.4c Bestiary: every other egg and monster ✅ built
- **Built by:** `GenerateBestiary.py` → one `Family_<Egg>.glb` per egg family, `BestiaryVFXMeshes.glb` (white hatch shards) and `BestiaryData.lua`.
- **10 eggs and 46 monsters:**

  | Egg | Monsters (most common first) |
  |---|---|
  | Mossbark (5.4b) | Mosscap Toad (5.4b), Twigroot Boar, Barkhorn Stag, Oakheart Golem |
  | Fernleaf | Fernling Snail, Leafwing Beetle, Thornback Hedgehog, Elderfern Treant |
  | Toadstool | Spotcap Frog, Puffball Bunny, Sporecloak Fox, Toadstool Titan |
  | Crystal | Quartzpaw Kit, Amethyst Moth, Prismhorn Ram, Geodeback Tortoise |
  | Geode | Shardling Mole, Druzy Lynx, Gemhorn Rhino, Prismatic Basilisk |
  | Lava | Cinderpaw Pup, Magmashell Crab, Emberwing Drake, Obsidian Colossus |
  | Obsidian | Ashen Imp, Slagback Boar, Basalt Wyvern, Molten Behemoth |
  | Void | Voidmote Wisp, Gloomfang Wolf, Nullhorn Beast, Abyssbone Leviathan |
  | Celestial = Frostmane Egg (5.2) | Starfrost Owl, Glacierhorn Elk, Frostroot Wyrmling, Frostmane Wyrm (5.1) |
  | Nebula | Nebula Jellyfish, Comet Fox, Starlight Pegasus, Galaxy Serpent |
  | Solar | Sunflare Salamander, Corona Lion, Solarflare Phoenix, Helios Colossus |
  | Astral | Astral Moth, Eclipse Panther, Cosmos Dragon, Infinity Wyrm (Secret, 1 in 10,000) |

  The Nebula, Solar and Astral stats are placeholders that continue the curve above Celestial (Areas 6–7); replace them in `FAMILIES`.

- **The complexity ladder (4a) in practice:**
  - Each family's most common monster is the plainest: a cute slab body, 2–3 colours, big eyes.
  - Each rarity step adds texture: spots, plates, fur coats, crystals, then Glass/Neon glow parts, wings and horns. Size grows with rarity too (`RARITY_SCALE`).
  - Eggs follow the same rule. Fernleaf is plainer than Mossbark; Obsidian and Void have gold rings, glowing seams and crystal crowns. Every egg sits straight on the ground.
  - Every asset is 0.8k–7.8k triangles in 4–18 parts. The Infinity Wyrm is the densest: a star-scaled body coiled into an infinity sign, crystal antlers, a glowing halo and rune bands. In-game its glow cycles through every colour.
- **Effects (`CreatureKit.lua`, all driven by `BestiaryData`):**
  - Monster idles from the data: `Hop`, `Hover` or `Breathe`.
  - Theme particles: spores, leaves, sparkles, glints, embers, void wisps or frost motes. The particle rate grows with rarity, Epic+ get a light, and Legendary+ get a glow Highlight.
  - Eggs rock on the ground and show a name, rarity and price label.
  - Hatch: a wobble, a flash, shards in the egg's own colours and a theme burst; Epic+ eggs add a shockwave.
- **Studio:** `CreatureKit.lua` (`Unpack`, `Assemble`, `StartMonster`, `StartEgg`, `PlayHatch`, `ResetEgg`, `RollHatch`, `FollowerBonus`) and `BestiaryDemo.lua`.

### 5.5 Amanita / fly agaric (Zone 1 mushroom), blocky stud style
- **Size:** about 10.6 studs wide and 16 tall. It should look slim and elegant, not chubby.
- **Cap:** a bright-red dome stacked from rounded cross-slab layers, deep crimson at the rim fading to bright red on top.
- **Warts:** about 38 square white warts, grid-aligned and sitting on the surface, spread over the top, shoulders and sides.
- **Underneath:** pale cream gills with fine radial lines.
- **Stem:** slim, white and slatted, with darker grooves and a drooping white skirt ring partway up.
- **Base:** a bulbous foot wrapped in ragged white volva scraps, on a small studded dark-brown dirt patch.
- **Other mushrooms** follow the same rules in their own species shape and colors, for example porcini, chanterelle and shiitake. Keep them slim; the stem is clearly narrower than the cap.
- The pivot is at the centre of the base, so the runtime `ScaleTo` shrink stays grounded.

### 5.6 Player weapon animations ✅ built
- **Built by:** `blender/GenerateCorePlayerAnimations.py` (an R15 rig at 60 fps).
- **Played by:** `AnimationController` and `AnimationConfig`.
- **Attack combo (Action2):** four hits cut from one continuous loop, so each hit ends exactly where the next begins and hit 4 flows back into hit 1.
  1. **Slash** (0.55 s): diagonal, high right to low left.
  2. **Backhand** (0.55 s): flat, left to right.
  3. **Uppercut** (0.55 s): rising, low right to overhead.
  4. **Overhead chop** (0.80 s): two-handed finisher.
- **How the combo is built:**
  - Arm joints are solved so the hand reaches its target, with the weapon aimed from the wrist.
  - The blade edge leads every strike.
  - Each hit has a 5% overshoot and an elastic settle.
  - Markers `SwingWhoosh` and `Impact` are on every hit; the finisher has a heavier impact weight.
  - Speed scales with the Tool's `AttackSpeed` attribute.
  - Clicks are buffered and holding repeats; the combo resets after 0.45 s idle.
  - On Impact: hit-stop, camera shake, a particle burst and audio.
- **Idle_Weapon_Shoulder** (2.8 s loop, Action): wide stance with a cocked hip; the hand is at the chest and the shaft rests on the right shoulder with the head behind; slow breathing.
- **Run_Weapon_Drag** (0.7 s loop, Movement): about 45° forward lean, a bouncy stride and a pumping free arm. The weapon arm hangs back with the **blade tip on the floor behind**. Speed scales with WalkSpeed.
- The weapon's direction is baked into **RightHand** (not the Handle bone), so it reads with the default `RightGrip` weld.

### 5.7 Frostcap Dummy: blocky spec (to build)
- **Shape:** a stud-style ice mushroom dummy, about 12.5 studs tall.
  - A slatted pale-lavender stem with deep-blue grooves.
  - A scalloped stepped cap in deep blue, with a white frost-slab top and icicle crystals around the rim.
  - A crystal crown, and crystal clusters at the base.
- **Training target:** a stepped-slab bullseye strapped to the stem with two navy slab bands.
- **Base:** a snow-slab mound.
- **Game data:** `IsAFKDummy`, `StrengthPerSecond`, `UnlockCost`, `Tier`, and a `HitPoint` socket on the target.

### 5.8 Shop button (UI reference for all sidebar buttons)
- **Shape:** a rounded square with a thick black outline and a dark-red 3D lip along the bottom.
- **Face:** a gradient from deep red at the top to bright red, then a white-pink band at the bottom.
- **Rays:** soft white light wedges radiate from the center behind the icon and turn slowly. They're clipped to the rounded corners, and the gradient lives on its own layer so it doesn't tint the rays.
- **Icon:** a cartoon 3D basket rendered in Blender (deep pink tiled walls, darker interior, rounded rim, chunky white handle and a thick black outline).
- **Feel:**
  - The icon bobs while idle.
  - Hovering grows the button to 1.1 with Back easing.
  - Pressing squashes it to 0.88, and releasing springs back with Elastic easing.
  - Clicking wiggles the icon and fires an `OpenShopRequested` event.
- **Size:** 72–124 px, square at any screen size.

---

## 6. Blender pipeline (proven rules)

### 6.1 General
- **Build procedurally with `bpy` generator scripts,** never by hand.
  - One script per asset family.
  - Each script is self-contained: copy the "Geometry builder" and "Shared motifs" sections from `GenerateFrostmaneSet.py`.
  - Scripts must run both from the Text Editor (Alt+P) and headless (`blender --background --python`).
- **Log and fail safely:**
  - Write a run log into a text block called `<Set>_Log`.
  - Wrap `main()` in try/except and log the traceback.
  - The last log line is `Done. Output: <folder>`.
- **Output:** `~/Documents/<SetName>/`, containing GLBs, `Textures/`, `Previews/`, the `.blend` and `<Set>_Manifest.json` (palette, per-part colour, triangle count, glow flag, socket positions).
- **Units:** 1 Blender unit = 1 stud.
- **Roblox limits:**
  - ≤ 20,000 triangles per part. Check it and add a Decimate step if over.
  - Textures at most 1024×1024.
- **Seeded randomness** (`random.Random(SEED)`), so a re-run gives the same model.

### 6.2 Crash-proof scene rules
These caused real crashes in Blender 4.2. Follow them every time.
1. **Use one work scene per script, with one collection per asset** (`<Asset>_Parts`). Never export GLBs from several scenes in one run: the glTF exporter switches the window's scene and crashes on the second one.
2. **Never give a collection the same name as a scene.** The exporter crashes.
3. **Never delete the scene that's on screen.** Reuse it and empty its collections instead.
4. **In `--background`, never assign `window.scene`.** The window is a stub there, so build in `bpy.context.scene`.
5. **Pass `view_layer=` to every `select_set()` call** and use `bpy.context.temp_override(...)` for operators.
6. **Name helper objects per asset** (`<Asset>_Cam`, `_Sun`, `_Ground`, `_World`) and reuse them, so re-runs don't create `.001` copies. Purge orphan data before rebuilding.
7. **Both scripts must survive two runs in a row in one session.** Test that before calling a script done.

### 6.3 Building assets
- **Each palette colour is its own mesh part,** named after its palette key (`FurWhite`, `Crystals`, ...). Part names must be unique across the whole set: for example `Tusks` on the monster and `NestTusks` on the egg.
- **UVs:** box-projected in each slab's own frame, × `STUDS_PER_UNIT` (2). This is what makes `StudOverlay` tile studs correctly.
- **No coplanar faces.** Give overlapping slabs different depths and offsets. Coplanar faces render as black patches in Cycles and z-fight in Roblox.
- **Sockets:** VFX anchor points are tiny tetra meshes named `Socket_<Name>`, exported with the model. Studio turns them into Attachments.
- **Pivots:**
  - Monsters, dummies and props: ground level under the centre of mass.
  - Eggs: the centre of the nest base.
  - Mushrooms: the centre of the base.
- **Facing:** the head points to Blender −Y. Keep a `FACE_POSITIVE_Y` switch, and check the facing after import.

### 6.4 Materials, preview and export
- **Preview material** = palette colour mixed with `StudOverlay` (RGB weighted by alpha). Glow parts get Principled emission, plus transmission for Glass-type parts.
- **The GLB gets flat palette materials,** swapped in just for export. glTF can't carry the preview texture mix, and the exporter crashed on it.
- **Preview renders:**
  - Cycles CPU, about 24 samples with denoise, `Standard` view transform, studded green ground.
  - Front-three-quarter and back views.
  - Raise `transparent_max_bounces` to 64 and `transmission_bounces` to 32, otherwise stacked glass renders black.
  - Blender looks frozen while rendering; that's normal. A `RENDER_PREVIEWS` switch skips rendering.
- **Verify every asset from its preview render** before calling it done: facing, proportions, black patches, washed-out glow and hidden details.

### 6.5 VFX
Effects run in Roblox as ParticleEmitters, Beams, Trails, Highlights and lights, but **every texture and mesh they use is made in Blender**. Never use Roblox's built-in particle textures.
- **Particle textures:** pure white RGB with the shape in the alpha channel, written with numpy (`save_rgba`). Make soft versions and **pixel-art blocky versions** (16×16 grid, upscaled with hard edges) for the stud style.
- **Flipbooks:**
  - Render 16 frames of an animated Cycles shader (4D noise with W animated, plus an erosion value) on a transparent background.
  - Pack them into a 4×4 grid at 1024², frame 0 top-left, row by row.
  - In Roblox: `FlipbookLayout = Grid4x4`, `FlipbookMode = OneShot`.
- **VFX meshes:** built with the same vocabulary (crystal rings and bursts, shell shards, slash arcs, the level-up pillar) and exported as one `<Set>VFXMeshes.glb`.
- **Trails and beams:** horizontal strips with the head on the left and soft lengthwise streaks.
- **Record every texture id in `ReplicatedStorage.VFXLibrary`.** `"rbxassetid://0"` means "not uploaded", and the effect is skipped.

### 6.6 UI icons
- Render the in-game blocky models at 512×512 with Cycles and an orthographic camera, transparent background and `Standard` view transform.
- Thick black outlines come from Freestyle: silhouette/border at about 9 px, plus a thinner dark crease lineset.
- Use saturated base colours with low emission so they don't wash out.

### 6.6b Smooth weapon pipeline (4d)
1. **Build with `SmoothBuilder`** from `GenerateStarterSet.py`: tubes with parallel-transport frames, Coons-patch blades and spheres. Each face corner carries a painted `Col` and a detail `Mask` (R steel, G wood, B leather, A brass).
2. **Subdivide once** (level 1) and apply it. Keep each part under 20k triangles; aim for 8–13k.
3. **Smart UV Project**, then **bake the DIFFUSE COLOR pass** (Cycles) of the paint shader into a 1024² texture.
4. **Swap to a plain textured material.** Remove the vertex colours **by name**: removing them through stale references deleted the UV map.
5. **Mark the part `KeepMaterial`**, so the GLB export keeps the baked texture instead of a flat palette colour.
6. **Export sockets** (`Tip`, `TrailTop`, `TrailBottom`) as `Socket_*` meshes.

### 6.7 Getting assets into Studio
- **Meshes:** File (or Home/Avatar) → **Import 3D** → the `.glb`. Keep the default settings and rename the model to the asset name.
- **Images:** Studio Asset Manager → **Bulk Import** → right-click each image → **Copy Asset ID** → paste into `VFXLibrary`. The place must be published first.
  - Alternatively, serve the folder from Blender over `127.0.0.1` and use Studio's image upload.
- **Keep the beginner guide in step:** whenever the asset flow changes, update `docs/Guide_AddFrostmaneToRoblox.md`, or a per-set guide in the same style. Write it assuming the reader has never used Blender or Studio.

---

## 7. Studio assembly rules
- **Weapons:** a one-time `MakeTool` command-bar step (pattern: `StarterSet.MakeTool`):
  - turn the imported model into a Tool whose `Handle` is the handle part, with `Head` welded to it;
  - turn the sockets into `TipAttachment` plus a `SwingTrail` between `TrailTop` and `TrailBottom`;
  - set `Tool.Grip` (the grip distance and the yaw are settings) and the weapon attributes.
- **Assembly is a one-time step run from the Studio command bar** in Edit mode, never in Play. `SurfaceAppearance.ColorMap` can only be set from Studio. It follows the pattern of `FrostmaneVFX.Assemble(model, kind)`:
  1. Colour each part from the palette and set its material:
     - plastic parts: SmoothPlastic plus a `SurfaceAppearance` with AlphaMode = Overlay and ColorMap = `StudOverlay`;
     - crystals and membranes: **Glass**, transparency 0.15–0.3;
     - eyes, cracks and seams: **Neon**.
  2. Move the glowing parts into a `Glow` sub-model, so **one** Highlight covers them all.
  3. Anchor the root part (`Body` for monsters, `Nest` or an invisible `EggCore` at the base for eggs, `Handle` for weapons). Every other part gets a WeldConstraint to it and is set unanchored, Massless and CanCollide = false.
  4. Eggs: the shell parts are welded to an anchored, invisible `EggCore`, which the idle animation moves.
  5. Turn `Socket_*` parts into Attachments, then delete the sockets. The Mouth attachment faces out of the mouth.
  6. Fill in any missing attributes and set `PrimaryPart`. Assemble must be safe to re-run.
- **Glow** (strongest first, all subtle so the colours stay readable):
  - a Highlight on the `Glow` model (FillTransparency 0.66–0.8, Occluded, pulsing);
  - a PointLight in the tier colour (Brightness ~1.4–2, Range 9–14);
  - emitters using textures from `VFXLibrary` (LightEmission 1, LightInfluence 0).
- **Attributes:**
  - **Weapons:** `WeaponType`, `Tier`, `Rarity`, `Damage`, `StrengthPerClick`, `CashPrice`, `AttackSpeed`.
  - **Monsters:** `MonsterName`, `Rarity`, `Tier`, `SourceEgg`, `HatchChance`, `CashPerSecond`, `StrengthMultiplier`, `LuckMultiplier`, `IndexReward`, `IdleHover`.
  - **Eggs:** `EggName`, `Rarity`, `Tier`, `TopDrop`, `TopDropChance`.
  - **Mushrooms:** `MushroomType`, `Zone`, `MaxHealth`, `Health`, `Stage`, `StrengthReward`, `EggDrop`, `RespawnTime`.
  - **Dummies:** `IsAFKDummy`, `StrengthPerSecond`, `UnlockCost`, `Tier`.
- **Runtime effects API** (copy this pattern for every set):
  - `Start<Monster>(model)` and `StartEgg(model, {PriceText})` return a handle with `.Stop()`.
  - `PlayHatch(egg, onReveal)`.
  - `ResetEgg(egg)`.
- **Placement:**
  - Raycast to the ground, and keep assets from overlapping each other or the SpawnLocation.
  - Keep cyan or coloured lights from tinting neighbouring props.
- **Never edit during Play mode,** because changes are lost. Stop the playtest first.
- Don't modify or delete anything I didn't ask about.
- **Verify every asset** with a preview render (Blender) or a screenshot (Studio) before calling it done.

---

## 8. Repo layout & code deliverables (production-ready Luau)

```
blender/                                  bpy generators (one per asset family)
src/ReplicatedStorage/                    ModuleScripts
src/StarterPlayer/StarterPlayerScripts/   client LocalScripts
src/ServerScriptService/                  server Scripts
docs/                                     guides, this brief, preview images (docs/images)
```

**Done** (extend these; don't rewrite them):
1. `AnimationController.lua` and `AnimationConfig.lua`: the weapon combo, shoulder idle and drag run (5.6).
2. `blender/GenerateCorePlayerAnimations.py`: the R15 rig and the animation clips.
3. `blender/GenerateFrostmaneSet.py`: the Frostmane Wyrm, Frostmane Egg and Frostmane VFX set (5.1–5.3).
4. `FrostmaneVFX.lua`, `VFXLibrary.lua` and `FrostmaneDemo.lua` (click-to-hatch demo).
5. `blender/GenerateStarterSet.py`, `StarterSet.lua` and `StarterDemo.lua`: the Wood starter set (5.4, 5.4b).
6. `blender/GenerateBestiary.py`, `CreatureKit.lua`, `BestiaryData.lua` and `BestiaryDemo.lua`: every other egg and monster (5.4c).
7. `blender/GenerateChoppers.py`, `ChopperKit.lua`, `ChopperData.lua` and `ChopperDemo.lua`: the other nine choppers (5.4d).
8. Docs:
   - `docs/Guide_AddFrostmaneToRoblox.md`, `docs/Guide_StarterSet.md`, `docs/Guide_Bestiary.md` and `docs/Guide_Choppers.md` (beginner guides);
   - `docs/FrostmaneSet.md`;
   - `docs/PlayerAnimations.md`.

**To build:**
1. **`HUDAndFeedbackController.lua`** (client):
   - the bottom-left stack;
   - the Settings modal (music, SFX, reduced motion, codes);
   - floating `+X 💪` popups;
   - the sidebar button feel (5.8).
2. **`MushroomHealthService.lua`** (server):
   - mushroom health and damage (validating the `ChopImpact` remote that `AnimationConfig` fires), and the 3 stages (1.0 / 0.8 / 0.6 scale);
   - shrink tweens, break, egg and Strength drops, and respawn;
   - remote events for client hit VFX and health bars.
3. **`EggIncubatorService.lua`** (server): capacity checks, zone egg spawning, plot placement, hatch timers, weighted monster rolls and passive income. Hatching uses `CreatureKit.RollHatch`, `StartEgg`, `PlayHatch` and `StartMonster`, and the follower bonus uses `CreatureKit.FollowerBonus`.
4. **`IndexRewardService.lua`** (server): records discoveries and grants one-time Cash rewards.
5. **`UpgradesService.lua`** (server): Choppers weapon purchases, plus the Upgrades stats (capacity, luck, hitbox range, WalkSpeed).
6. **`StrengthLevelService.lua`** (server): click gains, levels, rebirth level walls and the level-up lightbeam event.
7. **`LeaderboardService.lua`** (server): the 3D leaderboards with OrderedDataStore.
8. **Blender generators** for every remaining asset family, each following section 6 and reusing the Frostmane vocabulary:
   - the other tiers' VFX (all eggs and monsters are done, 5.4c);
   - mushrooms (5.5);
   - dummies (5.7);
   - world props;
   - UI icons.
9. **Design spec sheet:**
   - colour hex palettes;
   - tween and easing values;
   - floating-text mechanics;
   - camera shake;
   - particle emitter settings;
   - the egg hatch cutscene;
   - the level-up beam;
   - the weapon combo.

**Code conventions:**
- Asset ids of `"rbxassetid://0"` are skipped with a single warning, never an error.
- Hooks and callbacks run inside `pcall`.
- Client effects respect `SFXEnabled` and `ReducedMotion`.
- Lint Luau with selene; Python must compile.
- Test every Blender script headless by running it twice in a row in one session.

---

## 9. How I'll ask
- "Make a [tier] [axe/sword] called [name]."
- "Make a [rarity] [tier] monster called [name]" (optionally "based on a [creature]").
- "Make the [tier] egg" / "Make the [tier] training dummy."
- "Make a [species] mushroom for zone [N]."
- "Make the [name] sidebar button."
- "Make the [effect] VFX" (e.g. hit sparks, egg hatch burst, level-up beam).

**For every asset, deliver all of these:**
- the Blender generator;
- the GLB(s) plus preview renders committed to `docs/images`;
- its VFX textures and meshes;
- a Luau effects module following the `FrostmaneVFX` / `StarterSet` pattern;
- the `VFXLibrary` entries;
- a beginner-guide section.

Match the complexity ladder (4a) to the tier and rarity.

**Naming:** if I don't give a name, invent a two-word fantasy name in the set's pattern (material + noun), for example Frostmane Wyrm, Frostmane Egg, Frostmane Cleaver, Emberbark Splitter, Voidspine Lurker.
