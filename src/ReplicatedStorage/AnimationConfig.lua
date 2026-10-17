--[[
	AnimationConfig  (ModuleScript)
	Location: ReplicatedStorage.AnimationConfig

	Single source of truth for the player weapon motion suite used by
	StarterPlayerScripts.AnimationController.

	Clips are authored by blender/GenerateCorePlayerAnimations.py at 60 fps:
	  Attack1_Slash          0.55 s  forehand diagonal slice   SwingWhoosh 0.183  Impact 0.283
	  Attack2_Backhand       0.55 s  flat backhand slice       SwingWhoosh 0.167  Impact 0.267
	  Attack3_Uppercut       0.55 s  rising slice              SwingWhoosh 0.167  Impact 0.267
	  Attack4_OverheadChop   0.80 s  two-handed chop finisher  SwingWhoosh 0.250  Impact 0.367
	  Idle_Weapon_Shoulder   2.80 s  loop, shaft resting on the right shoulder
	  Run_Weapon_Drag        0.70 s  loop, deep lean, blade tip dragging behind

	The four attacks are cut from one continuous combo: each ends exactly where
	the next begins (pose and velocity), and Attack4 flows back into Attack1, so
	chained or held swings loop seamlessly.

	After importing each clip in Studio's Animation Editor and publishing it,
	paste the resulting asset ids into Tracks below. An id of "rbxassetid://0"
	means "not uploaded yet": the controller skips that track instead of erroring.

	Hooks: other client scripts can listen to animation events without touching
	the controller:

		local AnimationConfig = require(ReplicatedStorage.AnimationConfig)
		local disconnect = AnimationConfig.AddHook("Impact", function(ctx)
			print(ctx.Tool, ctx.Position, ctx.AttackSpeed)
		end)
]]

local AnimationConfig = {}

local FPS = 60
AnimationConfig.FrameRate = FPS

-- Cross-fade used for every state change unless a track overrides it.
AnimationConfig.DefaultFadeTime = 0.15

----------------------------------------------------------------------
-- Tracks
----------------------------------------------------------------------
-- Priority order (low -> high): Core < Idle < Movement < Action < Action2 < Action3 < Action4.
-- Roblox's default Animate script plays at Core, so every track below wins over it.
-- Attacks sit one level above Idle so a swing fully replaces the idle's upper body
-- instead of averaging 50/50 with it (same-priority tracks blend by weight).
local function attack(assetId: string, frameCount: number, whooshFrame: number, impactFrame: number, impactScale: number)
	return {
		AssetId = assetId,
		Priority = Enum.AnimationPriority.Action2,
		Looped = false,
		DefaultSpeed = 1.0,
		-- Snappy in, soft out: a 0.15 s fade-in would swallow most of a sped-up
		-- anticipation, so the first hit pops in fast and the last settles slowly.
		FadeIn = 0.08,
		FadeOut = 0.15,
		Weight = 1,
		ClipLength = frameCount / FPS,
		-- Clip-time (at speed 1) of each event. Used as a fallback when the
		-- uploaded clip has no animation events (FBX import does not carry
		-- Blender markers). Once a real marker fires, the fallback is retired.
		Events = {
			SwingWhoosh = whooshFrame / FPS,
			Impact = impactFrame / FPS,
		},
		-- Scales camera shake and hit-stop for this hit (the finisher lands hardest).
		ImpactScale = impactScale,
	}
end

