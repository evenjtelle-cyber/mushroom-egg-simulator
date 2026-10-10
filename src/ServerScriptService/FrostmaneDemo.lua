--[[
	FrostmaneDemo  (Script)
	Location: ServerScriptService.FrostmaneDemo

	A test so you can see the Frostmane set working in Play mode:
	  * the egg in Workspace spins, bobs, sparkles and shows its label;
	  * click the egg: it wobbles, flashes and bursts, then a Frostmane Wyrm
	    appears next to it with its idle effects;
	  * 12 seconds later the dragon goes away and the egg is ready again.

	Needs (see docs/Guide_AddFrostmaneToRoblox.md):
	  Workspace.FrostmaneEgg       the assembled egg
	  ServerStorage.FrostmaneWyrm  the assembled dragon (moved out of Workspace)
	  ReplicatedStorage.FrostmaneVFX and ReplicatedStorage.VFXLibrary

	This is only a demo. Your real hatching code (EggIncubatorService) can call
	the same three functions: StartEgg, PlayHatch and StartWyrm.
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local FX = require(ReplicatedStorage:WaitForChild("FrostmaneVFX"))

local SPAWN_DISTANCE = 26 -- studs between the egg and the dragon that hatches
local SHOW_SECONDS = 12

local egg = workspace:WaitForChild("FrostmaneEgg")
local wyrmTemplate = ServerStorage:WaitForChild("FrostmaneWyrm")

FX.StartEgg(egg, { PriceText = "$7.8B" }) -- PlayHatch stops these idle effects by itself

local clicker = Instance.new("ClickDetector")
clicker.MaxActivationDistance = 60
clicker.Parent = egg -- on the model, so clicking any part of the egg or nest counts

local busy = false
clicker.MouseClick:Connect(function()
	if busy then
		return
	end
	busy = true

	local wyrm, wyrmEffects
	FX.PlayHatch(egg, function(centre)
		wyrm = wyrmTemplate:Clone()
		-- Stand the dragon on the same floor as the egg, a little to the side.
		local eggBox, eggSize = egg:GetBoundingBox()
		local floorY = eggBox.Position.Y - eggSize.Y / 2
		local box, size = wyrm:GetBoundingBox()
		local target = Vector3.new(centre.X + SPAWN_DISTANCE, floorY + size.Y / 2, centre.Z)
		wyrm:PivotTo(wyrm:GetPivot() + (target - box.Position))
		wyrm.Parent = workspace
		wyrmEffects = FX.StartWyrm(wyrm)
	end)

	task.wait(SHOW_SECONDS)
	if wyrmEffects then
		wyrmEffects.Stop()
	end
	if wyrm then
		wyrm:Destroy()
	end
	FX.ResetEgg(egg)
	FX.StartEgg(egg, { PriceText = "$7.8B" })
	busy = false
end)
