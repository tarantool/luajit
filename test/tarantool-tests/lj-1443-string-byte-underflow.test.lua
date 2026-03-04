local tap = require('tap')

-- The test file to demonstrate integer underflow during recording
-- for the `string.byte()` built-in.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1443.

local test = tap.test('lj-1443-string-byte-underflow'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

jit.opt.start('hotloop=1')

local result
local str = 'xxx'
for _ = 1, 4 do
  -- Failed assertion in `rec_check_slots()` due to incorrect
  -- number of results after underflow.
  result = (str):byte(0X7FFFFFFF, -0X7FFFFFFF)
end

test:is(result, nil, 'correct result on trace')

test:done(true)
