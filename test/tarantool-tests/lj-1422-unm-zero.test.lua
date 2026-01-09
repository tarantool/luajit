local tap = require('tap')

-- The test file to demonstrate LuaJIT's incorrect BC_UNM for the
-- 0 operand for the DUALNUM mode.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1422.

local test = tap.test('lj-1422-unm-zero')
test:plan(1)

test:ok(tostring(-0) == '-0', 'correct unary minus for 0')

test:done(true)
