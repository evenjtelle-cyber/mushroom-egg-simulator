--[[
	StarterSet  (ModuleScript)
	Location: ReplicatedStorage.StarterSet

	Studio assembly and runtime effects for the Wood-tier starter set made by
	blender/GenerateStarterSet.py:
	  Mossbark Hatchet  starter axe, smooth cartoon style   MossbarkHatchet.glb
	  Mossbark Egg      most common egg (blocky, no nest)   MossbarkEgg.glb
	  Mosscap Toad      its first Common monster (blocky)   MosscapToad.glb
	  Hatch shards                                          MossbarkVFXMeshes.glb -> ReplicatedStorage.VFXMeshes

	1) ONE-TIME SETUP in Studio (Edit mode, command bar, one line):
	     local S = require(game.ReplicatedStorage.StarterSet); S.Assemble(workspace.MossbarkEgg, "Egg"); S.Assemble(workspace.MosscapToad, "Toad"); S.MakeTool(workspace.MossbarkHatchet)
	   Assemble colours and studs the blocky models, welds them and sets attributes.
	   MakeTool turns the imported axe into a Tool in StarterPack. It sets the
	   grip, adds a TipAttachment and a SwingTrail, and sets the attributes
	   (WeaponType = "Axe"), so AnimationController plays the combo with it.

	2) RUNTIME:
	     local handle = S.StartToad(toadModel)      -- idle hops, spores, dust on landing
	     local handle = S.StartEgg(eggModel)        -- rocks on the ground, falling leaves, spores, label
	     handle.Stop()
	     S.PlayHatch(eggModel, function(centre) spawnToad(centre) end)
	     S.ResetEgg(eggModel)
]]

local Debris = game:GetService("Debris")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local StarterPack = game:GetService("StarterPack")
local TweenService = game:GetService("TweenService")

local VFXLibrary = require(ReplicatedStorage:WaitForChild("VFXLibrary"))

local StarterSet = {}

-- Mirrors PALETTE in blender/GenerateStarterSet.py (sRGB hex).
StarterSet.PALETTE = {
	EggShell = "#7A5230",
	EggShellLight = "#9A6B3F",
	EggMoss = "#4F8A2E",
	EggLeaf = "#7CC242",
	EggLeafLight = "#B5E36A",
	EggSprout = "#5FA83A",
	EggShroom = "#E5402F",
	EggShroomSpots = "#FFF7EC",
	ToadBody = "#6DBE45",
	ToadBelly = "#F1E7C2",
	ToadMoss = "#4F8A2E",
	ToadToes = "#8ED160",
	ToadCap = "#E5402F",
	ToadSpots = "#FFF7EC",
	ToadEyes = "#FFFFFF",
	ToadPupils = "#1B1B1B",
	ToadMouth = "#3A1F14",
	ToadCheeks = "#FF8FA3",
}

-- Small face parts stay smooth (studs would make the eyes look noisy).
local NO_STUDS = { ToadEyes = true, ToadPupils = true, ToadMouth = true }

-- Every part of the egg; all of them hide when it hatches.
local EGG_SHELL_PARTS = {
	EggShell = true, EggShellLight = true, EggMoss = true, EggLeaf = true,
	EggLeafLight = true, EggSprout = true, EggShroom = true, EggShroomSpots = true,
}

StarterSet.ATTRIBUTES = {
	Toad = {
		MonsterName = "Mosscap Toad",
		Rarity = "Common",
		Tier = "Wood",
		SourceEgg = "Mossbark Egg",
		HatchChance = 0.6,
		CashPerSecond = 1,
		StrengthMultiplier = 1.05,
		LuckMultiplier = 1,
		IndexReward = 50,
		IdleHover = false,
	},
	Egg = {
		EggName = "Mossbark Egg",
		Rarity = "Common",
		Tier = "Wood",
		TopDrop = "Mosscap Toad",
		TopDropChance = 0.6,
	},
	Hatchet = {
		WeaponType = "Axe",
		Tier = "Wood",
		Rarity = "Common",
		Damage = 1,
		StrengthPerClick = 1,
		CashPrice = 0,
		AttackSpeed = 1,
	},
}

-- Where the hand holds the axe, in studs up from the bottom of the Handle
-- (the bottom includes the little pommel spike).
StarterSet.GRIP_FROM_BOTTOM = 0.95
-- Turn the axe around the handle if the blade faces the wrong way in-hand
-- (try 180, then 90 / -90).
StarterSet.GRIP_YAW_DEGREES = 0

