local tap = require('tap')

-- Test file to demonstrate incorrect register allocation for
-- `IR_TOBIT` on x86/x64.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1536.
local test = tap.test('lj-1536-tobit-regalloc'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

local tobit = bit.tobit

jit.opt.start('hotloop=1')

local res
local VALUE = 0x100
-- Use a table for the `noreg` of the tobit operand.
local t = {k = VALUE}
-- 5 iterations to hit invariant loop part.
for _ = 1, 5 do
  -- Generates the following IRs in the LOOP part:
  -- 0011 xmm0  >  num SLOAD  #4    T
  -- ...
  -- 0015 ------------ LOOP ------------
  -- 0016 rbp    + int TOBIT  0011  bias
  -- The resulting machine code adding the bias to the allocated
  -- for the SLOAD (before the patch) register corrupts it and
  -- hence restores an incorrect value to the interpreter.
  res = tobit(t.k)
  t.k = VALUE -- `noreg`.
end

test:is(res, VALUE, 'correct tobit result')

test:done(true)
