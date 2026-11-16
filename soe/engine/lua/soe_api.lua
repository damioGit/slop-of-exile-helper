-- Thin, stable API over PoB internals. Python calls only these, so PoB updates break one file.
soe = {}

function soe.recalc()
	build.buildFlag = true
	runCallback("OnFrame")
end

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

function soe.paste_gems(text)
	build.skillsTab:PasteSocketGroup(text)
	soe.recalc()
end

function soe.add_item(raw)
	build.itemsTab:CreateDisplayItemFromRaw(raw, true)
	local item = build.itemsTab.displayItem
	if not item then return false end
	build.itemsTab:AddDisplayItem()
	soe.recalc()
	return item.name
end

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

function soe.export_xml()
	return build:SaveDB("soe")
end
