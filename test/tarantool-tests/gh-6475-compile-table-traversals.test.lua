local tap = require('tap')

-- Test that table traversals are compiled: neither a `pairs()`
-- loop (BC_ISNEXT and BC_ITERN) nor a `next()` call aborts the
-- trace recording.
-- See also https://github.com/tarantool/tarantool/issues/6475.

local test = tap.test('gh-6475-compile-table-traversals'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Disabled on *BSD due to #4819'] = jit.os == 'BSD',
})

local jparse = require('utils').jit.parse

-- Both the array and the hash parts are traversed.
local t = {1, 2, a = 3, b = 4}
local N_CALLS = 4
local EXPECTED_SUM = N_CALLS * 10

local function sum_pairs()
  local sum = 0
  for _, v in pairs(t) do
    sum = sum + v
  end
  return sum
end

local function sum_next()
  local sum = 0
  local k, v = next(t)
  while k ~= nil do
    sum = sum + v
    k, v = next(t, k)
  end
  return sum
end

-- XXX: Avoid any other traces compilation due to hotcount
-- collisions for predictable results.
jit.off()
jit.flush()

test:plan(6)

local function check(name, func)
  jit.flush()
  jit.on()
  jit.opt.start('hotloop=1')
  jparse.start('i')

  -- The outer loop is recorded too, and its trace runs into the
  -- traversal: without the compilation of BC_ISNEXT it aborts.
  local sum = 0
  for _ = 1, N_CALLS do
    sum = sum + func()
  end

  local traces, aborted_traces = jparse.finish()
  jit.off()

  test:is(sum, EXPECTED_SUM, name .. ': correct result')
  -- Aborts like "inner loop in root trace" are fine.
  local nyi = false
  for _, aborts in pairs(aborted_traces) do
    for _, trace in ipairs(aborts) do
      nyi = nyi or trace.abort_reason:match('NYI') ~= nil
    end
  end
  test:ok(not nyi, name .. ': no NYI aborts')
  local compiled = false
  for _, trace in pairs(traces) do
    compiled = compiled or trace:has_ir('lj_vm_next') ~= nil
  end
  test:ok(compiled, name .. ': the traversal is compiled')
end

check('pairs()', sum_pairs)
check('next()', sum_next)

test:done(true)
