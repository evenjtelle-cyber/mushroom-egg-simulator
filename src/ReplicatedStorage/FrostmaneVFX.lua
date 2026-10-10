--[[
	FrostmaneVFX  (ModuleScript)
	Location: ReplicatedStorage.FrostmaneVFX

	Studio assembly and runtime effects for the end-game Celestial set built by
	blender/GenerateFrostmaneSet.py:
	  Frostmane Wyrm  (Secret monster)    FrostmaneWyrm.glb
	  Frostmane Egg   (Secret egg + nest) FrostmaneEgg.glb
	  VFX meshes                          FrostmaneVFXMeshes.glb -> ReplicatedStorage.VFXMeshes

	1) ASSEMBLE ONCE IN STUDIO (Edit mode, command bar; NOT during Play).
	   SurfaceAppearance.ColorMap can only be set from Studio:
	     local FX = require(game.ReplicatedStorage.FrostmaneVFX)
	     FX.Assemble(workspace.FrostmaneWyrm, "Wyrm")
	     FX.Assemble(workspace.FrostmaneEgg, "Egg")
	   This colours every part from the palette and adds the stud overlay
	   (SurfaceAppearance, AlphaMode Overlay). It also sets materials
	   (Glass ice, Neon eyes and cracks), anchors and welds the parts, turns the
	   Socket_* markers into Attachments, groups glowing parts into a "Glow"
	   model and writes the brief's attributes.

	2) RUNTIME (server or client; client looks smoothest):
	     local handle = FX.StartWyrm(monsterModel)  -- glow, sparkles, mist, breath puffs
	     local handle = FX.StartEgg(eggModel)       -- spin/bob, crown sparkles, crack pulse, label
	     handle.Stop()
	     FX.PlayHatch(eggModel, function(centre) spawnMonster(centre) end)

	Textures come from ReplicatedStorage.VFXLibrary. An emitter whose texture
	is not uploaded yet is skipped (never a built-in Roblox texture).
]]

local Debris = game:GetService("Debris")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")

local VFXLibrary = require(ReplicatedStorage:WaitForChild("VFXLibrary"))

local FrostmaneVFX = {}

-- Mirrors PALETTE in blender/GenerateFrostmaneSet.py (sRGB hex).
FrostmaneVFX.PALETTE = {
	Body = "#23489E",
	Belly = "#CFE6FF",
	FurWhite = "#EEF5FF",
	FurIce = "#A9D3FF",
	FurBlue = "#4C8FE6",
	FurNavy = "#1C3F8F",
	Tusks = "#BDE3FF",
	Claws = "#F4F8FF",
	WingFrame = "#163577",
	WingMembrane = "#6FCBFF",
	Crystals = "#7FEAFF",
	CrystalsViolet = "#B48CFF",
	Eyes = "#9CFFFF",
	Mouth = "#0E1630",
	Shell = "#23489E",
	ShellBlue = "#4C8FE6",
	Frost = "#EEF5FF",
	FrostIce = "#A9D3FF",
	Cracks = "#5FF4FF",
	Crown = "#7FEAFF",
	CrownViolet = "#B48CFF",
	Nest = "#6F8FB8",
	NestLight = "#9DB8D8",
	NestSnow = "#EEF5FF",
	NestCrystals = "#7FEAFF",
	NestViolet = "#B48CFF",
	NestTusks = "#BDE3FF",
	NovaRing = "#7FEAFF",
	CrystalBurst = "#7FEAFF",
}

-- Look per part: Neon glows, Glass is translucent ice; everything else is
-- studded plastic.
local LOOKS = {
	Eyes = { Material = Enum.Material.Neon },
	Cracks = { Material = Enum.Material.Neon },
	Crystals = { Material = Enum.Material.Glass, Transparency = 0.15, Glow = true },
	CrystalsViolet = { Material = Enum.Material.Glass, Transparency = 0.15, Glow = true },
	Crown = { Material = Enum.Material.Glass, Transparency = 0.15, Glow = true },
	CrownViolet = { Material = Enum.Material.Glass, Transparency = 0.15, Glow = true },
	NestCrystals = { Material = Enum.Material.Glass, Transparency = 0.15, Glow = true },
	NestViolet = { Material = Enum.Material.Glass, Transparency = 0.15, Glow = true },
	WingMembrane = { Material = Enum.Material.Glass, Transparency = 0.3, Glow = true },
	NovaRing = { Material = Enum.Material.Glass, Transparency = 0.1 },
	CrystalBurst = { Material = Enum.Material.Glass, Transparency = 0.1 },
	Mouth = { Material = Enum.Material.SmoothPlastic, NoStuds = true },
}

