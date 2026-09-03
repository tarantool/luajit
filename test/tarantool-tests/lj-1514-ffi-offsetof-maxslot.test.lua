local tap = require('tap')

-- The test file to demonstrate an incorrect JIT slots recording
-- for the `ffi.offsetof()` fast function.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1514.
local test = tap.test('lj-1514-ffi-offsetof-maxslot'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

local ffi = require('ffi')

ffi.cdef[[
  struct test {int a;}
]]

jit.opt.start('hotloop=1')

local ct = ffi.typeof('struct test')

local res
for _ = 1, 4 do
  -- Need to use CALLM for the `ffi.offsetof()` call to adjust
  -- JIT slots to occupy extra slots above the top of the Lua
  -- stack. Use `tonumber()` as an external function as the
  -- simplest proxy. `ffi.offsetof()` returns 1 value for regular
  -- fields.
  res = tonumber(ffi.offsetof(ct, 'a'))
end

test:is(res, 0, 'correct offset value')

test:done(true)
