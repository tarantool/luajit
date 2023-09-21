local tap = require('tap')

-- A test file to demonstrate a crash due to Lua stack
-- out-of-bounds access, see below testcase descriptions.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1048.
local test = tap.test('lj-1048-fix-stack-checks-vararg-calls')

test:plan(2)

-- The test case demonstrates a segmentation fault due to stack
-- overflow by recursive calling `pcall()`. The functions are
-- vararg because the stack check in BC_IFUNCV is off by one on
-- ARM64 and MIPS64 without the patch.
local function prober_1(...) -- luacheck: no unused
  -- Any fast function can be used as metamethod, but `type` is
  -- convenient here because it works fast and can be used with
  -- any data type. Lua function cannot be used since it
  -- will check the stack on each invocation. We need to check
  -- using of the correct value LJ_STACK_EXTRA slots
  -- (5+3*LJ_FR2) = 8 for GC64 mode.
  pcall(pcall, pcall, pcall, pcall, pcall, pcall, pcall, pcall, type, 0)
end

local function looper(prober, n, ...)
  prober(...)
  return looper(prober, n + 1, n, ...)
end

pcall(coroutine.wrap(looper), prober_1, 0)

test:ok(true, 'no stack overflow with recursive pcall')

-- The testcase demonstrate a segmentation fault due to stack
-- overflow when `pcall()` is used as `__newindex` metamethod.
-- The function is vararg because stack check in BC_IFUNCV is off
-- by one on ARM64 and MIPS64 without the patch.

-- Any fast function can be used as metamethod, but `type` is
-- convenient here because it works fast and can be used with
-- any data type. Lua function cannot be used since it
-- will check the stack on each invocation.
local t = setmetatable({}, { __newindex = pcall, __call = type })

local function prober_2(...) -- luacheck: no unused
  -- Invokes `pcall(t, t, t)`.
  t[t] = t
end

pcall(coroutine.wrap(looper), prober_2, 0)

test:ok(true, 'no stack overflow with metamethod')

test:done(true)