local EGG_SHELL_PARTS = {
	Shell = true, ShellBlue = true, Frost = true, FrostIce = true,
	Cracks = true, Crown = true, CrownViolet = true,
}
local EGG_SHELL_SOCKETS = { EggCenter = true, Crown = true }

-- Brief section 7 attributes. Assemble only fills attributes that are not set yet.
FrostmaneVFX.ATTRIBUTES = {
	Wyrm = {
		MonsterName = "Frostmane Wyrm",
		Rarity = "Secret",
		Tier = "Celestial",
		SourceEgg = "Frostmane Egg",
		HatchChance = 0.00001, -- 1 in 100,000
		CashPerSecond = 2500000000,
		StrengthMultiplier = 25,
		LuckMultiplier = 5,
		IndexReward = 5000000000,
		IdleHover = false,
	},
	Egg = {
		EggName = "Frostmane Egg",
		Rarity = "Secret",
		Tier = "Celestial",
		TopDrop = "Frostmane Wyrm",
		TopDropChance = 0.00001,
	},
}

local ICE = Color3.fromRGB(127, 234, 255)
local VIOLET = Color3.fromRGB(180, 140, 255)
local WHITE = Color3.new(1, 1, 1)

----------------------------------------------------------------------
-- Helpers
----------------------------------------------------------------------
local warned = {}
local function warnOnce(key: string, message: string)
	if not warned[key] then
		warned[key] = true
		warn("[FrostmaneVFX] " .. message)
	end
end

local function texture(name: string): string?
	local id = VFXLibrary[name]
	local number = typeof(id) == "string" and tonumber(string.match(id, "%d+$"))
	if number and number > 0 then
		return id
	end
	warnOnce("tex-" .. name, "VFXLibrary." .. name .. " is not uploaded yet; effects using it are skipped.")
	return nil
end

-- Imported duplicates may carry Blender's ".001" suffix.
local function baseName(instance: Instance): string
	return string.match(instance.Name, "^(.-)%.%d+$") or instance.Name
end

local function emitter(parent: Instance, textureName: string, props): ParticleEmitter?
	local id = texture(textureName)
	if not id then
		return nil
	end
	local e = Instance.new("ParticleEmitter")
	e.Texture = id
	e.LightEmission = 1
	e.LightInfluence = 0
	e.Rotation = NumberRange.new(0, 360)
	for key, value in props do
		e[key] = value
	end
	e.Parent = parent
	return e
end

local function seq(a: number, b: number): NumberSequence
	return NumberSequence.new(a, b)
end

local function attachmentAt(model: Model, name: string): Attachment?
	local found = model:FindFirstChild(name, true)
	return if found and found:IsA("Attachment") then found else nil
end

local function burstAttachment(position: Vector3, lifetime: number): Attachment
	local a = Instance.new("Attachment")
	a.Position = position -- Terrain sits at the origin, so this is world space.
	a.Parent = workspace.Terrain
	Debris:AddItem(a, lifetime)
	return a
end

----------------------------------------------------------------------
-- 1) Studio assembly
----------------------------------------------------------------------
local function applyLook(part: BasePart, key: string)
	local hex = FrostmaneVFX.PALETTE[key]
	if hex then
		part.Color = Color3.fromHex(hex)
	end
	local look = LOOKS[key]
	part.Material = look and look.Material or Enum.Material.SmoothPlastic
	part.Transparency = look and look.Transparency or 0
	part.CastShadow = not (look and look.Material ~= Enum.Material.SmoothPlastic)

	for _, child in part:GetChildren() do
		if child:IsA("SurfaceAppearance") then
			child:Destroy() -- importer-made appearance; ours replaces it
		end
	end
	if look and (look.Material ~= Enum.Material.SmoothPlastic or look.NoStuds) then
		return
	end
	local studs = texture("StudOverlay")
	if not studs then
		return
	end
	local ok, err = pcall(function()
		local appearance = Instance.new("SurfaceAppearance")
		appearance.AlphaMode = Enum.AlphaMode.Overlay
		appearance.ColorMap = studs
		appearance.Parent = part
	end)
	if not ok then
		warnOnce("sa", "SurfaceAppearance needs Studio (command bar / plugin): " .. tostring(err))
	end