AnimationConfig.Tracks = {
	Attack1 = attack("rbxassetid://0", 33, 11, 17, 0.8), -- Attack1_Slash
	Attack2 = attack("rbxassetid://0", 33, 10, 16, 0.8), -- Attack2_Backhand
	Attack3 = attack("rbxassetid://0", 33, 10, 16, 0.9), -- Attack3_Uppercut
	Attack4 = attack("rbxassetid://0", 48, 15, 22, 1.6), -- Attack4_OverheadChop

	Idle = {
		AssetId = "rbxassetid://0", -- Idle_Weapon_Shoulder
		Priority = Enum.AnimationPriority.Action,
		Looped = true,
		DefaultSpeed = 1.0, -- 2.8 s breath
		FadeIn = 0.15,
		FadeOut = 0.15,
		Weight = 1,
	},

	Run = {
		AssetId = "rbxassetid://0", -- Run_Weapon_Drag
		Priority = Enum.AnimationPriority.Movement,
		Looped = true,
		-- At BaseWalkSpeed the 0.7 s stride cycle plays at this rate.
		DefaultSpeed = 1.0,
		FadeIn = 0.15,
		FadeOut = 0.15,
		Weight = 1,
	},
}

----------------------------------------------------------------------
-- Attack combo
----------------------------------------------------------------------
AnimationConfig.Combo = {
	-- Played in order, wrapping back to the first. Steps whose AssetId isn't
	-- uploaded yet are skipped. Swords and axes both use this mix of slices
	-- and chops; reorder or trim it per weapon with WeaponTypeOverrides.
	Steps = { "Attack1", "Attack2", "Attack3", "Attack4" },
	-- If the next attack starts within this long after the last one ended, the
	-- combo continues. Otherwise it restarts at step 1.
	ResetTime = 0.45,
	-- Cross-fade between chained hits. The clips already meet pose-for-pose,
	-- so this only needs to hide a frame of timing jitter.
	ChainFadeTime = 0.04,
}

----------------------------------------------------------------------
-- Locomotion / gait
----------------------------------------------------------------------
AnimationConfig.Locomotion = {
	BaseWalkSpeed = 16, -- Roblox default Humanoid.WalkSpeed; the speed the run clip was timed for.
	-- playback = DefaultSpeed * (groundSpeed / BaseWalkSpeed) ^ SpeedExponent
	-- An exponent below 1 lets faster characters lengthen their stride a little
	-- instead of only spinning their legs faster (reads better at 30+ WalkSpeed).
	SpeedExponent = 0.85,
	MinPlaybackSpeed = 0.45,
	MaxPlaybackSpeed = 2.4,
	-- Hysteresis so tiny velocity jitter doesn't flicker between idle and run.
	EnterRunSpeed = 1.2, -- studs/s needed to start running
	ExitRunSpeed = 0.6, -- studs/s below which we return to idle...
	ExitRunDelay = 0.08, -- ...after staying below it this long
	-- Spring that smooths playback speed (critically damped when Damping = 1).
	SpeedSpring = { Frequency = 6, Damping = 1 },
	-- Humanoid states where the weapon locomotion fades out and the default
	-- Animate script's jump/fall/climb/swim takes over.
	SuspendedStates = {
		[Enum.HumanoidStateType.Jumping] = true,
		[Enum.HumanoidStateType.Freefall] = true,
		[Enum.HumanoidStateType.Climbing] = true,
		[Enum.HumanoidStateType.Swimming] = true,
		[Enum.HumanoidStateType.Seated] = true,
		[Enum.HumanoidStateType.FallingDown] = true,
		[Enum.HumanoidStateType.Ragdoll] = true,
		[Enum.HumanoidStateType.PlatformStanding] = true,
	},
}

----------------------------------------------------------------------
-- Swing input & attack speed
----------------------------------------------------------------------
AnimationConfig.Swing = {
	AttackSpeedAttribute = "AttackSpeed", -- Tool attribute, 1 = clip speed
	MinAttackSpeed = 0.25,
	MaxAttackSpeed = 4,
	-- A click this close to the end of the current swing is queued, not dropped.
	InputBufferTime = 0.12,
	-- Holding the mouse keeps chopping (Tool.Activated fires once per press).
	HoldToRepeat = true,
	-- Small grace before a fallback event fires, so a real marker wins the race.
	FallbackGrace = 0.03,
}

