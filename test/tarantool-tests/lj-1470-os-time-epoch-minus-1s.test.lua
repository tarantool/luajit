local tap = require('tap')

-- The test file demonstrates os.time() fail to return -1 time
-- value.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1470.
local test = tap.test('lj-1470-os-time-epoch-minus-1s')

test:plan(1)

local minus_1s_time = os.date('*t', -1)
test:is(os.time(minus_1s_time), -1, 'correct os.time()')

test:done(true)
