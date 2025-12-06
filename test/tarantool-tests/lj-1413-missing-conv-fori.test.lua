local tap = require('tap')

-- Test file to demonstrate LuaJIT incorrect recording of FORI
-- bytecode in the DUALNUM mode.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1413.

local test = tap.test('lj-1413-missing-conv-fori'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

local function always_number(val)
  -- Trace 3 starts as a side trace for the first one.
  return tonumber(val) or 1
end

jit.opt.start('hotloop=1', 'hotexit=1')

-- Compile the root trace with stitching.
always_number()
always_number('')

-- An additional loop to evidentiate the issue for x86 arch in the
-- DUALNUM mode.
for _ = 1, 2 do
  -- Use '%' to force number slots.
  for i = always_number(9 % 1), 1 do
    -- The resulting IR for the trace 4 is the following:
    -- | 0002 > int SLOAD  10   TCI
    -- | 0003   int ADD    0002  +1.
    -- | 0004 > int LE     0003  +1.
    -- | 0005   int ADD    0003  +1.
    -- | 0006 > int GT     0005  +1.
    --
    -- The problem is within the type mismatch between the result
    -- type and the right operand in the IRs.
    for _ = '9' % i, always_number('') do end -- Trace 4.
  end
end

test:ok(true, 'no assertion failure')
test:done(true)