----------------------------------------------------------------------
-- Weapon detection
----------------------------------------------------------------------
AnimationConfig.Weapon = {
	-- Only Tools carrying this attribute drive the weapon motion suite (brief 5.7).
	RequiredAttribute = "WeaponType",
	-- First match wins when finding where an impact happens.
	TipAttachmentNames = { "TipAttachment", "HitPoint", "BladeTip" },
	HeadPartNames = { "Head", "Blade" },
	-- Optional Trail inside the Tool, enabled from SwingWhoosh until shortly after Impact.
	TrailName = "SwingTrail",
	TrailLinger = 0.12,
}

-- Per-WeaponType tweaks. A track name (Attack1, Idle, Run, ...) replaces fields
-- in that track; ComboSteps replaces the combo order for that weapon type.
-- Examples:
--   Axe = { ComboSteps = { "Attack1", "Attack4" } },           -- slice then big chop
--   Sword = { Attack4 = { AssetId = "rbxassetid://123" } },     -- a sword-specific finisher
AnimationConfig.WeaponTypeOverrides = {
	Axe = {},
	Sword = {},
	-- The newer choppers (GenerateChoppers.py) use the same combo until they get their own clips.
	Sickle = {},
	Scythe = {},
	Halberd = {},
	Glaive = {},
}

----------------------------------------------------------------------
-- Impact & whoosh feedback
----------------------------------------------------------------------
AnimationConfig.Effects = {
	-- Players can opt out via a HUD setting: LocalPlayer:SetAttribute("ReducedMotion", true)
	ScreenShake = {
		Enabled = true,
		ImpactTrauma = 0.45, -- 0..1, shake strength is trauma^2
		MaxAngleDegrees = 1.6,
		MaxOffsetStuds = 0.18,
		Frequency = 22, -- noise samples per second
		Decay = 2.6, -- trauma lost per second
	},

	-- Heavy impact frame: freeze the swing for a beat on contact, then release.
	HitStop = {
		Enabled = true,
		Duration = 0.055,
		SpeedScale = 0.04,
	},

	-- Textures come from ReplicatedStorage.VFXLibrary (Blender-made, white RGB +
	-- alpha). Missing keys are skipped: never fall back to built-in Roblox textures.
	ImpactParticles = {
		{
			Texture = "MushroomChunk",
			Count = 9,
			Lifetime = NumberRange.new(0.35, 0.6),
			Speed = NumberRange.new(14, 24),
			SpreadAngle = Vector2.new(70, 70),
			Size = NumberSequence.new({
				NumberSequenceKeypoint.new(0, 0.55),
				NumberSequenceKeypoint.new(1, 0.1),
			}),
			Acceleration = Vector3.new(0, -60, 0),
			RotSpeed = NumberRange.new(-360, 360),
			UseTierColor = false,
			Color = ColorSequence.new(Color3.fromRGB(255, 244, 228)),
		},
		{
			Texture = "Sparkle",
			Count = 6,
			Lifetime = NumberRange.new(0.18, 0.3),
			Speed = NumberRange.new(8, 14),
			SpreadAngle = Vector2.new(180, 180),
			Size = NumberSequence.new({
				NumberSequenceKeypoint.new(0, 1.1),
				NumberSequenceKeypoint.new(1, 0),
			}),
			LightEmission = 1,
			UseTierColor = true,
		},
		{
			Texture = "ShockwaveRing",
			Count = 1,
			Lifetime = NumberRange.new(0.22, 0.22),
			Speed = NumberRange.new(0, 0),
			Size = NumberSequence.new({
				NumberSequenceKeypoint.new(0, 0.4),
				NumberSequenceKeypoint.new(1, 4.5),
			}),
			Transparency = NumberSequence.new({
				NumberSequenceKeypoint.new(0, 0.2),
				NumberSequenceKeypoint.new(1, 1),
			}),
			LightEmission = 1,
			UseTierColor = true,
		},
	},

	-- Sound ids of "rbxassetid://0" are skipped. Respects the HUD SFX toggle via
	-- LocalPlayer:GetAttribute("SFXEnabled") == false.
	Sounds = {
		SwingWhoosh = { SoundId = "rbxassetid://0", Volume = 0.55, PitchMin = 0.95, PitchMax = 1.1 },
		Impact = { SoundId = "rbxassetid://0", Volume = 0.8, PitchMin = 0.9, PitchMax = 1.05 },
	},

	-- Tier glow colours (brief section 4 tier table). Tool attribute `Tier` selects one.
	TierColors = {
		Wood = Color3.fromRGB(150, 220, 110),
		Crystal = Color3.fromRGB(196, 160, 255),
		Lava = Color3.fromRGB(255, 140, 50),
		Void = Color3.fromRGB(150, 80, 230),
		Celestial = Color3.fromRGB(110, 230, 255),
	},
	DefaultTierColor = Color3.fromRGB(255, 255, 255),
}

