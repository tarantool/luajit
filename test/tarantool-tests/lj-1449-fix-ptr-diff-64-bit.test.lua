local tap = require('tap')

-- Test file to demonstrate LuaJIT's incorrect 64-bit pointer
-- subtraction.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1449.

local test = tap.test('lj-1449-fix-ptr-diff-64-bit')

local ffi = require('ffi')

test:plan(2)

local diff = 0x80000001ULL
local base = 0x700000000000ULL
local p0 = ffi.cast('char *', base)
local p1 = ffi.cast('char *', base + diff)

test:is(p1 - p0, diff, 'correct pointer difference between 64-bit pointers')

test:skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

local results = {}

jit.opt.start('hotloop=1')

for i = 1, 4 do
  -- Use constants on trace.
  local delta = 0x80000001ULL
  local b = 0x700000000000ULL
  local pt0 = ffi.cast('char *', b)
  local pt1 = ffi.cast('char *', b + delta)
  results[i] = pt1 - pt0
end

test:samevalues(results, 'consistent JIT and VM behaviour for ptr subtraction')

test:done(true)
