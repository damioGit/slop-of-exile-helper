-- Pure-Lua shim for the lua-utf8 C module (the C build is linked against PoB's own lua51.dll).
-- PoB headless only uses it for number formatting and text editing; byte-wise is good enough.
local M = {}
for k, v in pairs(string) do M[k] = v end
function M.next(s, i, step)
	i = (i or 0) + (step or 1)
	if i < 1 or i > #s then return nil end
	return i
end
return M
