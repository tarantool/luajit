local tap = require('tap')

-- The test file to demonstrate the incorrect exit to the
-- interpreter into fast functions on mips64.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1428.

local test = tap.test('lj-1428-mips64-bus-error-stitch'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

local function always_number(val)
  return tonumber(val) or 1
end

jit.opt.start('hotloop=1')

-- `tonumber()` with a string argument produces stitching and
-- exits to the interpreter after that.
-- On mips64 the `PC2PROTO` offset leads to an unaligned address
-- for this fast function.

always_number('')
always_number('')

-- Start the stitched trace and exit to the interpreter.
-- Leads to the Bus error on mips64 before the patch.
always_number('')

test:ok(true, 'no bus error')

test:done(true)
