local tap = require('tap')

-- Test file to demonstrate unbalanced Lua stack after instruction
-- recording due to throwing an error at recording of a stitched
-- function.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1166.

local test = tap.test('lj-1166-error-stitch-oom-ir-buff'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Disabled on *BSD due to #4819'] = jit.os == 'BSD',
})

test:plan(1)

local allocinject = require('allocinject')

-- Generate the following Lua chunk:
-- local s1
-- ...
-- local sN
-- for i = 1, 2 do
--   s1 = i + 1
--   ...
--   sN = i + N
--   math.modf(1)
-- end
local function create_chunk(n_slots)
  local chunk = ''
  for i = 1, n_slots do
    chunk = chunk .. ('local s%d\n'):format(i)
  end
  chunk = chunk .. 'for i = 1, 2 do\n'
  -- Generate additional IR instructions.
  for i = 1, n_slots do
    chunk = chunk .. ('  s%d = i + %d\n'):format(i, i)
  end
  -- `math.modf()` recording is NYI.
  chunk = chunk .. '  math.modf(1)\n'
  chunk = chunk .. 'end\n'
  return chunk
end

-- XXX: amount of slots is empirical.
local tracef = assert(loadstring(create_chunk(175)))

jit.opt.start('hotloop=1', '-loop', '-fold')

allocinject.enable()

tracef()

allocinject.disable()

test:ok(true, 'stack is balanced')

test:done(true)
