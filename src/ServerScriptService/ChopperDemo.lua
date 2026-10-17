--[[
	ChopperDemo  (Script)
	Location: ServerScriptService.ChopperDemo

	A test so you can try every chopper in Play mode: each player gets a copy
	of every Tool in ReplicatedStorage.Choppers, in shop order (hotbar keys
	1-9). Equip one and click to swing; with AnimationController installed you
	get the 4-hit combo and the coloured swing trail.

	Delete or disable this script when your shop gives choppers out instead.
	Needs: ReplicatedStorage.ChopperKit, ChopperData and the Choppers folder
	made by ChopperKit.SetupAll() (see docs/Guide_Choppers.md).
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local K = require(ReplicatedStorage:WaitForChild("ChopperKit"))

local function giveAll(player: Player)
	for _, entry in K.ShopList() do
		if entry.Source == "Choppers" then
			K.GiveTool(player, entry.Asset)
		end
	end
end

local function onPlayer(player: Player)
	player.CharacterAdded:Connect(function()
		giveAll(player) -- the Backpack empties on every respawn
	end)
	if player.Character then
		giveAll(player)
	end
end

Players.PlayerAdded:Connect(onPlayer)
for _, player in Players:GetPlayers() do
	onPlayer(player)
end
