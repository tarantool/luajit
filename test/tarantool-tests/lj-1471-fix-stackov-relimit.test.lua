local tap = require('tap')

-- The test file demonstrates a heap-overflow due to Lua stack
-- out-of-bounds access after an incorrect stack shrinking after
-- unwinding.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1471.

local test = tap.test('lj-1471-fix-stackov-relimit')

test:plan(1)

local function recursive_add(v1, v2)
  -- Slot to eat the stack.
  -- luacheck: no unused
  local _
  recursive_add(v1, v2)
end

local table_mt = {
  __add = recursive_add,
}

local t1 = setmetatable({}, table_mt)
local t2 = setmetatable({}, table_mt)

coroutine.wrap(function()
  xpcall(error, function()
    pcall(error) -- Shrink stack back after unwinding.
    -- XXX: Empirical amount of stack slots to observe the issue.
    -- After the stack overflow, the `xpcall()` handler is invoked
    -- again (see https://github.com/LuaJIT/LuaJIT/issues/1382).
    -- The stack is overallocated beyond its normal limit to
    -- handle the error. After the `pcall(error)`, stack is
    -- shrinking back to its normal size, leaving no space for
    -- metamethod invocation. It is leaving to heap-overflow and a
    -- crash.
    -- luacheck: no unused
    local _, _, _, _, _, _, _, _, _, _
    local _, _, _, _, _, _, _, _, _, _
    local _, _, _, _, _, _, _, _, _, _
    local _
    local _ = t1 + t2
  end)
end)()

test:ok(true, 'no heap overflow after stack relimiting')

test:done(true)
