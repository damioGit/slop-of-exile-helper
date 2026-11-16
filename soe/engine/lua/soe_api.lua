-- Thin, stable API over PoB internals. Python calls only these, so PoB updates break one file.
soe = {}
local json = require("dkjson")

function soe.recalc()
	build.buildFlag = true
	runCallback("OnFrame")
end

local function scalars(out)
	local res = {}
	for k, v in pairs(out) do
		local t = type(v)
		if t == "number" or t == "boolean" or t == "string" then res[k] = v end
	end
	return res
end

-- ---- character -------------------------------------------------------------
function soe.set_class(className, ascendName)
	local spec = build.spec
	for id, cls in pairs(spec.tree.classes) do
		if cls.name == className then
			spec:SelectClass(id)
			if ascendName then
				for aid, asc in pairs(cls.classes) do
					if asc.name == ascendName then spec:SelectAscendClass(aid) end
				end
			end
			spec:BuildAllDependsAndPaths()
			soe.recalc()
			return true
		end
	end
	return false
end

function soe.set_level(level)
	build.characterLevel = level
	build.characterLevelAutoMode = false
	soe.recalc()
end

-- ---- passive tree ------------------------------------------------------------
-- Allocate a node plus the shortest path to it. Returns points spent, or nil.
function soe.alloc_node(nodeId)
	local spec = build.spec
	local node = spec.nodes[nodeId]
	if not node or node.alloc or not node.path then return nil end
	local cost = #node.path
	spec:AllocNode(node)
	soe.recalc()
	return cost
end

function soe.dealloc_node(nodeId)
	local node = build.spec.nodes[nodeId]
	if not node or not node.alloc then return false end
	build.spec:DeallocNode(node)
	soe.recalc()
	return true
end

