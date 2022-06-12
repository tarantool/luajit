-- Sysprof is implemented for x86 and x64 architectures only.
require('utils').skipcond(
  jit.arch ~= 'x86' and jit.arch ~= 'x64' or jit.os ~= 'Linux'
    or require('ffi').abi('gc64'),
  jit.arch..' architecture or '..jit.os..
  ' OS is NIY for sysprof'
)

local tap = require('tap')
local test = tap.test('gh-7264-add-proto-trace-sysprof-default.test.lua')
test:plan(2)

local chunk = [[
return function()
  local a = 'teststring'
end
]]

local function allocate()
  local a = {}
  for _ = 1, 3 do
    table.insert(a, 'teststring')
  end
  return a
end

-- Proto creation during the sysprof runtime.
jit.off()

assert(misc.sysprof.start({ mode = 'D' }))
-- The first call yields the anonymous function created by loading
-- <chunk> proto. As a result the child proto function is yielded.
-- The second call invokes the child proto function to trigger
-- <lj_sysprof_add_proto> call.
assert(load(chunk))()()
test:ok(misc.sysprof.stop(), 'new proto in sysprof runtime')

-- Trace creation during the sysprof runtime.
jit.flush()
jit.opt.start('hotloop=1')
jit.on()

assert(misc.sysprof.start({ mode = 'D' }))
-- Run <allocate> function to record a new trace. As a result,
-- <lj_sysprof_add_trace> is triggered to be invoked.
allocate()
test:ok(misc.sysprof.stop(), 'trace record in sysprof runtime')

os.exit(test:check() and 0 or 1)
