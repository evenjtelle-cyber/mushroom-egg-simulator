--[[
	AnimationController  (LocalScript)
	Location: StarterPlayer.StarterPlayerScripts.AnimationController

	Client motion engine for R15 weapon locomotion and attacks.

	  Idle     (Action)   Idle_Weapon_Shoulder  breathing loop, weapon resting on the shoulder
	  Run      (Movement) Run_Weapon_Drag       playback speed follows ground speed / WalkSpeed
	  Attack1-4 (Action2) slash, backhand, uppercut, overhead chop: a combo that
	                      loops; speed scales with Tool:GetAttribute("AttackSpeed")

	Each click plays the next combo step. A click inside the last InputBufferTime
	of a hit, or holding the mouse, chains straight into the next step: the clips
	meet pose-for-pose, so the chain (and its wrap from Attack4 to Attack1) is
	seamless. Pausing longer than Combo.ResetTime restarts the combo at step 1.

	Only Tools that carry a `WeaponType` attribute drive these tracks. Without one,
	and while jumping/falling/climbing/swimming, Roblox's default Animate script
	is left in charge. Every idle<->run change is a weighted cross-fade
	(AnimationConfig.DefaultFadeTime, 0.15 s) with speed hysteresis so the pose
	never pops.

	Animation events (marker names in the clip):
	  SwingWhoosh  whoosh sound + enables the Tool's SwingTrail
	  Impact       hit-stop, camera shake, Blender-textured particle burst, impact sound
	If the uploaded clip has no events (Blender markers don't survive FBX import),
	the controller fires them on a timer from each attack's Events in AnimationConfig,
	scaled by the current playback speed. The first real marker retires the timer.

	Public API (from any other LocalScript):
	  local controller = Players.LocalPlayer.PlayerScripts:WaitForChild("AnimationController")
	  controller.SwingRequested:Fire()                       -- swing (auto-chop, mobile button)
	  controller.AnimationEvent.Event:Connect(function(eventName, ctx) end)
	  -- or AnimationConfig.AddHook("Impact", fn) for callbacks with the same ctx.

	Player settings read from LocalPlayer attributes (set by the HUD):
	  SFXEnabled = false     mutes swing/impact sounds
	  ReducedMotion = true   disables camera shake
]]

local Debris = game:GetService("Debris")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local SoundService = game:GetService("SoundService")
local Workspace = game:GetService("Workspace")

local AnimationConfig = require(ReplicatedStorage:WaitForChild("AnimationConfig"))

local LocalPlayer = Players.LocalPlayer
local rng = Random.new()

----------------------------------------------------------------------
-- Public signals
----------------------------------------------------------------------
local SwingRequested = Instance.new("BindableEvent")
SwingRequested.Name = "SwingRequested"
SwingRequested.Parent = script

local AnimationEvent = Instance.new("BindableEvent")
AnimationEvent.Name = "AnimationEvent"
AnimationEvent.Parent = script

----------------------------------------------------------------------
-- Helpers
----------------------------------------------------------------------
local warned = {}
local function warnOnce(key: string, message: string)
	if not warned[key] then
		warned[key] = true
		warn("[AnimationController] " .. message)
	end
end

local cachedVFXLibrary = nil
local function getVFXLibrary()
	if cachedVFXLibrary then
		return cachedVFXLibrary
	end
	local module = ReplicatedStorage:FindFirstChild("VFXLibrary")
	if module and module:IsA("ModuleScript") then
		local ok, result = pcall(require, module)
		if ok and typeof(result) == "table" then
			cachedVFXLibrary = result
		end
	end
	return cachedVFXLibrary
end

local function runHooks(eventName: string, ctx)
	local hooks = AnimationConfig.Hooks[eventName]
	if hooks then
		-- Copy so a hook can remove itself while we iterate.
		for _, callback in table.clone(hooks) do
			local ok, err = pcall(callback, ctx)
			if not ok then
				warn(string.format("[AnimationController] %s hook failed: %s", eventName, tostring(err)))
			end
		end
	end
	AnimationEvent:Fire(eventName, ctx)
end

local function findFirstNamed(root: Instance, names: { string }, className: string): Instance?
	for _, name in names do
		local found = root:FindFirstChild(name, true)
		if found and found:IsA(className) then
			return found
		end
	end
	return nil
end

----------------------------------------------------------------------
-- Spring (sub-stepped damped harmonic oscillator)
----------------------------------------------------------------------
local Spring = {}
Spring.__index = Spring

function Spring.new(frequency: number, damping: number, initial: number)
	return setmetatable({
		omega = frequency * 2 * math.pi,
		damping = damping,
		position = initial,
		velocity = 0,
		target = initial,
	}, Spring)
end

function Spring:Snap(value: number)
	self.position = value
	self.velocity = 0
	self.target = value
end

function Spring:Step(dt: number): number
	-- Fixed 1/120 s sub-steps keep semi-implicit Euler stable at any frame rate.
	local remaining = math.min(dt, 0.1)
	while remaining > 0 do
		local h = math.min(remaining, 1 / 120)
		local accel = self.omega * self.omega * (self.target - self.position)
			- 2 * self.damping * self.omega * self.velocity
		self.velocity += accel * h
		self.position += self.velocity * h
		remaining -= h
	end
	return self.position
end

----------------------------------------------------------------------
-- Camera shake (trauma model; offset is removed before the camera updates
-- so rotational shake never drifts the player's look direction)
----------------------------------------------------------------------
local CameraShake = {
	trauma = 0,
	seed = rng:NextNumber(0, 1000),
	applied = CFrame.identity,
}

function CameraShake.Add(amount: number)
	CameraShake.trauma = math.clamp(CameraShake.trauma + amount, 0, 1)
end

function CameraShake.Start()
	RunService:BindToRenderStep("WeaponShakeUndo", Enum.RenderPriority.Camera.Value - 1, function()
		local camera = Workspace.CurrentCamera
		if camera and CameraShake.applied ~= CFrame.identity then
			camera.CFrame *= CameraShake.applied:Inverse()
		end
		CameraShake.applied = CFrame.identity
	end)

	RunService:BindToRenderStep("WeaponShakeApply", Enum.RenderPriority.Camera.Value + 1, function(dt)
		local settings = AnimationConfig.Effects.ScreenShake
		local camera = Workspace.CurrentCamera
		if not camera or CameraShake.trauma <= 0 then
			return
		end

		local shake = CameraShake.trauma * CameraShake.trauma
		local t = os.clock() * settings.Frequency
		local seed = CameraShake.seed
		local function noise(offset: number): number
			return math.clamp(math.noise(seed + offset, t) * 2, -1, 1)
		end

		local offset = CFrame.new(
			noise(11.3) * settings.MaxOffsetStuds * shake,
			noise(23.7) * settings.MaxOffsetStuds * shake,
			0
		) * CFrame.Angles(
			math.rad(noise(37.1) * settings.MaxAngleDegrees * shake),
			math.rad(noise(41.9) * settings.MaxAngleDegrees * shake),
			math.rad(noise(59.3) * settings.MaxAngleDegrees * shake)
		)

		camera.CFrame *= offset
		CameraShake.applied = offset
		CameraShake.trauma = math.max(0, CameraShake.trauma - settings.Decay * dt)
	end)
end

----------------------------------------------------------------------
-- One-shot effects
----------------------------------------------------------------------
local function playSound(soundDef, parent: Instance?)
	if not soundDef or not AnimationConfig.IsValidAssetId(soundDef.SoundId) then
		return
	end
	if LocalPlayer:GetAttribute("SFXEnabled") == false then
		return
	end
	local sound = Instance.new("Sound")
	sound.SoundId = soundDef.SoundId
	sound.Volume = soundDef.Volume or 0.6
	sound.PlaybackSpeed = rng:NextNumber(soundDef.PitchMin or 1, soundDef.PitchMax or 1)
	sound.RollOffMaxDistance = 90
	sound.Parent = parent or SoundService
	sound:Play()
	Debris:AddItem(sound, 4)
end

local function emitImpactBurst(position: Vector3, tierColor: Color3)
	local library = getVFXLibrary()
	if not library then
		warnOnce("vfx", "ReplicatedStorage.VFXLibrary not found; impact particles skipped.")
		return
	end

	local attachment = Instance.new("Attachment")
	attachment.Name = "ImpactBurst"
	attachment.Position = position -- Terrain sits at the origin, so this is world space.
	attachment.Parent = Workspace.Terrain

	local longest = 0
	for _, def in AnimationConfig.Effects.ImpactParticles do
		local texture = library[def.Texture]
		if typeof(texture) ~= "string" then
			warnOnce("vfx-" .. def.Texture, "VFXLibrary has no '" .. def.Texture .. "' texture; layer skipped.")
			continue
		end

		local emitter = Instance.new("ParticleEmitter")
		emitter.Enabled = false
		emitter.Texture = texture
		emitter.Lifetime = def.Lifetime
		emitter.Speed = def.Speed
		emitter.SpreadAngle = def.SpreadAngle or Vector2.new(180, 180)
		emitter.Size = def.Size
		emitter.Transparency = def.Transparency or NumberSequence.new(0)
		emitter.Acceleration = def.Acceleration or Vector3.zero
		emitter.RotSpeed = def.RotSpeed or NumberRange.new(0)
		emitter.Rotation = NumberRange.new(0, 360)
		emitter.LightEmission = def.LightEmission or 0
		emitter.LightInfluence = if def.LightEmission then 0 else 1
		emitter.Color = if def.UseTierColor
			then ColorSequence.new(tierColor)
			else def.Color or ColorSequence.new(Color3.new(1, 1, 1))
		emitter.Parent = attachment
		emitter:Emit(def.Count)

		longest = math.max(longest, def.Lifetime.Max)
	end

	Debris:AddItem(attachment, longest + 0.25)
end

----------------------------------------------------------------------
-- Controller (one per character)
----------------------------------------------------------------------
local Controller = {}
Controller.__index = Controller

function Controller.new(player: Player, character: Model)
	local humanoid = character:WaitForChild("Humanoid") :: Humanoid
	local self = setmetatable({
		player = player,
		character = character,
		humanoid = humanoid,
		root = character:WaitForChild("HumanoidRootPart") :: BasePart,
		animator = humanoid:WaitForChild("Animator") :: Animator,

		connections = {},
		toolConnections = {},
		animations = {}, -- assetId -> Animation
		trackCache = {}, -- assetId -> AnimationTrack
		boundTracks = {}, -- AnimationTrack -> true (marker/stop signals connected)
		markersVerified = {}, -- assetId -> true once a real marker has fired

		tool = nil,
		weaponType = nil,
		roles = {}, -- "Idle" | "Run" -> { track, def, assetId }
		combo = {}, -- ordered attack roles: { track, def, assetId, name }
		comboIndex = 0, -- last combo step played
		lastSwingEnded = -math.huge,

		state = "None", -- "None" | "Idle" | "Run" | "Suspended"
		belowExitTime = 0,
		speedSpring = Spring.new(
			AnimationConfig.Locomotion.SpeedSpring.Frequency,
			AnimationConfig.Locomotion.SpeedSpring.Damping,
			1
		),

		swing = nil,
		swingCounter = 0,
		swingQueued = false,
		holding = false,
		destroyed = false,
	}, Controller)

	table.insert(self.connections, character.ChildAdded:Connect(function(child)
		if child:IsA("Tool") then
			self:_onToolAdded(child)
		end
	end))
	table.insert(self.connections, character.ChildRemoved:Connect(function(child)
		if child == self.tool then
			self:_unequip()
		end
	end))
	table.insert(self.connections, humanoid.Died:Connect(function()
		self:Destroy()
	end))
	table.insert(self.connections, RunService.Heartbeat:Connect(function(dt)
		self:_update(dt)
	end))

	for _, child in character:GetChildren() do
		if child:IsA("Tool") then
			self:_onToolAdded(child)
		end
	end

	return self
end

-- Track loading ------------------------------------------------------

function Controller:_loadTrack(def)
	if not def or not AnimationConfig.IsValidAssetId(def.AssetId) then
		return nil
	end
	local assetId = def.AssetId
	local track = self.trackCache[assetId]
	if not track then
		local animation = Instance.new("Animation")
		animation.AnimationId = assetId
		self.animations[assetId] = animation

		local ok, result = pcall(function()
			return self.animator:LoadAnimation(animation)
		end)
		if not ok then
			warnOnce("load-" .. assetId, "Could not load " .. assetId .. ": " .. tostring(result))
			return nil
		end
		track = result
		self.trackCache[assetId] = track
	end
	-- Re-apply every time: overrides may share an asset id with different settings.
	track.Priority = def.Priority
	track.Looped = def.Looped
	return track
end

function Controller:_resolveRole(roleName: string)
	local def = AnimationConfig.GetTrackDef(roleName, self.weaponType)
	local track = self:_loadTrack(def)
	if not track then
		warnOnce("missing-" .. roleName .. tostring(def and def.AssetId),
			roleName .. " has no uploaded AssetId in AnimationConfig; that state is skipped.")
		return nil
	end
	return { track = track, def = def, assetId = def.AssetId }
end

function Controller:_bindSwingTrack(role)
	local track = role.track
	if self.boundTracks[track] then
		return
	end
	self.boundTracks[track] = true

	local eventNames = { "SwingWhoosh", "Impact" }
	for eventName in role.def.Events or {} do
		if not table.find(eventNames, eventName) then
			table.insert(eventNames, eventName)
		end
	end
	for _, eventName in eventNames do
		table.insert(self.connections, track:GetMarkerReachedSignal(eventName):Connect(function()
			local swing = self.swing
			if swing and swing.track == track then
				self.markersVerified[swing.assetId] = true
				self:_fireSwingEvent(eventName)
			end
		end))
	end

	-- Safety net: the track stopped without us ending the swing (e.g. another
	-- script called StopAllAnimations). Deferred events mean the track may
	-- already be replaying a new swing, so only finish if it really stopped.
	table.insert(self.connections, track.Stopped:Connect(function()
		local swing = self.swing
		if swing and swing.track == track and swing.active and not track.IsPlaying then
			self:_finishSwing(swing)
		end
	end))
end

-- Equip / unequip ---------------------------------------------------

function Controller:_onToolAdded(tool: Tool)
	local attribute = AnimationConfig.Weapon.RequiredAttribute
	if tool:GetAttribute(attribute) == nil then
		return
	end
	if self.tool then
		self:_unequip()
	end

	self.tool = tool
	self.weaponType = tool:GetAttribute(attribute)
	self.roles = {
		Idle = self:_resolveRole("Idle"),
		Run = self:_resolveRole("Run"),
	}
	self.combo = {}
	for _, stepName in AnimationConfig.GetComboSteps(self.weaponType) do
		local role = self:_resolveRole(stepName)
		if role then
			role.name = stepName
			self:_bindSwingTrack(role)
			table.insert(self.combo, role)
		end
	end
	self.comboIndex = 0

	table.insert(self.toolConnections, tool.Activated:Connect(function()
		self.holding = true
		self:RequestSwing()
	end))
	table.insert(self.toolConnections, tool.Deactivated:Connect(function()
		self.holding = false
	end))

	self:_setTrail(false)
	runHooks("WeaponEquipped", self:_context("WeaponEquipped"))
	self.belowExitTime = 0
	self:_setState(self:_desiredState(0))
end

function Controller:_unequip()
	local tool = self.tool
	if not tool then
		return
	end

	if self.swing and self.swing.active then
		self.swing.track:Stop(self.swing.def.FadeOut)
		self:_finishSwing(self.swing, true)
	end
	self:_setTrail(false)
	self:_setState("None")

	for _, connection in self.toolConnections do
		connection:Disconnect()
	end
	table.clear(self.toolConnections)

	local ctx = self:_context("WeaponUnequipped")
	self.tool = nil
	self.weaponType = nil
	self.roles = {}
	self.combo = {}
	self.comboIndex = 0
	self.holding = false
	self.swingQueued = false
	runHooks("WeaponUnequipped", ctx)
end

-- Locomotion --------------------------------------------------------

function Controller:_groundSpeed(): number
	local velocity = self.root.AssemblyLinearVelocity
	local horizontal = Vector3.new(velocity.X, 0, velocity.Z).Magnitude
	-- Ignore knockback/fling spikes beyond what the Humanoid can actually walk.
	return math.min(horizontal, self.humanoid.WalkSpeed * 1.25)
end

function Controller:_desiredState(dt: number): string
	if not self.tool or self.humanoid.Health <= 0 then
		return "None"
	end
	if AnimationConfig.Locomotion.SuspendedStates[self.humanoid:GetState()] then
		return "Suspended"
	end

	local loco = AnimationConfig.Locomotion
	-- MoveDirection guards against riding conveyors/platforms while standing still.
	local wantsToMove = self.humanoid.MoveDirection.Magnitude > 0.01
	local speed = if wantsToMove then self:_groundSpeed() else 0

	if self.state == "Run" then
		if speed < loco.ExitRunSpeed then
			self.belowExitTime += dt
			if self.belowExitTime >= loco.ExitRunDelay then
				return "Idle"
			end
		else
			self.belowExitTime = 0
		end
		return "Run"
	end

	self.belowExitTime = 0
	return if speed >= loco.EnterRunSpeed then "Run" else "Idle"
end

function Controller:_targetRunSpeed(): number
	local loco = AnimationConfig.Locomotion
	local role = self.roles.Run
	local base = if role then role.def.DefaultSpeed else 1
	local ratio = self:_groundSpeed() / math.max(loco.BaseWalkSpeed, 0.01)
	local speed = base * math.pow(math.max(ratio, 0), loco.SpeedExponent)
	return math.clamp(speed, loco.MinPlaybackSpeed, loco.MaxPlaybackSpeed)
end

local function fadeIn(role, speed: number?)
	if not role then
		return
	end
	local def = role.def
	local track = role.track
	if track.IsPlaying then
		track:AdjustWeight(def.Weight, def.FadeIn or AnimationConfig.DefaultFadeTime)
		track:AdjustSpeed(speed or def.DefaultSpeed)
	else
		track:Play(def.FadeIn or AnimationConfig.DefaultFadeTime, def.Weight, speed or def.DefaultSpeed)
	end
end

local function fadeOut(role)
	if role and role.track.IsPlaying then
		role.track:Stop(role.def.FadeOut or AnimationConfig.DefaultFadeTime)
	end
end

function Controller:_setState(newState: string)
	if newState == self.state then
		return
	end
	local previous = self.state
	self.state = newState

	if newState == "Idle" then
		fadeIn(self.roles.Idle)
		fadeOut(self.roles.Run)
	elseif newState == "Run" then
		local speed = self:_targetRunSpeed()
		self.speedSpring:Snap(speed)
		fadeIn(self.roles.Run, speed)
		fadeOut(self.roles.Idle)
	else -- "Suspended" / "None": hand the body back to the default Animate script
		fadeOut(self.roles.Idle)
		fadeOut(self.roles.Run)
	end

	local ctx = self:_context("StateChanged")
	ctx.State = newState
	ctx.PreviousState = previous
	runHooks("StateChanged", ctx)
end

-- Per-frame ---------------------------------------------------------

function Controller:_update(dt: number)
	if self.destroyed then
		return
	end

	self:_setState(self:_desiredState(dt))

	if self.state == "Run" and self.roles.Run then
		self.speedSpring.target = self:_targetRunSpeed()
		self.roles.Run.track:AdjustSpeed(self.speedSpring:Step(dt))
	end

	local swing = self.swing
	if swing and swing.active then
		local track = swing.track
		local length = if track.Length > 0 then track.Length else swing.def.ClipLength
		local remainingSeconds = (length - track.TimePosition) / swing.speed
		-- Chaining into the next hit: run to the clip's end (it meets the next
		-- clip pose-for-pose) and hand over with a tiny cross-fade. Otherwise
		-- stop a touch early so the fade-out overlaps the clip's own settle.
		local chaining = self:_wantsChain()
		local fadeOutTime = if chaining
			then AnimationConfig.Combo.ChainFadeTime
			else swing.def.FadeOut or AnimationConfig.DefaultFadeTime

		if remainingSeconds <= fadeOutTime or os.clock() > swing.deadline then
			track:Stop(fadeOutTime)
			self:_finishSwing(swing)
		end
	end
end

-- Swing -------------------------------------------------------------

function Controller:_attackSpeed(): number
	local settings = AnimationConfig.Swing
	local value = self.tool and self.tool:GetAttribute(settings.AttackSpeedAttribute)
	if typeof(value) ~= "number" or value <= 0 then
		value = 1
	end
	return math.clamp(value, settings.MinAttackSpeed, settings.MaxAttackSpeed)
end

function Controller:_wantsChain(): boolean
	return self.swingQueued or (AnimationConfig.Swing.HoldToRepeat and self.holding)
end

function Controller:RequestSwing(): boolean
	if self.destroyed or not self.tool or #self.combo == 0 then
		return false
	end

	local swing = self.swing
	if swing and swing.active then
		local track = swing.track
		local length = if track.Length > 0 then track.Length else swing.def.ClipLength
		local remaining = (length - track.TimePosition) / swing.speed
		if remaining <= AnimationConfig.Swing.InputBufferTime then
			self.swingQueued = true
		end
		return false
	end

	self:_startSwing()
	return true
end

function Controller:_startSwing(chained: boolean?)
	-- Continue the combo if the last hit just ended, else restart at step 1.
	local continuing = chained or (os.clock() - self.lastSwingEnded) <= AnimationConfig.Combo.ResetTime
	self.comboIndex = if continuing then self.comboIndex % #self.combo + 1 else 1
	local role = self.combo[self.comboIndex]
	local def = role.def
	local track = role.track

	self.swingCounter += 1
	self.swingQueued = false

	local attackSpeed = self:_attackSpeed()
	local speed = def.DefaultSpeed * attackSpeed
	local length = if track.Length > 0 then track.Length else def.ClipLength

	local swing = {
		id = self.swingCounter,
		track = track,
		def = def,
		assetId = role.assetId,
		step = self.comboIndex,
		stepName = role.name,
		attackSpeed = attackSpeed,
		speed = speed,
		fired = {},
		active = true,
		-- Hard stop in case TimePosition never advances (asset failed to load).
		deadline = os.clock() + length / speed + 1,
	}
	self.swing = swing

	if track.IsPlaying then
		track:Stop(0)
	end
	track:Play(if chained then AnimationConfig.Combo.ChainFadeTime else def.FadeIn, def.Weight, speed)

	runHooks("SwingStarted", self:_context("SwingStarted"))

	if not self.markersVerified[role.assetId] and def.Events then
		local grace = AnimationConfig.Swing.FallbackGrace
		for eventName, clipTime in def.Events do
			task.delay(clipTime / speed + grace, function()
				if self.swing == swing and swing.active then
					self:_fireSwingEvent(eventName)
				end
			end)
		end
	end
end

function Controller:_finishSwing(swing, suppressRepeat: boolean?)
	if not swing.active then
		return
	end
	swing.active = false

	-- An Impact that never fired (clip cut short) still owes the hit.
	if not swing.fired.Impact and not suppressRepeat then
		self:_fireSwingEvent("Impact", swing)
	end

	self.lastSwingEnded = os.clock()
	runHooks("SwingEnded", self:_context("SwingEnded", swing))

	if suppressRepeat or self.destroyed or not self.tool then
		return
	end
	if self:_wantsChain() then
		self:_startSwing(true)
	end
end

function Controller:_fireSwingEvent(eventName: string, swingOverride)
	local swing = swingOverride or self.swing
	if not swing or swing.fired[eventName] then
		return
	end
	if not swingOverride and not swing.active then
		return
	end
	swing.fired[eventName] = true

	local ctx = self:_context(eventName, swing)
	ctx.Position = self:_impactPosition()

	if eventName == "SwingWhoosh" then
		self:_setTrail(true)
		playSound(AnimationConfig.Effects.Sounds.SwingWhoosh, self:_handle())
	elseif eventName == "Impact" then
		self:_onImpact(swing, ctx)
	end

	runHooks(eventName, ctx)
end

function Controller:_onImpact(swing, ctx)
	local effects = AnimationConfig.Effects

	-- Heavy impact frame: freeze on contact, then let the follow-through go.
	local impactScale = swing.def.ImpactScale or 1
	local hitStop = effects.HitStop
	if hitStop.Enabled and swing.active then
		swing.track:AdjustSpeed(swing.speed * hitStop.SpeedScale)
		task.delay(hitStop.Duration * impactScale, function()
			if self.swing == swing and swing.active then
				swing.track:AdjustSpeed(swing.speed)
			end
		end)
	end

	if effects.ScreenShake.Enabled and LocalPlayer:GetAttribute("ReducedMotion") ~= true then
		CameraShake.Add(effects.ScreenShake.ImpactTrauma * impactScale)
	end

	if ctx.Position then
		local tierColor = effects.TierColors[ctx.Tier] or effects.DefaultTierColor
		emitImpactBurst(ctx.Position, tierColor)
	end

	playSound(effects.Sounds.Impact, self:_handle())

	local tool = self.tool
	task.delay(AnimationConfig.Weapon.TrailLinger, function()
		-- Leave the trail on if a chained swing has already whooshed.
		local latest = self.swing
		if self.tool == tool and (latest == swing or not (latest and latest.fired.SwingWhoosh)) then
			self:_setTrail(false)
		end
	end)
end

-- Weapon geometry ---------------------------------------------------

function Controller:_handle(): BasePart?
	local handle = self.tool and self.tool:FindFirstChild("Handle")
	return if handle and handle:IsA("BasePart") then handle else nil
end

function Controller:_impactPosition(): Vector3?
	local tool = self.tool
	if not tool then
		return nil
	end
	local weapon = AnimationConfig.Weapon
	local tip = findFirstNamed(tool, weapon.TipAttachmentNames, "Attachment") :: Attachment?
	if tip then
		return tip.WorldPosition
	end
	local head = findFirstNamed(tool, weapon.HeadPartNames, "BasePart") :: BasePart?
	if head then
		return head.Position
	end
	local handle = self:_handle()
	return handle and handle.Position
end

function Controller:_setTrail(enabled: boolean)
	local tool = self.tool
	local trail = tool and tool:FindFirstChild(AnimationConfig.Weapon.TrailName, true)
	if trail and trail:IsA("Trail") then
		trail.Enabled = enabled
	end
end

function Controller:_context(eventName: string, swing)
	swing = swing or self.swing
	local tool = self.tool
	return {
		Event = eventName,
		Player = self.player,
		Character = self.character,
		Tool = tool,
		WeaponType = self.weaponType,
		Tier = tool and tool:GetAttribute("Tier"),
		AttackSpeed = if swing then swing.attackSpeed else self:_attackSpeed(),
		SwingId = swing and swing.id,
		ComboStep = swing and swing.step,
		ComboTrack = swing and swing.stepName,
		ImpactScale = swing and swing.def.ImpactScale or 1,
		State = self.state,
	}
end

-- Teardown ----------------------------------------------------------

function Controller:Destroy()
	if self.destroyed then
		return
	end
	self:_unequip()
	self.destroyed = true

	for _, connection in self.connections do
		connection:Disconnect()
	end
	table.clear(self.connections)

	for _, track in self.trackCache do
		track:Stop(0)
		track:Destroy()
	end
	for _, animation in self.animations do
		animation:Destroy()
	end
	table.clear(self.trackCache)
	table.clear(self.animations)
end

----------------------------------------------------------------------
-- Bootstrap
----------------------------------------------------------------------
local current = nil

local function onCharacterAdded(character: Model)
	if current then
		current:Destroy()
		current = nil
	end
	local controller = Controller.new(LocalPlayer, character)
	-- Controller.new yields on WaitForChild; drop it if the character already changed.
	if LocalPlayer.Character ~= character then
		controller:Destroy()
		return
	end
	current = controller
end

LocalPlayer.CharacterAdded:Connect(onCharacterAdded)
LocalPlayer.CharacterRemoving:Connect(function(character)
	if current and current.character == character then
		current:Destroy()
		current = nil
	end
end)
if LocalPlayer.Character then
	task.spawn(onCharacterAdded, LocalPlayer.Character)
end

SwingRequested.Event:Connect(function()
	if current then
		current:RequestSwing()
	end
end)

CameraShake.Start()
