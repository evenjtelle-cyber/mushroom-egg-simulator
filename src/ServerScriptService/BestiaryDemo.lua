--[[
	BestiaryDemo  (Script)
	Location: ServerScriptService.BestiaryDemo

	A test so you can see the bestiary working in Play mode:
	  * every egg in Workspace.Bestiary rocks on the ground and shows its label;
	  * click an egg: it hatches and a monster from its family (picked with the
	    HatchChance odds) appears next to it, idling with its effects;
	  * 10 seconds later the monster goes away and the egg is ready again;
	  * monsters you put in Workspace.Bestiary just idle there (a showcase).

	Needs (see docs/Guide_Bestiary.md):
	  Workspace.Bestiary         folder with assembled eggs (and any showcase monsters)
	  ServerStorage.Bestiary     folder with the assembled monsters used as hatch templates
	  ReplicatedStorage.CreatureKit, BestiaryData and VFXLibrary
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local K = require(ReplicatedStorage:WaitForChild("CreatureKit"))

local SPAWN_DISTANCE = 4
local SHOW_SECONDS = 10
local LUCK = 1 -- try 3 to see the rarer monsters more often

local display = workspace:WaitForChild("Bestiary")
local templates = ServerStorage:WaitForChild("Bestiary")

local function setUpEgg(egg: Model)
	K.StartEgg(egg) -- PlayHatch stops these idle effects by itself

	local clicker = Instance.new("ClickDetector")
	clicker.MaxActivationDistance = 60
	clicker.Parent = egg -- on the model, so clicking any part of the egg counts

	local busy = false
	clicker.MouseClick:Connect(function()
		if busy then
			return
		end
		busy = true

		local asset = K.RollHatch(egg:GetAttribute("Family"), LUCK)
		local template = asset and templates:FindFirstChild(asset)
		if not template then
			warn("[BestiaryDemo] No template ServerStorage.Bestiary." .. tostring(asset))
		end

		local monster, effects
		K.PlayHatch(egg, function(centre)
			if not template then
				return
			end
			monster = template:Clone()
			local eggBox, eggSize = egg:GetBoundingBox()
			local floorY = eggBox.Position.Y - eggSize.Y / 2
			local box, size = monster:GetBoundingBox()
			local away = eggSize.X / 2 + size.X / 2 + SPAWN_DISTANCE
			local target = Vector3.new(centre.X + away, floorY + size.Y / 2, centre.Z)
			monster:PivotTo(monster:GetPivot() + (target - box.Position))
			monster.Parent = workspace
			effects = K.StartMonster(monster)
			print(string.format("[BestiaryDemo] %s hatched a %s (%s)", egg.Name,
				monster:GetAttribute("MonsterName"), monster:GetAttribute("Rarity")))
		end)

		task.wait(SHOW_SECONDS)
		if effects then
			effects.Stop()
		end
		if monster then
			monster:Destroy()
		end
		K.ResetEgg(egg)
		K.StartEgg(egg)
		busy = false
	end)
end

for _, model in display:GetChildren() do
	if model:IsA("Model") then
		local kind = model:GetAttribute("Kind")
		if kind == "Egg" then
			setUpEgg(model)
		elseif kind == "Monster" then
			K.StartMonster(model)
		else
			warn("[BestiaryDemo] " .. model:GetFullName() .. " is not assembled; run CreatureKit.Assemble on it first.")
		end
	end
end
