# Beginner guide: putting the Frostmane dragon, egg and effects into Roblox

This guide assumes you've never done any of this before. Follow the parts in order. Each one ends with a check so you know it worked before moving on.

**Where you're heading:** an egg sits in your game, spinning and sparkling with a name label above it. When you click it, it shakes, flashes and bursts into ice, and the Frostmane Wyrm dragon appears next to it with frost effects.

**Time needed:** about 45 minutes the first time.

---

## The big picture

There are three kinds of things, made in three places:

| What | Made where | What you do with it |
|---|---|---|
| 3D models: the dragon, the egg and the effect shapes | **Blender**, by running a script | Import them into Roblox Studio |
| Effect pictures: sparkles, snowflakes, mist and the stud pattern | **Blender**, by the same script | Upload them to Roblox |
| Scripts that make it all glow and move | Already written: the `.lua` files in this project | Copy and paste them into Studio |

---

## Part 0: Get the tools and files

1. **Install Blender** (free) from <https://www.blender.org/download/>. Any version 4.2 or newer works.
2. **Install Roblox Studio** from <https://create.roblox.com/> (choose "Start Creating").
3. **Download this project's files:**
   1. Open the project page on GitHub.
   2. Click the button that says **main** (the branch picker, top left above the file list) and choose **`claude/determined-einstein-mfy9yk`**. That's where all the new files are.
   3. Click the green **Code** button, then **Download ZIP**.
   4. Find the ZIP in your Downloads folder and unzip it: on Windows, right-click it and choose **Extract All**; on Mac, double-click it.

✅ **Check:** you have a folder containing `blender`, `src` and `docs` folders.

---

## Part 1: Make the models and pictures in Blender

1. Open **Blender**. If a splash screen pops up, click anywhere outside it to close it.
2. At the very top of the window is a row of tabs: Layout, Modeling, Sculpting and so on. Click **Scripting**. It may be hidden off to the right if your window is narrow; scroll the tab row with your mouse wheel.
3. In the big text area in the middle of the Scripting tab, click **Open** (or use the menu **Text → Open**).
4. Find the unzipped project folder, open the `blender` folder and pick **`GenerateFrostmaneSet.py`**. Click **Open Text**.
5. Optional, but helpful on Windows: in the menu choose **Window → Toggle System Console**. A black window opens and shows progress messages while the script runs.
6. Click the **▶ Run Script** button at the top of the text area, or hover over the text and press **Alt+P**.

**Now wait 3–8 minutes.** Blender will look frozen and Windows may even say "Not Responding". **That's normal**: it's rendering preview pictures and building effect textures. Don't click anything and don't close it.

When it's done, Blender responds again and you'll see the dragon in the viewport. To see the egg or the effect shapes instead, use the **Outliner** (the list in the top right): click the eye icons next to `FrostmaneEgg_Parts` or `FrostmaneVFX_Parts`.

