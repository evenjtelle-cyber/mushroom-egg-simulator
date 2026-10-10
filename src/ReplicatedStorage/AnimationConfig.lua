--[[
	AnimationConfig  (ModuleScript)
	Location: ReplicatedStorage.AnimationConfig

	Single source of truth for the player weapon motion suite used by
	StarterPlayerScripts.AnimationController.

	Clips are authored by blender/GenerateCorePlayerAnimations.py at 30 fps:
	  Weapon_Chop_Heavy   frames 0-18  (0.600 s)  markers: SwingWhoosh @5, Impact @8
	  Idle_Weapon_Guard   frames 0-24  (0.800 s)  loop
	  Run_Weapon_Forward  frames 0-16  (0.533 s)  loop

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

local FPS = 30
AnimationConfig.FrameRate = FPS

-- Cross-fade used for every state change unless a track overrides it.
AnimationConfig.DefaultFadeTime = 0.15

----------------------------------------------------------------------
-- Tracks
----------------------------------------------------------------------
-- Priority order (low -> high): Core < Idle < Movement < Action < Action2 < Action3 < Action4.
-- Roblox's default Animate script plays at Core, so all three tracks below win over it.
-- Swing sits one level above Idle so a chop fully replaces the idle's upper body
-- instead of averaging 50/50 with it (same-priority tracks blend by weight).
AnimationConfig.Tracks = {
	Swing = {
		AssetId = "rbxassetid://0", -- Weapon_Chop_Heavy
		Priority = Enum.AnimationPriority.Action2,
		Looped = false,
		DefaultSpeed = 1.0,
		-- Snappy in, soft out: a 0.15 s fade-in would swallow most of a sped-up
		-- 4-frame anticipation, so the swing pops in fast and settles out slowly.
		FadeIn = 0.06,
		FadeOut = 0.15,
		Weight = 1,
		ClipLength = 18 / FPS,
		-- Clip-time (at speed 1) of each event. Used as a fallback when the
		-- uploaded clip has no animation events (FBX import does not carry
		-- Blender markers). Once a real marker fires, the fallback is retired.
		Events = {
			SwingWhoosh = 5 / FPS,
			Impact = 8 / FPS,
		},
	},

	Idle = {
		AssetId = "rbxassetid://0", -- Idle_Weapon_Guard
		Priority = Enum.AnimationPriority.Action,
		Looped = true,
		-- The 24-frame breath is 0.8 s at 30 fps; 0.3x gives a calm ~2.7 s breath.
		DefaultSpeed = 0.3,
		FadeIn = 0.15,
		FadeOut = 0.15,
		Weight = 1,
	},

	Run = {
		AssetId = "rbxassetid://0", -- Run_Weapon_Forward
		Priority = Enum.AnimationPriority.Movement,
		Looped = true,
		-- At BaseWalkSpeed the 16-frame cycle plays at this rate (~0.63 s per stride pair).
		DefaultSpeed = 0.85,
		FadeIn = 0.15,
		FadeOut = 0.15,
		Weight = 1,
	},
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

-- Per-WeaponType clip swaps. Any field set here replaces the field in Tracks.
-- Example:
--   Sword = { Swing = { AssetId = "rbxassetid://123", Events = { SwingWhoosh = 3/30, Impact = 6/30 } } },
AnimationConfig.WeaponTypeOverrides = {
	Axe = {},
	Sword = {},
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
--     SwingId, Position (Vector3?, Impact/Whoosh only), State (StateChanged only) }
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
				remote:FireServer(ctx.Tool, ctx.SwingId)
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

function AnimationConfig.IsValidAssetId(assetId: string?): boolean
	if typeof(assetId) ~= "string" then
		return false
	end
	local id = tonumber(string.match(assetId, "%d+$"))
	return id ~= nil and id > 0
end

return AnimationConfig
