local tap = require('tap')

-- Test file to demonstrate LuaJIT incorrect sink of the `IR_CONV`
-- with disabled DCE optimization.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1537.
local test = tap.test('lj-1537-conv-sink-without-dce'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

jit.opt.start('hotloop=1', '-dce')

-- Before the patch, the CONV num.int is sunk even with disabled
-- DCE optimization (which is required for sink optimization).
-- Hence, the register allocated for CONV IR is the same as for
-- the next ADD IR, leading to the incorrect results when
-- exiting to the interpreter.
-- | 0004 xmm7     num CONV   0003  num.int
-- | 0005 xmm7  >  num SLOAD  #4    T
-- | 0006 xmm7   + num ADD    0005  +1
-- | ...
-- | 0009 ------------ LOOP ------------
-- | 0010 xmm7   + num ADD    0006  +1
-- | 0011 rbp    + int ADD    0007  +1
-- | ....              SNAP   #3   [ ---- ---- ---- 0004 0010 ]

local t = {}
local conv, n = 0, 0
for _ = 1, 4 do
  -- Need preserve the conversion, not int value in a snap.
  conv = #t * 1
  n = n + 1 -- Occupies the same register.
end

test:is(conv, 0, 'correct value is restored from snapshot')

test:done(true)