local LEAF = Color3.fromRGB(150, 220, 90)
local SPORE = Color3.fromRGB(205, 255, 150)
local WHITE = Color3.new(1, 1, 1)

----------------------------------------------------------------------
-- Helpers
----------------------------------------------------------------------
local warned = {}
local function warnOnce(key: string, message: string)
	if not warned[key] then
		warned[key] = true
		warn("[StarterSet] " .. message)
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
	e.LightEmission = 0.4
	e.LightInfluence = 0.3
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

local function attachmentAt(model: Instance, name: string): Attachment?
	local found = model:FindFirstChild(name, true)
	return if found and found:IsA("Attachment") then found else nil
end

local function collectSockets(model: Instance)
	local sockets = {}
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") and string.sub(d.Name, 1, 7) == "Socket_" then
			table.insert(sockets, d)
		end
	end
	return sockets
end

local function socketsToAttachments(sockets, pickParent)
	for _, s in sockets do
		local name = string.sub(s.Name, 8)
		local parent = pickParent(name)
		local old = parent:FindFirstChild(name)
		if old and old:IsA("Attachment") then
			old:Destroy()
		end
		local a = Instance.new("Attachment")
		a.Name = name
		a.Parent = parent
		a.WorldPosition = s.Position
		s:Destroy()
	end
end

----------------------------------------------------------------------
-- 1) Studio setup
----------------------------------------------------------------------
local function applyLook(part: BasePart, key: string)
	local hex = StarterSet.PALETTE[key]
	if hex then
		part.Color = Color3.fromHex(hex)
	end
	part.Material = Enum.Material.SmoothPlastic
	part.Transparency = 0
	for _, child in part:GetChildren() do
		if child:IsA("SurfaceAppearance") then
			child:Destroy()
		end
	end
	if NO_STUDS[key] then
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
		warnOnce("sa", "SurfaceAppearance needs Studio (command bar, Edit mode): " .. tostring(err))
	end
end

