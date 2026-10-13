local tap = require('tap')

-- Test file to demonstrate LuaJIT incorrect handling of no
-- arguments for `math.ceil()`, `math.floor()` functions.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1532.

local test = tap.test('lj-1532-math-floor-ceil-argcheck')

test:plan(2)

-- A simple function to push a number value for `math.floor()`,
-- `math.ceil()` to the Lua stack.
local function stack()
  return 1.2
end

local function call_wp(f)
  -- Push some value to the stack to mark the slot.
  stack()
  -- Use non-inlined variant for function name in the error
  -- message.
  local res = f()
  return res
end

local function math_func_test(subtest, f)
  subtest:plan(2)
  local err, msg = pcall(call_wp, f)
  subtest:is(err, false, 'correct status for empty ' .. subtest.name)
  subtest:like(msg, "bad argument #1 to 'f' %(number expected, got no value%)",
               'correct error message for empty ' .. subtest.name)
end

test:test('math.ceil', math_func_test, math.ceil)
test:test('math.floor', math_func_test, math.floor)

test:done(true)
