-- Dumps PoB's game data (as loaded in memory) to one JSON document for the knowledge base.
local json = require("dkjson")

local function setToList(set)
	local res = {}
	for k, v in pairs(set or {}) do
		if v then res[#res + 1] = k end
	end
	table.sort(res)
	return res
end

local function copyList(list)
	local res = {}
	for i, v in ipairs(list or {}) do res[i] = v end
	return res
end

local skillTypeName = {}
for name, id in pairs(SkillType) do skillTypeName[id] = name end

local function typeNames(set)
	local res = {}
	for id, v in pairs(set or {}) do
		if v then res[#res + 1] = skillTypeName[id] or tostring(id) end
	end
	table.sort(res)
	return res
end

-- requireSkillTypes etc. are RPN-like lists: type ids mixed with "AND"/"OR"/"NOT"
local function typeExpr(list)
	local res = {}
	for i, v in ipairs(list or {}) do
		res[i] = type(v) == "number" and (skillTypeName[v] or tostring(v)) or v
	end
	return res
end

-- Human readable stat lines of a skill at a gem level
local function describeSkill(grantedEffect, level)
	local lines = {}
	for setIndex, set in ipairs(grantedEffect.statSets or {}) do
		local stats = {}
		for _, cs in ipairs(set.constantStats or {}) do stats[cs[1]] = cs[2] end
		local lvl = set.levels and (set.levels[level] or set.levels[1])
		for i, statId in ipairs(set.stats or {}) do
			local v = lvl and lvl[i]
			if type(v) ~= "number" then v = 1 end
			if stats[statId] == nil then stats[statId] = v end
		end
		local ok, out = pcall(data.describeStats, stats, set.statDescriptionScope or "skill_stat_descriptions")
		if ok and out then
			for _, line in ipairs(out) do lines[#lines + 1] = (set.label and setIndex > 1) and (set.label .. ": " .. line) or line end
		end
	end
	return lines
end

local function skillRecord(id, ge, level)
	return {
		id = id,
		name = ge.name,
		description = ge.description,
		support = ge.support and true or false,
		hidden = ge.hidden and true or false,
		cast_time = ge.castTime,
		skill_types = typeNames(ge.skillTypes),
		minion_types = typeNames(ge.minionSkillTypes),
		cannot_be_supported = ge.cannotBeSupported and true or false,
		support_gems_only = ge.supportGemsOnly and true or false,
		require_types = typeExpr(ge.requireSkillTypes),
		add_types = typeExpr(ge.addSkillTypes),
		exclude_types = typeExpr(ge.excludeSkillTypes),
		family = copyList(ge.gemFamily),
		stats_text = describeSkill(ge, level),
	}
end

function soe.kb_export()
	local out = { gems = {}, skills = {}, mods = {}, bases = {}, uniques = {}, nodes = {}, classes = {} }

	-- gems (things you socket) and every skill (incl. ones granted by items / ascendancies)
	local skillsFromGems = {}
	for id, gem in pairs(data.gems) do
		local ge = gem.grantedEffect or data.skills[gem.grantedEffectId]
		local maxLevel = gem.naturalMaxLevel or 20
		local level = (ge and ge.support) and 1 or maxLevel
		skillsFromGems[gem.grantedEffectId or ""] = true
		out.gems[#out.gems + 1] = {
			id = id,
			name = gem.name,
			gem_type = gem.gemType,
			tags = setToList(gem.tags),
			tag_string = gem.tagString,
			req_str = gem.reqStr, req_dex = gem.reqDex, req_int = gem.reqInt,
			tier = gem.Tier,
			max_level = maxLevel,
			skill_id = gem.grantedEffectId,
			skill = ge and skillRecord(gem.grantedEffectId, ge, level) or nil,
		}
	end
	for _, gem in pairs(data.gems) do
		for k, v in pairs(gem) do
			if type(k) == "string" and k:match("^additionalStatSet") then skillsFromGems[v] = true end
		end
	end
	for id, ge in pairs(data.skills) do
		if not skillsFromGems[id] and ge.name and ge.description then
			local rec = skillRecord(id, ge, 20)
			rec.from_gem = false
			out.skills[#out.skills + 1] = rec
		end
	end

	-- item modifiers
	for domain, mods in pairs(data.itemMods) do
		for id, m in pairs(mods) do
			if type(m) == "table" then
				out.mods[#out.mods + 1] = {
					id = id, domain = domain, type = m.type, affix = m.affix,
					text = copyList(m), level = m.level, group = m.group,
					tags = copyList(m.modTags), weight_keys = copyList(m.weightKey), weight_vals = copyList(m.weightVal),
					adds_tags = copyList(m.tags),  -- tags the mod puts on the item, e.g. no_cold_spell_mods
				}
			end
		end
	end

	-- item bases
	for name, b in pairs(data.itemBases) do
		local props = {}
		for _, k in ipairs({ "armour", "weapon", "flask", "charm", "tincture", "spirit" }) do
			if type(b[k]) == "table" then
				local p = {}
				for pk, pv in pairs(b[k]) do
					if type(pv) == "number" or type(pv) == "string" or type(pv) == "boolean" then p[pk] = pv end
				end
				props[k] = p
			end
		end
		local req = {}
		for k, v in pairs(b.req or {}) do req[k] = v end
		out.bases[#out.bases + 1] = {
			name = name, type = b.type, sub_type = b.subType, tags = setToList(b.tags),
			implicit = b.implicit, req = req, props = props, hidden = b.hidden and true or false,
		}
	end

	-- uniques: raw text blocks as PoB stores them
	for utype, list in pairs(data.uniques) do
		for _, raw in ipairs(list) do
			out.uniques[#out.uniques + 1] = { slot_type = utype, raw = raw }
		end
	end

	-- passive tree
	local tree = build.spec.tree
	for id, node in pairs(build.spec.nodes) do  -- spec nodes carry the resolved links
		if node.dn then
			local linked = {}
			for _, other in ipairs(node.linked or {}) do linked[#linked + 1] = other.id end
			table.sort(linked)
			out.nodes[#out.nodes + 1] = {
				id = id, name = node.dn, type = node.type, ascendancy = node.ascendancyName,
				stats = copyList(node.sd), linked = linked, x = node.x, y = node.y,
				is_notable = node.isNotable and true or false, is_keystone = node.isKeystone and true or false,
			}
		end
	end
	for _, cls in pairs(tree.classes) do
		local asc = {}
		for _, a in pairs(cls.classes or {}) do
			if a.name and a.name ~= "None" then asc[#asc + 1] = a.name end
		end
		table.sort(asc)
		out.classes[#out.classes + 1] = { name = cls.name, ascendancies = asc }
	end

	-- essences: guaranteed mod per item type
	out.essences = {}
	for id, e in pairs(data.essences or {}) do
		for itemType, modId in pairs(e.mods or {}) do
			out.essences[#out.essences + 1] = { id = id, name = e.name, family = e.type, tier_level = e.tierLevel,
				item_type = itemType, mod_id = modId }
		end
	end

	out.tree_version = build.spec.treeVersion
	return json.encode(out)
end