-- Assemble(model, "Egg" | "Toad"). Safe to run again.
function StarterSet.Assemble(model: Model, kind: string)
	assert(kind == "Egg" or kind == "Toad", "kind must be \"Egg\" or \"Toad\"")
	local rootName = if kind == "Toad" then "ToadBody" else "EggShell"

	local parts = {}
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") and string.sub(d.Name, 1, 7) ~= "Socket_" and d.Name ~= "EggCore" then
			table.insert(parts, d)
		elseif d:IsA("WeldConstraint") and d.Name == "StarterWeld" then
			d:Destroy()
		end
	end
	local root = nil
	for _, p in parts do
		if baseName(p) == rootName then
			root = p
			break
		end
	end
	assert(root, "Assemble: no part named " .. rootName .. " in " .. model:GetFullName())

	local sockets = collectSockets(model)
	if kind == "Egg" then
		-- The egg sits on the ground with no nest. An invisible anchored core at
		-- its base centre is the root, so idle rocking and the hatch wobble
		-- pivot around the point that touches the ground.
		local core = model:FindFirstChild("EggCore", true)
		if not core then
			core = Instance.new("Part")
			core.Name = "EggCore"
			core.Size = Vector3.new(0.5, 0.5, 0.5)
			core.Transparency = 1
			core.CanCollide = false
			core.CanQuery = false
			core.Parent = model
		end
		local _, size = model:GetBoundingBox()
		local base = Vector3.new(root.Position.X, root.Position.Y - size.Y / 2, root.Position.Z)
		for _, s in sockets do
			if s.Name == "Socket_Ground" then
				base = s.Position
			end
		end
		core.CFrame = CFrame.new(base)
		root.CanCollide = true -- the shell itself stays solid
		root = core
	end

	root.Anchored = true
	for _, p in parts do
		applyLook(p, baseName(p))
		if p ~= root then
			p.Anchored = false
			p.Massless = true
			if baseName(p) ~= "EggShell" then
				p.CanCollide = false
			end
			local weld = Instance.new("WeldConstraint")
			weld.Name = "StarterWeld"
			weld.Part0 = root
			weld.Part1 = p
			weld.Parent = p
		end
	end
	socketsToAttachments(sockets, function()
		return root
	end)

	for key, value in StarterSet.ATTRIBUTES[kind] do
		if model:GetAttribute(key) == nil then
			model:SetAttribute(key, value)
		end
	end
	model.PrimaryPart = root
	print(string.format("[StarterSet] Assembled %s (%d parts, %d sockets)", model.Name, #parts, #sockets))
end

--[[ MakeTool(importedModel, parent?) -> Tool
     Converts the imported MossbarkHatchet model (MeshParts Handle + Head and
     Socket_ markers) into a Tool, by default in StarterPack. ]]
function StarterSet.MakeTool(model: Instance, parent: Instance?): Tool
	local handle = model:FindFirstChild("Handle", true)
	local head = model:FindFirstChild("Head", true)
	assert(handle and handle:IsA("BasePart"), "MakeTool: no part named Handle in " .. model:GetFullName())
	assert(head and head:IsA("BasePart"), "MakeTool: no part named Head in " .. model:GetFullName())
	local sockets = collectSockets(model)

	local tool = Instance.new("Tool")
	tool.Name = "Mossbark Hatchet"
	tool.CanBeDropped = false
	tool.RequiresHandle = true

	for _, p in { handle, head } do
		p.Anchored = false
		p.CanCollide = false
		p.Parent = tool
	end
	head.Massless = true
	local weld = Instance.new("WeldConstraint")
	weld.Part0 = handle
	weld.Part1 = head
	weld.Parent = head

	socketsToAttachments(sockets, function()
		return head
	end)
	local tip = head:FindFirstChild("Tip")
	if tip then
		tip.Name = "TipAttachment" -- AnimationController puts the impact burst here
	end

	local top, bottom = head:FindFirstChild("TrailTop"), head:FindFirstChild("TrailBottom")
	if top and bottom then
		local trail = Instance.new("Trail")
		trail.Name = "SwingTrail" -- AnimationController switches it on during swings
		trail.Attachment0 = top
		trail.Attachment1 = bottom
		trail.Enabled = false
		trail.Lifetime = 0.16
		trail.FaceCamera = true
		trail.LightEmission = 0.5
		trail.Color = ColorSequence.new(WHITE, Color3.fromRGB(200, 240, 170))
		trail.Transparency = NumberSequence.new(0.35, 1)
		trail.Texture = texture("SwingStreak") or ""
		trail.Parent = head
	end

	-- The hand holds the haft just above the pommel; the handle's long axis is Y.
	local length = handle.Size.Y
	tool.Grip = CFrame.new(0, -(length / 2 - StarterSet.GRIP_FROM_BOTTOM), 0)
		* CFrame.Angles(0, math.rad(StarterSet.GRIP_YAW_DEGREES), 0)

	for key, value in StarterSet.ATTRIBUTES.Hatchet do
		tool:SetAttribute(key, value)
	end
	tool.Parent = parent or StarterPack
	if model:IsA("Model") and #model:GetChildren() == 0 then
		model:Destroy()
	end
	print("[StarterSet] Made Tool " .. tool:GetFullName())
	return tool
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

--[[ Mosscap Toad idle: a happy hop every couple of seconds (squash on landing
     with a little dust puff) and spores drifting off its back. ]]
function StarterSet.StartToad(model: Model)
	local handle = newHandle()
	local root = model.PrimaryPart
	local back = attachmentAt(model, "Back")
	local feet = attachmentAt(model, "Feet")

	if back then
		track(handle, emitter(back, "Spore", {
			Rate = 2.5,
			Lifetime = NumberRange.new(1.6, 2.6),
			Speed = NumberRange.new(0.4, 1),
			EmissionDirection = Enum.NormalId.Top,
			SpreadAngle = Vector2.new(40, 40),
			Acceleration = Vector3.new(0, 0.3, 0),
			Size = seq(0.35, 0),
			Color = ColorSequence.new(SPORE),
		}))
	end
	local dust = feet and track(handle, emitter(feet, "DustPuff", {
		Enabled = false,
		Lifetime = NumberRange.new(0.4, 0.6),
		Speed = NumberRange.new(2, 3.5),
		SpreadAngle = Vector2.new(180, 5),
		Drag = 6,
		Size = seq(0.8, 1.6),
		Transparency = seq(0.3, 1),
		LightEmission = 0,
		Color = ColorSequence.new(Color3.fromRGB(200, 185, 150)),
	}))

	if root then
		local base = root.CFrame
		local t = 0
		local hopEvery, hopTime, hopHeight = 2.4, 0.42, 0.9
		table.insert(handle.connections, RunService.Heartbeat:Connect(function(dt)
			t += dt
			local phase = t % hopEvery
			local y, squash = 0, 0
			if phase < hopTime then
				local s = phase / hopTime
				y = hopHeight * 4 * s * (1 - s) -- parabola
			elseif phase < hopTime + 0.18 then
				squash = math.sin((phase - hopTime) / 0.18 * math.pi) -- landing squash
			end
			if dust and phase >= hopTime and phase - dt < hopTime then
				dust:Emit(4)
			end
			root.CFrame = base * CFrame.new(0, y - squash * 0.12, 0) * CFrame.Angles(math.rad(-squash * 4), 0, 0)
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
	gui.Size = UDim2.fromScale(6, if priceText then 2.8 else 2.1)
	gui.StudsOffsetWorldSpace = Vector3.new(0, 1.8, 0)
	gui.LightInfluence = 0
	gui.MaxDistance = 100

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
		stroke.Color = Color3.fromRGB(30, 24, 16)
		stroke.Parent = label
		label.Parent = gui
		return label
	end

	line(model:GetAttribute("EggName") or "Mossbark Egg", 1, 0.5, WHITE)
	local rarity = line(model:GetAttribute("Rarity") or "Common", 2, 0.42, WHITE)
	local gradient = Instance.new("UIGradient")
	gradient.Rotation = 90 -- Common: soft grey-white to leaf green
	gradient.Color = ColorSequence.new(Color3.fromRGB(235, 240, 230), Color3.fromRGB(150, 210, 110))
	gradient.Parent = rarity
	if priceText then
		line(priceText, 3, 0.36, Color3.fromRGB(110, 230, 90))
	end
	gui.Parent = model
end

local eggHandles = setmetatable({}, { __mode = "k" })

--[[ Mossbark Egg idle: it sits on the ground and gives a little rock from
     side to side every few seconds (pivoting at its base), with leaves
     drifting off the moss cap, spores around the sprout and the label.
     options = { PriceText = "$25", ShowLabel = true } ]]
function StarterSet.StartEgg(model: Model, options)
	options = options or {}
	local handle = newHandle()
	local core = model:FindFirstChild("EggCore", true)
	if core then
		local base = core.CFrame
		local t = 0
		local every, duration, maxTilt = 3.2, 0.9, math.rad(7)
		table.insert(handle.connections, RunService.Heartbeat:Connect(function(dt)
			t += dt
			local phase = t % every
			local tilt = 0
			if phase < duration then
				local s = phase / duration
				tilt = math.sin(s * math.pi * 3) * (1 - s) * maxTilt -- three settling rocks
			end
			core.CFrame = base * CFrame.Angles(0, 0, tilt)
		end))
		handle.coreBase = base
	end
	local crown = attachmentAt(model, "Crown")
	local centre = attachmentAt(model, "EggCenter")
	if crown then
		track(handle, emitter(crown, "Spore", {
			Rate = 3,
			Lifetime = NumberRange.new(1.2, 2),
			Speed = NumberRange.new(0.3, 0.8),
			SpreadAngle = Vector2.new(180, 180),
			Size = seq(0.3, 0),
			Color = ColorSequence.new(SPORE),
		}))
	end
	if centre then
		track(handle, emitter(centre, "LeafBit", {
			Rate = 0.8,
			Lifetime = NumberRange.new(2, 3),
			Speed = NumberRange.new(0.5, 1.2),
			SpreadAngle = Vector2.new(180, 30),
			Acceleration = Vector3.new(0, -1.2, 0),
			RotSpeed = NumberRange.new(-90, 90),
			Size = seq(0.4, 0.3),
			LightEmission = 0,
			Color = ColorSequence.new(LEAF),
		}))
	end
	if options.ShowLabel ~= false and (crown or core) then
		eggLabel(handle, model, crown or core, options.PriceText)
	end
	eggHandles[model] = handle
	return handle
end

--[[ Hatch: a building wobble, a soft flash, then the shell bursts into
     blocky shards with a leaf and dust burst. onReveal(centre) runs at the
     burst. Yields for about 1.9 s. ]]
function StarterSet.PlayHatch(model: Model, onReveal: ((Vector3) -> ())?)
	local idle = eggHandles[model]
	local core = model:FindFirstChild("EggCore", true)
	if idle then
		idle.Stop()
		eggHandles[model] = nil
		if core and idle.coreBase then
			core.CFrame = idle.coreBase
		end
	end
	local middle = attachmentAt(model, "EggCenter")
	local centre = if middle then middle.WorldPosition
		elseif core then core.Position + Vector3.new(0, 2, 0)
		else model:GetPivot().Position

	if core then
		local base = core.CFrame
		local t, duration = 0, 1.1
		while t < duration do
			t += RunService.Heartbeat:Wait()
			local k = t / duration
			local amp = math.rad(3 + 12 * k * k)
			core.CFrame = base * CFrame.Angles(math.sin(t * (12 + 14 * k)) * amp, 0, math.cos(t * 10) * amp * 0.6)
		end
		core.CFrame = base
	end

	local flash = Instance.new("Highlight")
	flash.Adornee = model
	flash.FillColor = WHITE
	flash.FillTransparency = 0.1
	flash.OutlineTransparency = 1
	flash.DepthMode = Enum.HighlightDepthMode.Occluded
	flash.Parent = model
	TweenService:Create(flash, TweenInfo.new(0.3), { FillTransparency = 1 }):Play()
	Debris:AddItem(flash, 0.35)

	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") and EGG_SHELL_PARTS[baseName(d)] then
			d.Transparency = 1
		end
	end

	local meshes = ReplicatedStorage:FindFirstChild("VFXMeshes")
	local set = meshes and meshes:FindFirstChild("MossbarkVFXMeshes")
	if set then
		for _, template in set:GetChildren() do
			if template:IsA("BasePart") and string.sub(template.Name, 1, 8) == "EggShard" then
				local shard = template:Clone()
				shard.Anchored = true
				shard.CanCollide = false
				shard.CFrame = CFrame.new(centre + Vector3.new(math.random() - 0.5, math.random() - 0.3, math.random() - 0.5) * 1.6)
				shard.Parent = workspace
				local dir = Vector3.new(math.random() - 0.5, 0, math.random() - 0.5).Unit * math.random(3, 6)
				local spun = shard.CFrame * CFrame.Angles(math.random() * 6, math.random() * 6, math.random() * 6)
				TweenService:Create(shard, TweenInfo.new(0.3, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
					CFrame = spun + dir * 0.6 + Vector3.new(0, 2.2, 0),
				}):Play()
				task.delay(0.3, function()
					TweenService:Create(shard, TweenInfo.new(0.5, Enum.EasingStyle.Quad, Enum.EasingDirection.In), {
						CFrame = spun + dir + Vector3.new(0, -1.6, 0),
						Transparency = 1,
					}):Play()
				end)
				Debris:AddItem(shard, 0.9)
			end
		end
	else
		warnOnce("meshes", "ReplicatedStorage.VFXMeshes.MossbarkVFXMeshes not found; shard burst skipped.")
	end

	local burst = Instance.new("Attachment")
	burst.Position = centre
	burst.Parent = workspace.Terrain
	Debris:AddItem(burst, 3)
	local function fire(textureName: string, count: number, props)
		props.Enabled = false
		local e = emitter(burst, textureName, props)
		if e then
			e:Emit(count)
		end
	end
	fire("LeafBit", 18, {
		Lifetime = NumberRange.new(0.9, 1.5),
		Speed = NumberRange.new(6, 11),
		SpreadAngle = Vector2.new(180, 180),
		Drag = 3,
		Acceleration = Vector3.new(0, -5, 0),
		RotSpeed = NumberRange.new(-200, 200),
		Size = seq(0.6, 0.35),
		LightEmission = 0,
		Color = ColorSequence.new(LEAF, Color3.fromRGB(110, 180, 70)),
	})
	fire("DustPuff", 8, {
		Lifetime = NumberRange.new(0.5, 0.8),
		Speed = NumberRange.new(4, 7),
		SpreadAngle = Vector2.new(180, 20),
		Drag = 5,
		Size = seq(1.2, 2.6),
		Transparency = seq(0.2, 1),
		LightEmission = 0,
		Color = ColorSequence.new(Color3.fromRGB(210, 195, 160)),
	})
	fire("Spore", 14, {
		Lifetime = NumberRange.new(0.6, 1.1),
		Speed = NumberRange.new(3, 6),
		SpreadAngle = Vector2.new(180, 180),
		Size = seq(0.5, 0),
		Color = ColorSequence.new(SPORE),
	})

	if onReveal then
		task.spawn(onReveal, centre)
	end
	task.wait(0.8)
end

-- Show the shell again after PlayHatch.
function StarterSet.ResetEgg(model: Model)
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") and EGG_SHELL_PARTS[baseName(d)] then
			d.Transparency = 0
		end
	end
end

return StarterSet