-- Reachable unallocated nodes of a type ("Notable", "Keystone", "Normal"), cheapest path first.
function soe.reachable(nodeType, limit)
	local out = {}
	for id, node in pairs(build.spec.nodes) do
		if not node.alloc and node.path and node.type == nodeType and not node.ascendancyName then
			out[#out + 1] = { id = id, name = node.dn, cost = #node.path }
		end
	end
	table.sort(out, function(a, b)
		if a.cost ~= b.cost then return a.cost < b.cost end
		return a.id < b.id
	end)
	local res = {}
	for i = 1, math.min(limit or #out, #out) do res[i] = out[i] end
	return res
end

function soe.allocated_count()
	local n = 0
	for _, node in pairs(build.spec.allocNodes) do
		if node.type ~= "ClassStart" and node.type ~= "AscendClassStart" then n = n + 1 end
	end
	return n
end

function soe.node_path(nodeId)
	local node = build.spec.nodes[nodeId]
	local res = {}
	if not node or not node.path then return res end
	for i, p in ipairs(node.path) do res[i] = p.id end
	return res
end

local function activeWeaponSet()
	return build.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1
end

-- stat lines PoB cannot parse into modifiers (so they do nothing in calculations)
local function unsupportedLines(node)
	local res = {}
	for i, m in ipairs(node.mods or {}) do
		if (m.extra or not m.list or #m.list == 0) and node.sd and node.sd[i] then res[#res + 1] = node.sd[i] end
	end
	return res
end

local function nodeRecord(node)
	local stats = {}
	for i, s in ipairs(node.sd or {}) do stats[i] = s end
	local mode = node.allocMode or 0
	return { id = node.id, name = node.dn, type = node.type, alloc = node.alloc and true or false,
		cost = node.path and #node.path or nil, ascendancy = node.ascendancyName, stats = stats,
		weapon_set = mode, active = (not node.alloc) or mode == 0 or mode == activeWeaponSet(),
		unsupported = unsupportedLines(node) }
end

function soe.node_info(nodeId)
	local node = build.spec.nodes[nodeId]
	if not node then return nil end
	return nodeRecord(node)
end

function soe.allocated_nodes()
	local res = {}
	for _, node in pairs(build.spec.allocNodes) do
		if node.type ~= "ClassStart" and node.type ~= "AscendClassStart" then res[#res + 1] = nodeRecord(node) end
	end
	table.sort(res, function(a, b) return a.id < b.id end)
	return res
end

-- Passive point budget the way PoB's own warning computes it
function soe.points()
	local used, ascUsed, _, sockets, ws1, ws2 = build.spec:CountAllocNodes()
	local out = build.calcsTab.mainOutput or {}
	local extra = out.ExtraPoints or 0
	local maxWS = (build.maxWeaponSets or 0) + (out.PassivePointsToWeaponSetPoints or 0) + (out.WeaponSetPassivePoints or 0)
	local quest = build.acts and build.maxActs and build.acts[build.maxActs] and build.acts[build.maxActs].questPoints or 0
	local level = build.characterLevel or 1
	local normalUsed = used - math.min(ws1, ws2)
	local available = math.min(99 + (build.maxWeaponSets or 0) + extra, level - 1 + quest + extra + (build.maxWeaponSets or 0))
	return { used = normalUsed, available = available, unspent = available - normalUsed,
		weapon_set_1 = ws1, weapon_set_2 = ws2, weapon_set_max = maxWS,
		ascendancy_used = ascUsed, ascendancy_max = 8, jewel_sockets = sockets, active_weapon_set = activeWeaponSet() }
end

-- Enemy resistances as PoB's config (boss preset etc.) sets them
function soe.enemy_resists()
	local env = build.calcsTab.mainEnv
	local db = env and env.enemyDB
	if not db then return {} end
	local res = {}
	for _, e in ipairs({ "Fire", "Cold", "Lightning", "Chaos" }) do
		res[e] = db:Sum("BASE", nil, e .. "Resist")
	end
	res.Armour = db:Sum("BASE", nil, "Armour")
	res.Evasion = db:Sum("BASE", nil, "Evasion")
	return res
end

-- ---- what-if (never changes the build) -------------------------------------
-- spec JSON: { add_nodes = {ids}, with_path = bool, remove_nodes = {ids}, slot = "Weapon 1", item_raw = "..." }
-- slot without item_raw = empty that slot
function soe.whatif(specJson)
	local spec = json.decode(specJson) or {}
	local calcFunc = build.calcsTab:GetMiscCalculator()
	local override = {}
	local nodes = build.spec.nodes
	local points = 0
	if spec.add_nodes then
		override.addNodes = {}
		for _, id in ipairs(spec.add_nodes) do
			local node = nodes[id]
			if node and not node.alloc then
				local list = (spec.with_path and node.path) or { node }
				for _, p in ipairs(list) do
					if not p.alloc and not override.addNodes[p] then
						override.addNodes[p] = true
						points = points + 1
					end
				end
			end
		end
	end
	if spec.remove_nodes then
		override.removeNodes = {}
		for _, id in ipairs(spec.remove_nodes) do
			local node = nodes[id]
			if node and node.alloc then
				-- removing a node also drops everything that only connects through it
				local list = (node.depends and #node.depends > 0) and node.depends or { node }
				for _, d in ipairs(list) do
					if d.alloc and not override.removeNodes[d] then
						override.removeNodes[d] = true
						points = points - 1
					end
				end
			end
		end
	end
	if spec.slot then
		override.repSlotName = spec.slot
		if spec.item_raw then
			local item = new("Item", spec.item_raw)
			if not item.base then error("unknown item base") end
			item:BuildModList()
			override.repItem = item
		end
	end
	local res = scalars(calcFunc(override, false))
	res.__points = points
	return res
end

-- ---- skills / gems ----------------------------------------------------------
local function groupInfo(i, g)
	-- supports actually applied to at least one active skill of this group
	local applied = {}
	for _, s in ipairs(g.displaySkillList or {}) do
		for _, eff in ipairs(s.effectList or {}) do
			if eff.grantedEffect then applied[eff.grantedEffect] = true end
		end
	end
	local gems = {}
	for j, gem in ipairs(g.gemList) do
		local ge = gem.gemData and gem.gemData.grantedEffect
		local isSupport = (ge and ge.support) and true or false
		gems[j] = {
			name = gem.nameSpec, level = gem.level, quality = gem.quality,
			enabled = gem.enabled and true or false,
			support = isSupport,
			valid = gem.gemData ~= nil,
			applies = (not isSupport) or (ge ~= nil and applied[ge] == true),
		}
	end
	local skills = {}
	for j, s in ipairs(g.displaySkillList or {}) do
		skills[j] = s.activeEffect.grantedEffect.name
	end
	return { index = i, label = g.label, slot = g.slot, enabled = g.enabled and true or false,
		include_full_dps = g.includeInFullDPS and true or false, main = (build.mainSocketGroup == i),
		source = g.source, gems = gems, skills = skills }
end

function soe.list_groups()
	local res = {}
	for i, g in ipairs(build.skillsTab.socketGroupList) do res[i] = groupInfo(i, g) end
	return res
end

function soe.paste_gems(text)
	build.skillsTab:PasteSocketGroup(text)
	soe.recalc()
end

-- fields JSON: any of { name, level, quality, enabled }. gemIdx past the end adds a gem.
function soe.set_gem(groupIdx, gemIdx, fieldsJson)
	local g = build.skillsTab.socketGroupList[groupIdx]
	if not g then return false end
	local f = json.decode(fieldsJson)
	local gem = g.gemList[gemIdx]
	if not gem then
		gem = { nameSpec = "", level = 20, quality = 0, enabled = true, enableGlobal1 = true, enableGlobal2 = true, count = 1 }
		g.gemList[#g.gemList + 1] = gem
	end
	if f.name then gem.nameSpec = f.name; gem.gemId = nil; gem.skillId = nil end
	if f.level then gem.level = f.level end
	if f.quality then gem.quality = f.quality end
	if f.enabled ~= nil then gem.enabled = f.enabled end
	build.skillsTab:ProcessSocketGroup(g)
	soe.recalc()
	return gem.gemData ~= nil
end

function soe.remove_gem(groupIdx, gemIdx)
	local g = build.skillsTab.socketGroupList[groupIdx]
	if not g or not g.gemList[gemIdx] then return false end
	table.remove(g.gemList, gemIdx)
	build.skillsTab:ProcessSocketGroup(g)
	soe.recalc()
	return true
end

function soe.set_main(groupIdx, skillIdx)
	local g = build.skillsTab.socketGroupList[groupIdx]
	if not g then return false end
	build.mainSocketGroup = groupIdx
	g.mainActiveSkill = skillIdx or 1
	g.mainActiveSkillCalcs = skillIdx or 1
	soe.recalc()
	return true
end

-- DPS of every active skill in every enabled group; the main skill is restored afterwards
function soe.all_skill_dps()
	local res = {}
	local groups = build.skillsTab.socketGroupList
	local prevMain = build.mainSocketGroup
	local prev = {}
	for i, g in ipairs(groups) do prev[i] = { g.mainActiveSkill, g.mainActiveSkillCalcs } end
	for i, g in ipairs(groups) do
		if g.enabled and g.displaySkillList then
			for j, s in ipairs(g.displaySkillList) do
				build.mainSocketGroup = i
				g.mainActiveSkill = j
				g.mainActiveSkillCalcs = j
				soe.recalc()
				local o = build.calcsTab.mainOutput
				local m = o.Minion
				res[#res + 1] = { group = i, skill = j, name = s.activeEffect.grantedEffect.name,
					TotalDPS = o.TotalDPS or 0, CombinedDPS = o.CombinedDPS or 0, TotalDotDPS = o.TotalDotDPS or 0,
					MinionDPS = m and (m.CombinedDPS or m.TotalDPS) or 0,
					Speed = o.Speed or 0, CritChance = o.CritChance or 0 }
			end
		end
	end
	build.mainSocketGroup = prevMain
	for i, g in ipairs(groups) do g.mainActiveSkill, g.mainActiveSkillCalcs = prev[i][1], prev[i][2] end
	soe.recalc()
	return res
end

-- ---- config -------------------------------------------------------------------
local configVarList
function soe.config_options()
	configVarList = configVarList or LoadModule("Modules/ConfigOptions")
	local res = {}
	local input = build.configTab.input
	for _, opt in ipairs(configVarList) do
		if opt.var then
			local choices
			if opt.list then
				choices = {}
				for k, c in ipairs(opt.list) do choices[k] = c.val end
			end
			res[#res + 1] = { var = opt.var, type = opt.type, label = opt.label and StripEscapes(opt.label) or nil,
				value = input[opt.var], choices = choices }
		end
	end
	return res
end

function soe.set_config(var, valueJson)
	local v = json.decode(valueJson)
	if v == json.null then v = nil end
	build.configTab.input[var] = v
	build.configTab:BuildModList()
	soe.recalc()
end

-- ---- items ----------------------------------------------------------------------
function soe.uses_second_weapon_set()
	return build.itemsTab.activeItemSet.useSecondWeaponSet and true or false
end

-- Is this slot used by the calculation? (weapon swap sets: only one set counts)
local function slotActive(name)
	if not name:match("^Weapon") then return true end
	local second = build.itemsTab.activeItemSet.useSecondWeaponSet and true or false
	return (name:match("Swap$") ~= nil) == second
end

function soe.list_items()
	local res = {}
	for name, slot in pairs(build.itemsTab.slots) do
		local id = slot.selItemId
		if id and id ~= 0 and not slot.nodeId then
			local item = build.itemsTab.items[id]
			if item then
				res[#res + 1] = { slot = name, id = id, name = item.name, base = item.baseName,
					rarity = item.rarity, active = slotActive(name), raw = item:BuildRaw() }
			end
		end
	end
	table.sort(res, function(a, b) return a.slot < b.slot end)
	return res
end

function soe.add_item(raw)
	build.itemsTab:CreateDisplayItemFromRaw(raw, true)
	local item = build.itemsTab.displayItem
	if not item then return false end
	build.itemsTab:AddDisplayItem()
	soe.recalc()
	return item.name
end

-- Equip an item from raw text into a specific slot (replaces what was there)
function soe.equip(slotName, raw)
	local slot = build.itemsTab.slots[slotName]
	if not slot then error("unknown slot " .. tostring(slotName)) end
	local item = new("Item", raw)
	if not item.base then error("unknown item base") end
	item:BuildModList()
	build.itemsTab:AddItem(item, true)
	slot:SetSelItemId(item.id)
	build.itemsTab:PopulateSlots()
	soe.recalc()
	return item.name
end

function soe.unequip(slotName)
	local slot = build.itemsTab.slots[slotName]
	if not slot then return false end
	slot:SetSelItemId(0)
	build.itemsTab:PopulateSlots()
	soe.recalc()
	return true
end

-- ---- save -------------------------------------------------------------------------
function soe.export_xml()
	return build:SaveDB("soe")
end