end

--[[
	Assemble(model, "Wyrm" | "Egg"). Safe to run again: welds and attachments
	are rebuilt from scratch.
]]
function FrostmaneVFX.Assemble(model: Model, kind: string)
	assert(kind == "Wyrm" or kind == "Egg", "kind must be \"Wyrm\" or \"Egg\"")
	local rootName = if kind == "Wyrm" then "Body" else "Nest"

	local parts, sockets = {}, {}
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") then
			if string.sub(d.Name, 1, 7) == "Socket_" then
				table.insert(sockets, d)
			elseif d.Name ~= "EggCore" then
				table.insert(parts, d)
			end
		elseif d:IsA("WeldConstraint") and d.Name == "FrostmaneWeld" then
			d:Destroy()
		end
	end

	local root: BasePart? = nil
	for _, p in parts do
		if baseName(p) == rootName then
			root = p
			break
		end
	end
	assert(root, "Assemble: no part named " .. rootName .. " in " .. model:GetFullName())

	-- Glowing parts live in a "Glow" sub-model so one Highlight covers them all.
	local glow = model:FindFirstChild("Glow") or Instance.new("Model")
	glow.Name = "Glow"
	glow.Parent = model

	-- The egg shell spins and bobs on an invisible core above the nest.
	local core: BasePart? = nil
	if kind == "Egg" then
		core = model:FindFirstChild("EggCore", true)
		if not core then
			core = Instance.new("Part")
			core.Name = "EggCore"
			core.Size = Vector3.one
			core.Transparency = 1
			core.CanCollide = false
			core.CanQuery = false
			core.Parent = model
		end
		local centre = root.Position
		for _, s in sockets do
			if s.Name == "Socket_EggCenter" then
				centre = s.Position
			end
		end
		core.CFrame = CFrame.new(centre)
		core.Anchored = true
	end

	root.Anchored = true
	for _, p in parts do
		local key = baseName(p)
		applyLook(p, key)
		local look = LOOKS[key]
		if look and look.Glow then
			p.Parent = glow
		end
		if p ~= root then
			local anchorTo = if core and EGG_SHELL_PARTS[key] then core else root
			p.Anchored = false
			p.Massless = true
			p.CanCollide = false
			local weld = Instance.new("WeldConstraint")
			weld.Name = "FrostmaneWeld"
			weld.Part0 = anchorTo
			weld.Part1 = p
			weld.Parent = p
		end
	end

	-- Socket markers -> Attachments (then the markers are removed).
	local headPos = nil
	for _, s in sockets do
		if s.Name == "Socket_Head" then
			headPos = s.Position
		end
	end
	for _, s in sockets do
		local name = string.sub(s.Name, 8)
		local parent = if core and EGG_SHELL_SOCKETS[name] then core else root
		local old = parent:FindFirstChild(name)
		if old and old:IsA("Attachment") then
			old:Destroy()
		end
		local a = Instance.new("Attachment")
		a.Name = name
		a.Parent = parent
		if name == "Mouth" and headPos then
			-- Face out of the mouth so breath emitters (EmissionDirection Front) blow forward.
			a.WorldCFrame = CFrame.lookAt(s.Position, s.Position + (s.Position - headPos))
		else
			a.WorldPosition = s.Position
		end
		s:Destroy()
	end

	for key, value in FrostmaneVFX.ATTRIBUTES[kind] do
		if model:GetAttribute(key) == nil then
			model:SetAttribute(key, value)
		end
	end
	model.PrimaryPart = root
	print(string.format("[FrostmaneVFX] Assembled %s (%d parts, %d sockets)", model.Name, #parts, #sockets))
end

----------------------------------------------------------------------
-- 2) Runtime effects
----------------------------------------------------------------------
local function newHandle()
	local handle = { connections = {}, instances = {}, tweens = {}, alive = true }
	function handle.Stop()
		handle.alive = false
		for _, c in handle.connections do
			c:Disconnect()
		end
		for _, t in handle.tweens do
			t:Cancel()
		end
		for _, i in handle.instances do
			i:Destroy()
		end
		table.clear(handle.connections)
		table.clear(handle.tweens)
		table.clear(handle.instances)
	end
	return handle
end

local function track(handle, instance)
	if instance then
		table.insert(handle.instances, instance)
	end
	return instance
end

local function pulse(handle, instance: Instance, info: TweenInfo, goal)
	local tween = TweenService:Create(instance, info, goal)
	table.insert(handle.tweens, tween)
	tween:Play()
	return tween
end

local PULSE = TweenInfo.new(1.6, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true)

local function addGlow(handle, model: Model, lightAt: Attachment?)
	local glow = model:FindFirstChild("Glow")
	if glow then
		local highlight = track(handle, Instance.new("Highlight"))
		highlight.Adornee = glow
		highlight.DepthMode = Enum.HighlightDepthMode.Occluded
		highlight.FillColor = ICE
		highlight.FillTransparency = 0.78
		highlight.OutlineTransparency = 1
		highlight.Parent = model
		pulse(handle, highlight, PULSE, { FillTransparency = 0.66 })
	end
	if lightAt then
		local light = track(handle, Instance.new("PointLight"))
		light.Color = ICE
		light.Brightness = 1.4
		light.Range = 13
		light.Shadows = false
		light.Parent = lightAt
		pulse(handle, light, PULSE, { Brightness = 1.9 })
		return light
	end
	return nil
end

--[[ Frostmane Wyrm idle: glow pulse, wing frost sparkles, spine shimmer,
     creeping foot mist, drifting snow, tail-tip motes and periodic breath puffs. ]]
function FrostmaneVFX.StartWyrm(model: Model)
	local handle = newHandle()
	addGlow(handle, model, attachmentAt(model, "Chest"))

	local glow = model:FindFirstChild("Glow")
	local membrane = glow and glow:FindFirstChild("WingMembrane")
	local crystals = glow and glow:FindFirstChild("Crystals")
	if membrane then
		track(handle, emitter(membrane, "BlockSparkle", {
			Rate = 7,
			Lifetime = NumberRange.new(0.8, 1.4),
			Speed = NumberRange.new(0.3, 1.2),
			SpreadAngle = Vector2.new(180, 180),
			Acceleration = Vector3.new(0, -1.2, 0),
			Size = seq(0.45, 0),
			Color = ColorSequence.new(ICE, WHITE),
		}))
	end
	if crystals then
		track(handle, emitter(crystals, "Sparkle", {
			Rate = 10,
			Lifetime = NumberRange.new(0.5, 0.9),
			Speed = NumberRange.new(1.5, 3),
			EmissionDirection = Enum.NormalId.Top,
			SpreadAngle = Vector2.new(15, 15),
			Size = seq(0.6, 0),
			Color = ColorSequence.new(ICE, VIOLET),
		}))
	end
	for _, foot in { "FootFL", "FootFR", "FootBL", "FootBR" } do
		local a = attachmentAt(model, foot)
		if a then
			track(handle, emitter(a, "FrostMist", {
				Rate = 1.6,
				Lifetime = NumberRange.new(2.5, 3.5),
				Speed = NumberRange.new(0.3, 0.8),
				SpreadAngle = Vector2.new(180, 8),
				Drag = 1,
				Acceleration = Vector3.new(0, 0.15, 0),
				RotSpeed = NumberRange.new(-20, 20),
				Size = seq(2.5, 5.5),
				Transparency = NumberSequence.new({
					NumberSequenceKeypoint.new(0, 1),
					NumberSequenceKeypoint.new(0.25, 0.7),
					NumberSequenceKeypoint.new(1, 1),
				}),
				LightEmission = 0.3,
				Color = ColorSequence.new(Color3.fromRGB(200, 235, 255)),
			}))
		end
	end
	local spine = attachmentAt(model, "Spine")
	if spine then
		track(handle, emitter(spine, "BlockSnowflake", {
			Rate = 4,
			Lifetime = NumberRange.new(2.2, 3.2),
			Speed = NumberRange.new(1, 2.5),
			SpreadAngle = Vector2.new(180, 180),
			Acceleration = Vector3.new(0, -1.4, 0),
			RotSpeed = NumberRange.new(-60, 60),
			Size = seq(0.45, 0.2),
			Color = ColorSequence.new(WHITE, ICE),
		}))
	end
	local tail = attachmentAt(model, "TailTip")
	if tail then
		track(handle, emitter(tail, "FrostMote", {
			Rate = 8,
			Lifetime = NumberRange.new(0.6, 1.2),
			Speed = NumberRange.new(0.5, 1.5),
			SpreadAngle = Vector2.new(180, 180),
			Size = seq(0.7, 0),
			Color = ColorSequence.new(ICE, VIOLET),
		}))
	end

	-- Breath: a few flipbook puffs every few seconds.
	local mouth = attachmentAt(model, "Mouth")
	local breath = mouth and track(handle, emitter(mouth, "FrostBreathFlipbook", {
		Enabled = false,
		FlipbookLayout = Enum.ParticleFlipbookLayout.Grid4x4,
		FlipbookMode = Enum.ParticleFlipbookMode.OneShot,
		Lifetime = NumberRange.new(1.1, 1.3),
		Speed = NumberRange.new(4, 6),
		EmissionDirection = Enum.NormalId.Front,
		SpreadAngle = Vector2.new(12, 12),
		Drag = 2,
		Size = seq(1.4, 4.2),
		Transparency = seq(0.15, 0.6),
		LightEmission = 0.6,
		Color = ColorSequence.new(Color3.fromRGB(215, 245, 255)),
	}))
	if breath then
		task.spawn(function()
			while handle.alive do
				task.wait(math.random() * 1.5 + 3.5)
				if not handle.alive then
					break
				end
				for _ = 1, 3 do
					breath:Emit(1)
					task.wait(0.12)
				end
			end
		end)
	end

	-- Optional hover (IdleHover attribute), brief section 7.
	local root = model.PrimaryPart
	if root and model:GetAttribute("IdleHover") then
		local base = root.CFrame
		local t = 0
		table.insert(handle.connections, RunService.Heartbeat:Connect(function(dt)
			t += dt
			root.CFrame = base * CFrame.new(0, math.sin(t * 1.4) * 0.35, 0)
		end))
		table.insert(handle.connections, {
			Disconnect = function()
				root.CFrame = base
			end,
		})
	end
	return handle
end

local function eggLabel(handle, model: Model, at: Instance, priceText: string?)
	local gui = track(handle, Instance.new("BillboardGui"))
	gui.Name = "EggLabel"
	gui.Adornee = at
	gui.Size = UDim2.fromScale(7, if priceText then 3.1 else 2.3)
	gui.StudsOffsetWorldSpace = Vector3.new(0, 2.2, 0)
	gui.AlwaysOnTop = false
	gui.LightInfluence = 0
	gui.MaxDistance = 120

	local layout = Instance.new("UIListLayout")
	layout.HorizontalAlignment = Enum.HorizontalAlignment.Center
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Parent = gui

	local function line(text: string, order: number, height: number, color: Color3)
		local label = Instance.new("TextLabel")
		label.LayoutOrder = order
		label.BackgroundTransparency = 1
		label.Size = UDim2.fromScale(1, height)
		label.Font = Enum.Font.FredokaOne
		label.TextScaled = true
		label.Text = text
		label.TextColor3 = color
		local stroke = Instance.new("UIStroke")
		stroke.Thickness = 2.5
		stroke.Color = Color3.fromRGB(14, 22, 48)
		stroke.Parent = label
		label.Parent = gui
		return label
	end

	line(model:GetAttribute("EggName") or "Frostmane Egg", 1, 0.5, WHITE)
	local rarity = line(model:GetAttribute("Rarity") or "Secret", 2, 0.42, WHITE)
	local gradient = Instance.new("UIGradient")
	gradient.Rotation = 90 -- vertical, icy cyan to violet (brief 5.3)
	gradient.Color = ColorSequence.new({
		ColorSequenceKeypoint.new(0, Color3.fromRGB(170, 245, 255)),
		ColorSequenceKeypoint.new(0.5, ICE),
		ColorSequenceKeypoint.new(1, VIOLET),
	})
	gradient.Parent = rarity
	if priceText then
		line(priceText, 3, 0.36, Color3.fromRGB(110, 230, 90))
	end
	gui.Parent = model
	return gui
end

local eggHandles = setmetatable({}, { __mode = "k" })

--[[ Frostmane Egg idle: slow spin and bob over the nest, crown sparkles,
     pulsing cracks, rising frost motes and the name/rarity label.
     options = { PriceText = "$7.8B", ShowLabel = true } ]]
function FrostmaneVFX.StartEgg(model: Model, options)
	options = options or {}
	local handle = newHandle()
	local core = model:FindFirstChild("EggCore", true)
	addGlow(handle, model, attachmentAt(model, "EggCenter"))

	if core then
		local base = core.CFrame
		local t, angle = 0, 0
		table.insert(handle.connections, RunService.Heartbeat:Connect(function(dt)
			t += dt
			angle += dt * 0.6
			core.CFrame = base * CFrame.new(0, math.sin(t * 1.6) * 0.22, 0) * CFrame.Angles(0, angle, 0)
		end))
		handle.coreBase = base
	end

	local crown = attachmentAt(model, "Crown")
	if crown then
		track(handle, emitter(crown, "Sparkle", {
			Rate = 6,
			Lifetime = NumberRange.new(0.5, 0.9),
			Speed = NumberRange.new(0.5, 1.5),
			SpreadAngle = Vector2.new(180, 180),
			Size = seq(0.7, 0),
			Color = ColorSequence.new(ICE, VIOLET),
		}))
	end
	local rim = attachmentAt(model, "NestRim")
	if rim then
		track(handle, emitter(rim, "FrostMote", {
			Rate = 6,
			Lifetime = NumberRange.new(1.5, 2.5),
			Speed = NumberRange.new(0.6, 1.4),
			EmissionDirection = Enum.NormalId.Top,
			SpreadAngle = Vector2.new(70, 70),
			Acceleration = Vector3.new(0, 0.4, 0),
			Size = seq(0.4, 0),
			Color = ColorSequence.new(WHITE, ICE),
		}))
	end
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") and baseName(d) == "Cracks" then
			pulse(handle, d, PULSE, { Color = Color3.fromRGB(215, 255, 255) })
		end
	end
	if options.ShowLabel ~= false and (crown or core) then
		eggLabel(handle, model, crown or core, options.PriceText)
	end

	eggHandles[model] = handle
	return handle
end

--[[ Hatch: the shell wobbles harder and harder while the cracks blaze, then a
     white flash and burst: shell shards fly out, a crystal burst and an ice
     nova ring expand, and snowflakes, glints and a shockwave fire.
     onReveal(centre: Vector3) runs at the burst, so spawn the monster there.
     Yields for about 2.4 s. ]]
function FrostmaneVFX.PlayHatch(model: Model, onReveal: ((Vector3) -> ())?)
	local idle = eggHandles[model]
	if idle then
		idle.Stop()
		eggHandles[model] = nil
		local core = model:FindFirstChild("EggCore", true)
		if core and idle.coreBase then
			core.CFrame = idle.coreBase
		end
	end

	local core = model:FindFirstChild("EggCore", true)
	local centre = if core then core.Position else model:GetPivot().Position
	local shellParts, cracks = {}, {}
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") then
			local key = baseName(d)
			if EGG_SHELL_PARTS[key] then
				table.insert(shellParts, d)
			end
			if key == "Cracks" then
				table.insert(cracks, d)
			end
		end
	end

	local light = Instance.new("PointLight")
	light.Color = ICE
	light.Range = 18
	light.Brightness = 1
	light.Parent = core or model.PrimaryPart

	-- 1) Wobble, building up over ~1.5 s.
	if core then
		local base = core.CFrame
		local t, duration = 0, 1.5
		while t < duration do
			local dt = RunService.Heartbeat:Wait()
			t += dt
			local k = t / duration
			local amp = math.rad(4 + 14 * k * k)
			local s = math.sin(t * (14 + 16 * k))
			core.CFrame = base * CFrame.Angles(s * amp, 0, math.cos(t * 11) * amp * 0.6)
			light.Brightness = 1 + 5 * k
			for _, c in cracks do
				c.Color = Color3.fromRGB(95, 244, 255):Lerp(WHITE, k)
			end
		end
		core.CFrame = base
	end

	-- 2) Flash.
	local flash = Instance.new("Highlight")
	flash.Adornee = model
	flash.FillColor = WHITE
	flash.FillTransparency = 0
	flash.OutlineTransparency = 1
	flash.DepthMode = Enum.HighlightDepthMode.Occluded
	flash.Parent = model
	TweenService:Create(flash, TweenInfo.new(0.35, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), { FillTransparency = 1 }):Play()
	Debris:AddItem(flash, 0.4)
	light.Brightness = 10
	TweenService:Create(light, TweenInfo.new(0.8, Enum.EasingStyle.Quad), { Brightness = 0 }):Play()
	Debris:AddItem(light, 0.9)

	-- 3) Burst.
	for _, p in shellParts do
		p.Transparency = 1
	end
	local meshes = ReplicatedStorage:FindFirstChild("VFXMeshes")
	local set = meshes and meshes:FindFirstChild("FrostmaneVFXMeshes")
	if set then
		for _, template in set:GetChildren() do
			if template:IsA("BasePart") and string.sub(template.Name, 1, 5) == "Shard" then
				local shard = template:Clone()
				shard.Anchored = true
				shard.CanCollide = false
				shard.CFrame = CFrame.new(centre + Vector3.new(math.random() - 0.5, math.random() - 0.3, math.random() - 0.5) * 2)
				shard.Parent = workspace
				local dir = (Vector3.new(math.random() - 0.5, 0, math.random() - 0.5).Unit * math.random(5, 9))
				local apex = shard.CFrame * CFrame.Angles(math.random() * 6, math.random() * 6, math.random() * 6)
				TweenService:Create(shard, TweenInfo.new(0.35, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
					CFrame = apex + dir * 0.6 + Vector3.new(0, 3, 0),
				}):Play()
				task.delay(0.35, function()
					TweenService:Create(shard, TweenInfo.new(0.55, Enum.EasingStyle.Quad, Enum.EasingDirection.In), {
						CFrame = apex + dir + Vector3.new(0, -2.6, 0), -- land around the nest base
						Transparency = 1,
					}):Play()
				end)
				Debris:AddItem(shard, 1.0)
			elseif template:IsA("BasePart") and (template.Name == "CrystalBurst" or template.Name == "NovaRing") then
				local fx = template:Clone()
				local target = fx.Size
				local isRing = template.Name == "NovaRing"
				fx.Anchored = true
				fx.CanCollide = false
				fx.Size = target * 0.15
				fx.CFrame = CFrame.new(if isRing then Vector3.new(centre.X, centre.Y - 2.6, centre.Z) else centre)
				fx.Parent = workspace
				TweenService:Create(fx, TweenInfo.new(if isRing then 0.6 else 0.45, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {
					Size = target * (if isRing then 1.6 else 1.3),
				}):Play()
				TweenService:Create(fx, TweenInfo.new(0.5, Enum.EasingStyle.Quad, Enum.EasingDirection.In, 0, false, 0.35), {
					Transparency = 1,
				}):Play()
				Debris:AddItem(fx, 1.0)
			end
		end
	else
		warnOnce("meshes", "ReplicatedStorage.VFXMeshes.FrostmaneVFXMeshes not found; mesh burst skipped.")
	end

	local burst = burstAttachment(centre, 3)
	local function fire(textureName: string, count: number, props)
		props.Enabled = false
		local e = emitter(burst, textureName, props)
		if e then
			e:Emit(count)
		end
	end
	fire("BlockSnowflake", 28, {
		Lifetime = NumberRange.new(0.9, 1.6),
		Speed = NumberRange.new(10, 18),
		SpreadAngle = Vector2.new(180, 180),
		Drag = 3,
		Acceleration = Vector3.new(0, -6, 0),
		RotSpeed = NumberRange.new(-180, 180),
		Size = seq(0.8, 0.2),
		Color = ColorSequence.new(WHITE, ICE),
	})
	fire("Sparkle", 20, {
		Lifetime = NumberRange.new(0.4, 0.8),
		Speed = NumberRange.new(6, 14),
		SpreadAngle = Vector2.new(180, 180),
		Size = seq(1.4, 0),
		Color = ColorSequence.new(ICE, VIOLET),
	})
	fire("IceShard", 14, {
		Lifetime = NumberRange.new(0.5, 0.9),
		Speed = NumberRange.new(14, 22),
		SpreadAngle = Vector2.new(180, 180),
		Drag = 4,
		Size = seq(1.2, 0.4),
		Orientation = Enum.ParticleOrientation.VelocityParallel,
		Color = ColorSequence.new(ICE),
	})
	fire("ShockwaveRing", 1, {
		Lifetime = NumberRange.new(0.45, 0.45),
		Speed = NumberRange.new(0, 0),
		Size = seq(1, 16),
		Transparency = seq(0, 1),
		Color = ColorSequence.new(ICE),
	})

	if onReveal then
		task.spawn(onReveal, centre)
	end
	task.wait(0.9)
end

return FrostmaneVFX
