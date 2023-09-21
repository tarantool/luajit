local tap = require('tap')

-- The test file to verify correctness of stack size check during
-- recording of vararg functions.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1402
local test = tap.test('lj-1402-vararg-stkov-check-gc64.test.lua'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

-- luacheck: no unused
local function vararg(...)
  -- None.
end

jit.opt.start('hotloop=1')

-- This function utilizes the exact amount of stack slots to cause
-- the stack reallocation during `call_init()` in the GC64 mode.
local function caller()
  local _, _, _, _, _, _, _, _, _, _
  local _, _, _, _, _, _, _, _, _, _
  local _, _, _, _, _, _, _, _, _, _
  local n = 1
  while n < 3 do
    vararg()
    n = n + 1
  end
end

coroutine.wrap(caller)()

test:ok(true, 'no assertion')

test:done(true)
