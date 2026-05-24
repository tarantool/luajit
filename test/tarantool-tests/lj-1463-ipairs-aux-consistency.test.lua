local tap = require('tap')

-- The test file to demonstrate the inconsistent behaviour between
-- the JIT compiler and the VM for the `ipairs_aux()` function on
-- x86 and x86_64 arches.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1463.

local test = tap.test('lj-1463-ipairs-aux-consistency'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(4)

jit.opt.start('hotloop=1')

local ipairs_aux = ipairs({})

local rkeys = {}
local rvals = {}

for i = 1, 4 do
  local key, val = ipairs_aux({[0] = 0, [1] = 1}, -0.1)
  rkeys[i] = key
  rvals[i] = val
end

test:is(rkeys[1], 1, 'correct key result')
test:is(rvals[1], 1, 'correct value result')
test:samevalues(rkeys, 'consistent JIT and VM behaviour for keys')
test:samevalues(rvals, 'consistent JIT and VM behaviour for values')

test:done(true)
