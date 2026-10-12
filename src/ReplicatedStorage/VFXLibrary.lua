--[[
	VFXLibrary  (ModuleScript)
	Location: ReplicatedStorage.VFXLibrary

	Every Blender-made VFX texture id in one place (brief 6.5). Particle textures
	are white RGB with the shape in alpha, so ParticleEmitter.Color tints one
	texture to any tier colour.

	Source files: ~/Documents/FrostmaneSet/Textures/*.png,
	~/Documents/StarterSet/Textures/*.png and ~/Documents/Bestiary/Textures/*.png,
	written by blender/GenerateFrostmaneSet.py, GenerateStarterSet.py and
	GenerateBestiary.py (StudOverlay.png is identical in every folder; upload it once).
	Upload each one (Studio Asset Manager -> Bulk Import, or the localhost
	route in brief 6.6) and paste the rbxassetid here.
	"rbxassetid://0" means "not uploaded yet": every effect that uses it is
	skipped instead of falling back to built-in Roblox textures.
]]

return {
	-- Surfaces
	StudOverlay = "rbxassetid://0", -- SurfaceAppearance ColorMap (AlphaMode Overlay), 1 tile = 0.5 stud

	-- Particles (256x256, white + alpha)
	SoftGlow = "rbxassetid://0",
	FrostMote = "rbxassetid://0",
	Sparkle = "rbxassetid://0", -- four-point glint
	BlockSparkle = "rbxassetid://0", -- pixel-art glint (stud style)
	BlockSnowflake = "rbxassetid://0", -- pixel-art snowflake (stud style)
	IceShard = "rbxassetid://0",
	ShockwaveRing = "rbxassetid://0",
	FrostMist = "rbxassetid://0",
	MushroomChunk = "rbxassetid://0", -- AnimationController impact debris

	-- Wood tier / starter set (~/Documents/StarterSet/Textures)
	Spore = "rbxassetid://0", -- soft forest spore
	LeafBit = "rbxassetid://0", -- pixel-art leaf (stud style)
	DustPuff = "rbxassetid://0", -- landing / hatch dust
	SwingStreak = "rbxassetid://0", -- weapon swing trail strip (256x64, head on the left)

	-- Bestiary themes (~/Documents/Bestiary/Textures), used by CreatureKit
	Ember = "rbxassetid://0", -- pixel-art ember (Lava, Obsidian)
	VoidWisp = "rbxassetid://0", -- soft smoky wisp (Void)
	Glint = "rbxassetid://0", -- sharp four-point gem glint (Crystal, Geode, Mythic+)

	-- Flipbooks (1024x1024, 4x4 grid, frame 0 top-left): FlipbookLayout = Grid4x4
	FrostBreathFlipbook = "rbxassetid://0",

	-- Trails / beams (256x64 horizontal strip, head on the left)
	FrostStreak = "rbxassetid://0",
}
