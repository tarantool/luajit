local tap = require('tap')

-- Test file to check the correct recording of for control
-- variable with NaN value.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1433.

local test = tap.test('lj-1433-nan-for-loop-control-var'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(3)

local traceinfo = require('jit.util').traceinfo

local function trace_nan_loop_start()
  local counter = 0
  -- XXX: Use NaN as stack slot, not upvalue.
  local nan = 0 / 0
  -- Run the inner trace several times. Before the patch, it leads
  -- to the trace with always fail guard.
  while true do
    if counter > 5 then break end
    counter = counter + 1;
    -- luacheck: ignore
    for _ = nan, 1, 1 do
      break
    end
  end
end

local function trace_nan_loop_stop()
  local counter = 0
  -- XXX: Use NaN as stack slot, not upvalue.
  local nan = 0 / 0
  -- Run the inner trace several times. Before the patch, it leads
  -- to the trace with always fail guard.
  while true do
    if counter > 5 then break end
    counter = counter + 1;
    -- luacheck: ignore
    for _ = 1, nan, 1 do
      break
    end
  end
end

local function trace_nan_loop_step()
  local counter = 0
  -- XXX: Use NaN as stack slot, not upvalue.
  local nan = 0 / 0
  -- Run the inner trace several times. Before the patch, it leads
  -- to several child traces due to the always failed guards.
  while true do
    if counter > 5 then break end
    counter = counter + 1;
    -- luacheck: ignore
    for _ = 1, 1, nan do
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

-- The NaN loop control vars leads to the always failed guard, so
-- such traces are now aborted and not recorded.

test:ok(not test_trace_recorded(trace_nan_loop_start),
        'no trace recorded NaN start')
test:ok(not test_trace_recorded(trace_nan_loop_stop),
        'no trace recorded NaN stop')
test:ok(not test_trace_recorded(trace_nan_loop_step),
        'no trace recorded NaN step')

test:done(true)

