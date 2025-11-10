local tap = require('tap')

-- The test file to demonstrate LuaJIT crash during stack overflow
-- in the VM event handle.
-- See also, https://github.com/LuaJIT/LuaJIT/issues/1403.

local test = tap.test('lj-1403-vmevent-crash-on-stkov'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

local jit_dump = require('jit.dump')

-- XXX: Some specific stack usage without a stack top check by the
-- Lua function header.
local t = setmetatable({}, {__newindex = pcall})
-- luacheck: no unused
local function prober(...)
  -- Invokes `pcall(t, t, t)`.
  t[t] = t
end

jit.opt.start('hotloop=1')
-- Need the invocation of the VM event.
jit_dump.start('i', '/dev/null')

-- The code below causes the stack overflow in the VM event
-- handler. The unwinding of the error breaks the JIT semantics
-- and leads to a crash.
local function looper()
  local r = pcall(prober)
  if not r then
    local n = 1
    while n < 3 do
      prober(1, 2)
      n = n + 1
    end
  end
  looper()
end

pcall(coroutine.wrap(looper))

test:ok(true, 'no crash')

test:done(true)
