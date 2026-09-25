local tap = require('tap')
local test = tap.test('lj-pidbg-stability'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Test requires LUAJIT_USE_PIDEBUG'] = not pcall(require, 'jit.pidbg'),
})

local pidbg = require('jit.pidbg')

-- XXX: Compile traces eagerly to make the test time-bounded.
jit.opt.start('hotloop=1', 'hotexit=1')

-- The functions below are intentionally different (arithmetic,
-- calls, branches, nested loops, table access) so that a diverse
-- set of traces is recorded while the precise debug info is
-- collected.
local function loop_sum(n)
  local s = 0
  for i = 1, n do s = s + i end
  return s
end

local function loop_mul(n)
  local p = 1
  for _ = 1, n do p = p * 2 end
  return p
end

local function branchy(n)
  local s = 0
  for i = 1, n do
    if i % 2 == 0 then
      s = s + i
    else
      s = s - i
    end
  end
  return s
end

local function nested(n)
  local s = 0
  for i = 1, n do
    for j = 1, 10 do s = s + i * j end
  end
  return s
end

local function table_loop(t, n)
  local s = 0
  for i = 1, n do s = s + t[i % #t + 1] end
  return s
end

local hot = { loop_sum, loop_mul, branchy, nested }
local hot_table = { 1, 2, 3, 4, 5, 6, 7, 8 }

local function compile_traces()
  for _ = 1, 50 do
    for i = 1, #hot do hot[i](50) end
    table_loop(hot_table, 50)
  end
end

-- Compile traces, flush them in different ways, and compile them
-- again, checking that the VM survives both the registration and
-- the removal of the precise debug info.
local function churn(round)
  compile_traces()
  if round % 2 == 0 then
    jit.flush()
  else
    -- Flush the traces one by one as well.
    for tr = 1, 32 do jit.flush(tr) end
  end
  collectgarbage()
  compile_traces()
end

-- Check that the trace introspection API is total: for any trace
-- number (including zero, negative and out-of-range values) it
-- must never raise an error and must return nil or a table.
local function check_trace_api()
  local trace_numbers = {
    -1000000, -1000, -1, 0, 1, 2, 3, 4, 5, 16, 64, 1024, 1000000,
  }
  for i = 1, #trace_numbers do
    local ok, res = pcall(pidbg.trace, trace_numbers[i])
    if not ok then
      return false
    end
    if res ~= nil and type(res) ~= 'table' then
      return false
    end
  end
  return true
end

-- At least one trace must have been registered after compilation.
local function has_registered_trace()
  for tr = 1, 128 do
    if pidbg.trace(tr) ~= nil then
      return true
    end
  end
  return false
end

local N_ITER = 6
local MODES = { 'l', 'b' }

test:plan(2 + N_ITER * 6)

test:ok(not pidbg.active(), 'pidbg is inactive initially')

for i = 1, N_ITER do
  local mode = MODES[(i - 1) % #MODES + 1]
  local label = ('mode %q iteration %d'):format(mode, i)

  test:ok(pidbg.start(mode), 'start() returns true (' .. label .. ')')
  test:ok(pidbg.active(), 'active() is true after start (' .. label .. ')')
  churn(i)
  test:ok(has_registered_trace(),
          'traces are registered while active (' .. label .. ')')
  test:ok(check_trace_api(),
          'trace() is total for any id (' .. label .. ')')
  test:ok(pidbg.stop(), 'stop() returns true (' .. label .. ')')
  test:ok(not pidbg.active(), 'active() is false after stop (' .. label .. ')')
end

test:ok(not pidbg.active(), 'pidbg is inactive at the end')

test:done(true)
