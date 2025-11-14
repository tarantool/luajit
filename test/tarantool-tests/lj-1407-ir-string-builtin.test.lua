local tap = require('tap')

-- Test file to demonstrate incorrect LuaJIT recording for the
-- corner cases of the `string` built-ins. All cases below don't
-- check the integer overflow/underflow correctly.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1407.

local test = tap.test('lj-1407-ir-string-builtin'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(4)

local function trace_sub(s, i, e)
  local r = s:sub(i, e)
  return r
end

local function trace_sub_neg(s, i)
  local r = s:sub(1, i)
  return r
end

local function trace_byte(s, i, e)
  local r = s:byte(i, e)
  return r
end

local function trace_find(s, i)
  local r = s:find('2', i)
  return r
end

jit.opt.start('hotloop=1')

-- Compile the trace.
trace_sub('123', 1, -2)
trace_sub('123', 1, -2)
-- Execute the trace with the invalid memory access.
test:is(trace_sub('123', 0x7FFFFFFF, -0x7FFFFFFF), '',
        'string.sub is correct at the trace')

-- The arithmetic for the number of results on the trace is the
-- following for the negative last argument (`end`):
-- | str->len + 1 + end - (start - 1)
-- Trace has the guard to the number of results. We should record
-- an original trace with the guard passed for the underflowed
-- case as well:
-- 0 + 1 + 0x80000001 - 0x7ffffffe = 4.
-- Compile the trace that fits the needed properties:
trace_byte('1234', 1, -1)
trace_byte('1234', 1, -1)
-- Execute the trace with the invalid memory access.
test:is(trace_byte('', 0x7FFFFFFF, -0x7FFFFFFF), nil,
        'string.byte is correct at the trace')

-- Compile the trace.
trace_sub_neg('123', 5)
trace_sub_neg('123', 5)
-- Execute the trace with negative value.
test:is(trace_sub_neg('123', -2), '12',
        'string.sub negative end is correct at the trace')

-- Compile the trace.
trace_find('123', 5)
trace_find('123', 5)
-- Execute the trace with value to overflow.
test:is(trace_find('123', -0x80000000), 2, 'string.find with overflow')

test:done(true)
