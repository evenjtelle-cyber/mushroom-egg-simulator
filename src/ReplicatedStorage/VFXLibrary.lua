--[[
	VFXLibrary  (ModuleScript)
	Location: ReplicatedStorage.VFXLibrary

	Every Blender-made VFX texture id in one place (brief 6.5). Particle textures
	are white RGB with the shape in alpha, so ParticleEmitter.Color tints one
	texture to any tier colour.

	Source files: ~/Documents/FrostmaneSet/Textures/*.png, written by
	blender/GenerateFrostmaneSet.py. Upload each one (Studio image upload,
	or the localhost route in brief 6.6) and paste the rbxassetid here.
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

	-- Flipbooks (1024x1024, 4x4 grid, frame 0 top-left): FlipbookLayout = Grid4x4
	FrostBreathFlipbook = "rbxassetid://0",

	-- Trails / beams (256x64 horizontal strip, head on the left)
	FrostStreak = "rbxassetid://0",
}
