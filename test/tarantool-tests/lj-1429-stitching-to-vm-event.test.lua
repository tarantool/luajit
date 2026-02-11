local tap = require('tap')

-- The test file to demonstrate the incorrect recording of the
-- trace when stitching in the VM event.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1429.

local test = tap.test('lj-1429-stitching-to-vm-event'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

local function always_number(val)
  return tonumber(val) or 1
end

-- This handler leads to stitching in the VM event.
local function hdl()
  always_number('')
end

jit.opt.start('hotloop=1', 'hotexit=1')

jit.attach(hdl, 'trace')

coroutine.wrap(function()
  always_number('')
  always_number('')
  always_number(0) -- Start side trace, invoke handler.
  -- This breaks the recording semantics before the patch.
end)()

test:ok(true, 'no assertion failure')

test:done(true)
