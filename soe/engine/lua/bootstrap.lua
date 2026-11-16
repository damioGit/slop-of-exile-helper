-- Boots Path of Building (PoE2) headless inside lupa's LuaJIT.
-- Python sets before running: SOE_RUNTIME_LUA, SOE_SHIM, SOE_INFLATE_HEX, SOE_DEFLATE_HEX
package.path = SOE_SHIM .. "/?.lua;" .. SOE_RUNTIME_LUA .. "/?.lua;" .. SOE_RUNTIME_LUA .. "/?/init.lua;" .. package.path
arg = arg or {}
-- HeadlessWrapper waits on stdin when startup fails; turn that into an error instead
io.read = function() error("PoB startup failed: " .. tostring(mainObject and mainObject.promptMsg or "?")) end
dofile("HeadlessWrapper.lua")

-- Real zlib through Python. Binary crosses the bridge as hex so lupa never has to decode it as text.
local function tohex(s) return (s:gsub(".", function(c) return string.format("%02x", c:byte()) end)) end
local function fromhex(h) return (h:gsub("..", function(x) return string.char(tonumber(x, 16)) end)) end
function Inflate(data) return fromhex(SOE_INFLATE_HEX(tohex(data))) end
function Deflate(data) return fromhex(SOE_DEFLATE_HEX(tohex(data))) end
