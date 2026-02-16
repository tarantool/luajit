local tap = require('tap')

-- The test file to check the correct recording of the for loop.
-- Used as a canary test, since we have none.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1438.

local test = tap.test('lj-1438-jit-for-canary'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

local traceinfo = require('jit.util').traceinfo

jit.flush()
jit.opt.start('hotloop=1')

for _ = 1, 4 do end

test:ok(traceinfo(1), 'simple for loop is recorded')

test:done(true)
