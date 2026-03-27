local tap = require('tap')

-- The test file to demonstrate UBSan warning for `unpack()` with
-- a huge indices value.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1450.
local test = tap.test('lj-1450-unpack-huge-indices')

test:plan(2)

local INT_MAX = 2 ^ 31 - 1

-- The first test checks the UBSan runtime error. The assertions
-- were added just to be sure we don't change the behaviour.
-- The second test additionally checks a correct behaviour for
-- a <maximum - 1> value.
local tbl = {
  [INT_MAX] = INT_MAX,
  [INT_MAX - 1] = INT_MAX - 1,
}
local res = unpack(tbl, INT_MAX, INT_MAX)
test:is(res, INT_MAX, 'unpack with INT_MAX: correct result')

res = unpack(tbl, INT_MAX - 1, INT_MAX - 1)
test:is(res, INT_MAX - 1, 'unpack with INT_MAX - 1: correct result')

test:done(true)
