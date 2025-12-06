local tap = require('tap')

-- This test demonstrates LuaJIT's incorrect narrowing
-- optimization in the DUALNUM mode for 0.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1418.

local test = tap.test('lj-1418-dualnum-narrowing-minus-0'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(2)

local tostring = tostring

local function test_const_on_trace(x)
  local zero = x % 1
  local mzero = -zero
  -- Bad IR slot with enabled optimizations.
  local res = tostring(mzero)
  return res
end

local function test_non_const_on_trace(a, b)
  local mb_zero = a % b
  -- Too optimistic optimization without check for the 0 corner
  -- case.
  local mb_mzero = -mb_zero
  local res = tostring(mb_mzero)
  return res
end

jit.opt.start('hotloop=1')

-- Hot trace.
test_const_on_trace(1)
-- Compile trace.
test:is(test_const_on_trace(1), '-0', 'correct const value on trace')

-- Reset hotcounts.
jit.opt.start('hotloop=1')

-- Hot trace.
test_non_const_on_trace(2, 3)
-- Record trace, use non-zero result value to record.
test_non_const_on_trace(2, 3)
-- Misbehaviour on trace with result zero value.
test:is(test_non_const_on_trace(2, 1), '-0', 'correct non-const value on trace')

test:done(true)
