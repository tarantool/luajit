local tap = require('tap')

-- The test file to demonstrate an incorrect LuaJIT handling of
-- JFORI loop setup for the empty numeric loops. This test fails
-- on ARM64 in particular, but it is worth checking for all
-- architectures.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1530.
local test = tap.test('lj-1530-fix-jfori-empty-step'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(2)

-- Function to wrap the recorded FORI instruction.
local function loop_fori(limit)
  local cnt = 0
  -- Use `1.1` to force a numeric loop. We may use a non-integer
  -- limit for this, and then we end up on the same path after
  -- `lj_meta_for()` casting the loop start index from integer to
  -- double. But the current path is just simpler.
  -- The loop body shouldn't be taken due to the empty range in
  -- this test.
  for _ = 1.1, limit do cnt = cnt + 1 end
  return cnt
end

-- Check the interpreter just in case.
test:is(loop_fori(0), 0, 'correct interpreter FORI loop skip')

jit.opt.start('hotloop=1')

-- Compile the loop.
loop_fori(4.1)

-- Run the empty loop range with the compiled instruction.
test:is(loop_fori(0), 0, 'correct JFORI loop skip')

test:done(true)
