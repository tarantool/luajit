local tap = require('tap')

-- Test file to demonstrate LuaJIT's incorrect `bit.tobit()`
-- behaviour for arm64.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1253.

local test = tap.test('lj-1253-tobit-conversion')

test:plan(2)

test:is(bit.tobit(1.7), 2, 'correct bit.tobit rounding')

test:skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

local results = {}

jit.opt.start('hotloop=1')

for i = 1, 4 do
  -- Use constants on trace.
  results[i] = bit.tobit(1.7)
end

test:samevalues(results, 'consistent JIT and VM behaviour for bit.tobit')

test:done(true)