**Where the files went:**
- Windows: `C:\Users\YOUR-NAME\Documents\FrostmaneSet\`
- Mac: `/Users/YOUR-NAME/Documents/FrostmaneSet/`

Inside you'll find:
- `FrostmaneWyrm.glb` (the dragon)
- `FrostmaneEgg.glb` (the egg)
- `FrostmaneVFXMeshes.glb` (shards and rings for the hatch effect)
- a **`Textures`** folder with 12 PNG pictures
- a **`Previews`** folder with rendered pictures of everything

✅ **Check:** open `Previews/FrostmaneWyrm_front.png` and you should see the dragon.

> **If Blender closes, crashes or shows a red error:** see [Troubleshooting](#troubleshooting) at the end. You can also turn off the preview pictures, which makes it run in under a minute: near the top of the script, change `RENDER_PREVIEWS = True` to `RENDER_PREVIEWS = False`, then run it again.

---

## Part 2: Learn the five Studio windows you need

1. Open **Roblox Studio** and either open your game or click **Baseplate** to make a test place.
2. **Save it to Roblox first:** **File → Publish to Roblox**, give it a name and click **Create**. Uploading pictures only works for a published game.
3. Open the **View** tab at the top and switch on these four:
   - **Explorer**: the list of everything in your game (Workspace, ReplicatedStorage and so on).
   - **Properties**: shows the settings of whatever you've selected.
   - **Output**: messages and errors appear here. You'll use it to check things worked.
   - **Command Bar**: a one-line box at the bottom where you can run a line of code.
4. The fifth is **Asset Manager**, also on the View tab. You'll use it for uploading pictures in Part 4.

✅ **Check:** Explorer is on the right and shows **Workspace**, **ReplicatedStorage**, **ServerScriptService** and **ServerStorage**.

---

## Part 3: Add the three scripts

You'll make three script objects and paste code into each. The names must be **exactly** as written, capitals included.

### 3a. `VFXLibrary` (a ModuleScript in ReplicatedStorage)
1. In **Explorer**, hover over **ReplicatedStorage** and click the small **⊕** that appears.
2. Type `ModuleScript` in the search box and click it. A new item called "ModuleScript" appears.
3. Right-click it, choose **Rename**, and type **`VFXLibrary`**.
4. Double-click it to open the code. Select everything that's there (**Ctrl+A**, or Cmd+A on Mac) and delete it.
5. On your computer, open `src/ReplicatedStorage/VFXLibrary.lua` from the project folder in Notepad (Windows) or TextEdit (Mac). Copy everything and paste it into Studio.

### 3b. `FrostmaneVFX` (a ModuleScript in ReplicatedStorage)
Do the same again: a new **ModuleScript** in **ReplicatedStorage**, renamed **`FrostmaneVFX`**, with the contents of `src/ReplicatedStorage/FrostmaneVFX.lua` pasted in.

### 3c. `FrostmaneDemo` (a Script in ServerScriptService)
Hover over **ServerScriptService**, click **⊕**, choose **Script** (not ModuleScript, not LocalScript), rename it **`FrostmaneDemo`**, and paste in `src/ServerScriptService/FrostmaneDemo.lua`.

✅ **Check:** Explorer shows `ReplicatedStorage → VFXLibrary`, `ReplicatedStorage → FrostmaneVFX` and `ServerScriptService → FrostmaneDemo`.

---

## Part 4: Upload the 12 effect pictures and paste their IDs

Every picture you upload to Roblox gets an ID number. The scripts look the pictures up by those numbers.

1. Open **View → Asset Manager**.
2. Click **Bulk Import** (the button with an arrow, top of the Asset Manager).
3. Go to `Documents/FrostmaneSet/Textures`, select **all 12 PNG files** (click the first one, then Shift+click the last one) and click **Open**.
4. Wait for the upload. Roblox checks images first, so they can show as "pending" for a minute or so.
5. In Asset Manager, open the **Images** folder. You'll see the 12 pictures with the same names as the files.
6. For **each** picture:
   1. Right-click it and choose **Copy Asset ID**. You get something like `rbxassetid://1234567890`.
   2. Open your **`VFXLibrary`** script and find the line with the **same name**, for example `Sparkle = "rbxassetid://0",`.
   3. Replace `rbxassetid://0` with what you copied, keeping the quotes. It should look like `Sparkle = "rbxassetid://1234567890",`.

   If Copy Asset ID gives you only a number, write `rbxassetid://` in front of it.

The names to match:

| File in Textures | Line in VFXLibrary |
|---|---|
| StudOverlay.png | `StudOverlay` |
| SoftGlow.png | `SoftGlow` |
| FrostMote.png | `FrostMote` |
| Sparkle.png | `Sparkle` |
| BlockSparkle.png | `BlockSparkle` |
| BlockSnowflake.png | `BlockSnowflake` |
| IceShard.png | `IceShard` |
| ShockwaveRing.png | `ShockwaveRing` |
| FrostMist.png | `FrostMist` |
| MushroomChunk.png | `MushroomChunk` |
| FrostBreathFlipbook.png | `FrostBreathFlipbook` |
| FrostStreak.png | `FrostStreak` |

✅ **Check:** none of the 12 lines in VFXLibrary still says `rbxassetid://0`. Any line you miss just means that one effect won't show; nothing breaks.

---

## Part 5: Import the 3D models

### The dragon
1. **File → Import 3D**. In some Studio versions this button is on the **Home** or **Avatar** tab instead.
2. Choose `Documents/FrostmaneSet/FrostmaneWyrm.glb` and click **Open**.
3. A preview window opens. Leave the settings as they are and click **Import**.
4. The dragon appears in your game, and in Explorer under **Workspace** as a model. If its name isn't exactly **`FrostmaneWyrm`**, right-click it and **Rename** it.

### The egg
Do the same with **`FrostmaneEgg.glb`**. The model must be called **`FrostmaneEgg`**.

### The effect shapes
1. Import **`FrostmaneVFXMeshes.glb`** the same way. The model must be called **`FrostmaneVFXMeshes`**.
2. In Explorer, hover over **ReplicatedStorage**, click **⊕** and add a **Folder**. Rename it **`VFXMeshes`**.
3. Drag the `FrostmaneVFXMeshes` model from Workspace into the `VFXMeshes` folder.

✅ **Check:**
- The dragon and egg are in Workspace.
- The shards and rings are at `ReplicatedStorage → VFXMeshes → FrostmaneVFXMeshes`.
- The models look plain at this point (flat colours, no studs, no glass). The next part fixes that.

