local tap = require('tap')

-- The test file to demonstrate the UBSan warning in
-- `carith_ptr()`.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1459.
local test = tap.test('lj-1459-subtraction-carith')

test:plan(2)

-- The `nil` as the first operand of subtraction is required,
-- since it is required to trigger metamethod invocation.
-- It successfully passes the argument check since it may be
-- considered as NULL ptr for other metamethods.
local func = loadstring('_ = nil - 0x8000000000000000LL')
local res, err = pcall(func)

test:is(res, false, 'correct result')
local error_msg = "attempt to perform arithmetic on 'nil' and 'int64_t'"
test:ok(err:match(error_msg), 'error on subtraction')

test:done(true)
