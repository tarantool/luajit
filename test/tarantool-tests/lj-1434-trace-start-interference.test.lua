local tap = require('tap')

-- The test file to demonstrate the incorrect recording of the
-- trace when facing the trace exit in the VM event (start).
-- See also https://github.com/LuaJIT/LuaJIT/issues/1434.

local test = tap.test('lj-1434-trace-start-interference'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

local function call(self)
  return self
end

local function cb()
  -- Side exit for trace 1.
  call(nil)
end

jit.opt.start('hotloop=1', 'hotexit=1');

jit.attach(cb, 'trace')

coroutine.wrap(function()
  for i = 1, 4 do
    -- Record trace 1.
    call(call(i))
    -- Start trace 2. Side exit from trace 1 in the 'trace start'
    -- VM event converts the second trace to the "side trace".
    -- After that the VM assertion `lj_assert_bad_for_arg_type()`
    -- fails, since we return from the VM event in the middle of
    -- another frame.
  end
end)()

test:ok(true, 'no assertion failure')

test:done(true)
