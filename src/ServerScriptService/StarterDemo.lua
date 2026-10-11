--[[
	StarterDemo  (Script)
	Location: ServerScriptService.StarterDemo

	A test so you can see the starter set working in Play mode:
	  * the Mossbark Egg in Workspace rocks on the ground, drops leaves and shows its label;
	  * click it: it wobbles and bursts, and a Mosscap Toad hops out next to it;
	  * 10 seconds later the toad goes away and the egg is ready again.
	  * The Mossbark Hatchet is in your backpack (StarterPack) after setup;
	    equip it and click to chop through the 4-hit combo.

	Needs (see docs/Guide_StarterSet.md):
	  Workspace.MossbarkEgg       the assembled egg
	  ServerStorage.MosscapToad   the assembled toad (moved out of Workspace)
	  ReplicatedStorage.StarterSet and ReplicatedStorage.VFXLibrary
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local S = require(ReplicatedStorage:WaitForChild("StarterSet"))

local SPAWN_DISTANCE = 7
local SHOW_SECONDS = 10

local egg = workspace:WaitForChild("MossbarkEgg")
local toadTemplate = ServerStorage:WaitForChild("MosscapToad")

S.StartEgg(egg, { PriceText = "$25" }) -- PlayHatch stops these idle effects by itself

local clicker = Instance.new("ClickDetector")
clicker.MaxActivationDistance = 40
clicker.Parent = egg -- on the model, so clicking any part of the egg counts

local busy = false
clicker.MouseClick:Connect(function()
	if busy then
		return
	end
	busy = true

	local toad, toadEffects
	S.PlayHatch(egg, function(centre)
		toad = toadTemplate:Clone()
		local eggBox, eggSize = egg:GetBoundingBox()
		local floorY = eggBox.Position.Y - eggSize.Y / 2
		local box, size = toad:GetBoundingBox()
		local target = Vector3.new(centre.X + SPAWN_DISTANCE, floorY + size.Y / 2, centre.Z)
		toad:PivotTo(toad:GetPivot() + (target - box.Position))
		toad.Parent = workspace
		toadEffects = S.StartToad(toad)
	end)

	task.wait(SHOW_SECONDS)
	if toadEffects then
		toadEffects.Stop()
	end
	if toad then
		toad:Destroy()
	end
	S.ResetEgg(egg)
	S.StartEgg(egg, { PriceText = "$25" })
	busy = false
end)