----------------------------------------------------------------------
-- Event hooks
----------------------------------------------------------------------
-- Event names: "SwingStarted", "SwingWhoosh", "Impact", "SwingEnded",
--              "WeaponEquipped", "WeaponUnequipped", "StateChanged".
-- Every callback receives one ctx table:
--   { Event, Player, Character, Tool, WeaponType, Tier, AttackSpeed,
--     SwingId, ComboStep (1-based), ComboTrack ("Attack1"...), ImpactScale,
--     Position (Vector3?, Impact/Whoosh only), State (StateChanged only) }
-- Callbacks run inside pcall, so a broken hook never stalls the animation loop.
AnimationConfig.Hooks = {
	SwingStarted = {},
	SwingWhoosh = {},
	Impact = {
		-- Tell the server the blade connected. The server owns damage and must
		-- validate range and cooldown itself (MushroomHealthService).
		function(ctx)
			local ReplicatedStorage = game:GetService("ReplicatedStorage")
			local remotes = ReplicatedStorage:FindFirstChild("Remotes")
			local remote = remotes and remotes:FindFirstChild("ChopImpact")
			if remote and remote:IsA("RemoteEvent") then
				remote:FireServer(ctx.Tool, ctx.SwingId, ctx.ComboStep)
			end
		end,
	},
	SwingEnded = {},
	WeaponEquipped = {},
	WeaponUnequipped = {},
	StateChanged = {},
}

function AnimationConfig.AddHook(eventName: string, callback: (any) -> ()): () -> ()
	local list = AnimationConfig.Hooks[eventName]
	if not list then
		list = {}
		AnimationConfig.Hooks[eventName] = list
	end
	table.insert(list, callback)
	return function()
		local index = table.find(list, callback)
		if index then
			table.remove(list, index)
		end
	end
end

-- Returns the track definition for `trackName`, with any WeaponType override merged on top.
function AnimationConfig.GetTrackDef(trackName: string, weaponType: string?)
	local base = AnimationConfig.Tracks[trackName]
	if not base then
		return nil
	end
	local overrides = weaponType and AnimationConfig.WeaponTypeOverrides[weaponType]
	local override = overrides and overrides[trackName]
	if not override then
		return base
	end
	local merged = table.clone(base)
	for key, value in override do
		merged[key] = value
	end
	return merged
end

-- Combo order for a weapon type (falls back to Combo.Steps).
function AnimationConfig.GetComboSteps(weaponType: string?): { string }
	local overrides = weaponType and AnimationConfig.WeaponTypeOverrides[weaponType]
	return (overrides and overrides.ComboSteps) or AnimationConfig.Combo.Steps
end

function AnimationConfig.IsValidAssetId(assetId: string?): boolean
	if typeof(assetId) ~= "string" then
		return false
	end
	local id = tonumber(string.match(assetId, "%d+$"))
	return id ~= nil and id > 0
end

return AnimationConfig
