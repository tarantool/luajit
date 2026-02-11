local tap = require('tap')

-- Test file to check the correct recording of -0 step for value.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1432.

local test = tap.test('lj-1432-minus-zero-step'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(2)

local traceinfo = require('jit.util').traceinfo

local function trace_slot()
  local counter = 0
  local slot = -0
  -- Run the inner trace several times. Before the patch, it leads
  -- to several child traces due to the always failed guards.
  while true do
    if counter > 5 then break end
    counter = counter + 1;
    -- luacheck: ignore
    for _ = 1, 1, slot do
      break
    end
  end
end

local function trace_const()
  local counter = 0
  -- Run the inner trace several times. Before the patch, it leads
  -- to several child traces due to the always failed guards.
  while true do
    if counter > 5 then break end
    counter = counter + 1;
    -- luacheck: ignore
    for _ = 1, 1, -0 do
      break
    end
  end
end

local function test_trace_recorded(test_payload)
  jit.flush()
  -- XXX: Reset hotcounters to avoid false-positive collisions.
  jit.opt.start('hotloop=1', 'hotexit=1')
  test_payload()
  return traceinfo(1)
end

-- The -0 step leads to the always failed guard, so such traces
-- are now aborted and not recorded.

test:ok(not test_trace_recorded(trace_slot), 'no trace recorded -0 as slot')
test:ok(not test_trace_recorded(trace_const), 'no trace recorded -0 as const')

test:done(true)
