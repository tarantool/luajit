local tap = require('tap')

-- Test file to demonstrate unbalanced Lua stack after instruction
-- recording due to throwing an error at recording of a stitched
-- function.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1166.

local test = tap.test('lj-1166-error-stitch-oom-snap-buff'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Disabled on *BSD due to #4819'] = jit.os == 'BSD',
})

test:plan(1)

local allocinject = require('allocinject')

-- Generate the following Lua chunk:
-- for i = 1, 2 do
--   if i < 1 then end
--   ...
--   if i < N then end
--   math.modf(1)
-- end
local function create_chunk(n_conds)
  local chunk = ''
  chunk = chunk .. 'for i = 1, 2 do\n'
  -- Each condition adds additional snapshot.
  for i = 1, n_conds do
    chunk = chunk .. ('  if i < %d then end\n'):format(i + n_conds)
  end
  -- `math.modf()` recording is NYI.
  chunk = chunk .. '  math.modf(1)\n'
  chunk = chunk .. 'end\n'
  return chunk
end

-- XXX: Need to compile the cycle in the `create_chunk()` to
-- preallocate the snapshot buffer.
jit.opt.start('hotloop=1', '-loop', '-fold')

-- XXX: Amount of slots is empirical.
local tracef = assert(loadstring(create_chunk(6)))

-- XXX: Remove previous trace.
jit.off()
jit.flush()

-- XXX: Update hotcounts to avoid hash collisions.
jit.opt.start('hotloop=1')
jit.on()

allocinject.enable()

tracef()

allocinject.disable()

test:ok(true, 'stack is balanced')

test:done(true)
