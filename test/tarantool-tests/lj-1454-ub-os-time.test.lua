local tap = require('tap')

-- The test file to demonstrate UBSan warning for `os.time()` with
-- huge negative index values for month and/or year.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1454.
local test = tap.test('lj-1454-ub-os-time')

test:plan(1)

local INT_MIN = -2 ^ 31

local cur_time = os.time({
  day = 1,
  month = INT_MIN,
  year = INT_MIN,
})
test:is(cur_time, nil, 'os.time() with INT_MIN')

test:done(true)
