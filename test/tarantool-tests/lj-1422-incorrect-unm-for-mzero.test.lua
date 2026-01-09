local tap = require('tap')

-- This test demonstrates LuaJIT's inconsistencies in the VM and
-- the JIT engine in the DUALNUM mode for 0.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1422.

local test = tap.test('lj-1422-incorrect-unm-for-mzero'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(3)

local tonumber = tonumber
local tostring = tostring

local function always_number(val)
  return tonumber(val) or 1
end

-- Yielded int type for non-x86 arches.
local function modvn(v1)
  return always_number(v1) % 1
end

local function unm(v)
  return -v
end

jit.opt.start('hotloop=1', 'hotexit=1')

always_number(nil) -- Root trace.
always_number(nil)

local stack_slot = nil
for _ = 1, 5 do
  always_number(0) -- Compile side trace.
  -- The side trace crashes in the `rec_check_slots()` for non-x86
  -- arches before the patch.
  stack_slot = tostring(unm(modvn(stack_slot)))
end

test:is(stack_slot, '-0', 'correct result of the trace execution')

-- `tonumber()` recording and conversion to number.
local results = {nil, nil, nil, nil}
for i = 1, 4 do
  local slot = -tonumber('0')
  results[i] = tostring(slot)
end

test:is(results[1], '-0', 'correct result of the expression')
test:samevalues(results, 'correct result of the tonumber recording')

test:done(true)