> **Is the size right?** The dragon should be about as tall as 4 stacked default characters (about 19 studs), and the egg a bit taller than one character. If it came in tiny or huge: select the model, use the **Scale** tool (Home tab) and drag a handle while holding **Shift** so it scales evenly.

---

## Part 6: Run the one-time setup

This step paints the models with the right colours and studs, makes the crystals glassy and the eyes glow, and glues all the pieces together.

1. Make sure you are **not** in Play mode. If the big buttons at the top say **Stop**, click Stop first.
2. Click into the **Command Bar** at the bottom, paste this one line and press **Enter**:
   ```lua
   local FX = require(game.ReplicatedStorage.FrostmaneVFX); FX.Assemble(workspace.FrostmaneWyrm, "Wyrm"); FX.Assemble(workspace.FrostmaneEgg, "Egg")
   ```
3. Look at **Output**. You should see two lines starting with `[FrostmaneVFX] Assembled`.

✅ **Check:** the dragon and egg now have blue and white colours, small studs, glassy crystals and glowing eyes.

Then position things:
1. Use the **Move** tool (Home tab) to put the **egg** where you want it.
2. Drag **`FrostmaneWyrm`** in Explorer from **Workspace** into **ServerStorage**. The demo script makes a copy of it when the egg hatches.

> **Is the dragon facing backwards?** Before moving it to ServerStorage, select it, use the **Rotate** tool and turn it 180° so the head points where you want.

---

## Part 7: Try it

1. Click **Play** (or press **F5**).
2. Walk to the egg. It should spin slowly, bob, sparkle at the crown, and show a "Frostmane Egg / Secret / $7.8B" label.
3. **Click the egg.** It shakes harder and harder, flashes white and bursts. Shell pieces fly out, an ice ring expands, snowflakes and sparkles pop, and the dragon appears beside it with glowing crystals, wing sparkles, mist at its feet and frosty breath puffs.
4. After 12 seconds the dragon disappears and the egg resets, so you can click it again.
5. Click **Stop** when you're done.

🎉 You're done.

---

## Troubleshooting

### Blender

| What you see | What to do |
|---|---|
| Blender says **Not Responding** or looks frozen | Normal while it renders. Wait up to 8 minutes. To make it faster, set `RENDER_PREVIEWS = False` near the top of the script. |
| **Blender closes or crashes** | Download the newest files from GitHub again (Part 0). An earlier version of the script could crash Blender while exporting, or when run a second time; that's fixed. If it still happens, open Blender, run the script again with the system console open (Part 1 step 5) and send me the last lines it printed. |
| **A red error message** appears | In the text area's **Text** menu, open the text called **`FrostmaneSet_Log`**. It holds the full error. Send it to me. |
| `KeyError: 'Emission Color'` or similar | Your Blender is older than 4.0. Install 4.2 or newer. |
| You can't find the output folder | Look at the last line of `FrostmaneSet_Log`, which reads `Done. Output: ...` followed by the folder. |

### Studio

| What you see | What to do |
|---|---|
| Output says `Assemble: no part named Body` (or `Nest`) | You picked the wrong model, or the model has an extra folder inside. Expand it in Explorer: the parts (Body, Belly, FurWhite and so on) should sit directly inside the model. |
| Output says `SurfaceAppearance needs Studio` | You ran the setup while playing. Click Stop and run Part 6 again. |
| `VFXLibrary.X is not uploaded yet` | That ID is still `rbxassetid://0`. Paste its ID (Part 4). |
| Models have no studs | `StudOverlay` isn't filled in. Fill it in, then run the Part 6 line again. |
| `FrostmaneVFXMeshes not found` | Check the names: the folder must be `VFXMeshes` inside ReplicatedStorage, and the model inside it must be `FrostmaneVFXMeshes`. |
| `Infinite yield possible on ... FrostmaneWyrm` | The demo can't find the dragon. It must be in **ServerStorage** and named exactly `FrostmaneWyrm`. |
| Clicking the egg does nothing | Make sure you're in Play mode (F5) and close enough (within 60 studs), and check Output for red errors. |

---

## What to change later

- **Monster and egg numbers** (cash per second, hatch chance, multipliers): after Part 6, select the model and look at the bottom of **Properties** under **Attributes**.
- **Colours:** change `PALETTE` in `GenerateFrostmaneSet.py`, then make the same change in `FrostmaneVFX.lua`.
- **Using it in your real game:** your own egg-hatching code calls the same three functions the demo uses, `FX.StartEgg`, `FX.PlayHatch` and `FX.StartWyrm`. Look at `FrostmaneDemo` for an example.
