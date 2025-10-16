local tap = require('tap')

-- Test file to demonstrate LuaJIT incorrect error message for the
-- errors in the error handler.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1381.

local test = tap.test('lj-1381-fix-errmsg-in-err-handler')

local allocinject = require('allocinject')

test:plan(6)

-- Disable JIT to avoid multiple invocation of the error handler.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1382.
jit.off()

-- OOM on the creation of ERRERR message.
coroutine.wrap(function()
  allocinject.enable_null_alloc()
  local st, msg = xpcall(error, error)
  allocinject.disable()
  test:ok(not st, 'OOM ERRERR incorrect status')
  -- Prevent preallocated error message.
  test:ok(msg:match('error in ' .. 'error handling'),
          'OOM ERRERR incorrect errmsg: ' .. msg)
end)()

-- OOM in the error handler.
coroutine.wrap(function()
  local function errmem() local _ = {} end
  allocinject.enable_null_alloc()
  local st, msg = xpcall(error, errmem)
  allocinject.disable()
  test:ok(not st, 'OOM incorrect status')
  -- Prevent preallocated error message.
  test:ok(msg:match('error in ' .. 'error handling'),
          'OOM incorrect errmsg: ' .. msg)
end)()

-- STKOV in the error handler.
coroutine.wrap(function()
  local function stkov() stkov() end
  local st, msg = xpcall(error, stkov)
  test:ok(not st, 'STKOV incorrect status')
  -- Prevent preallocated error message.
  test:ok(msg:match('error in ' .. 'error handling'),
          'STKOV incorrect errmsg: ' .. msg)
end)()

test:done(true)
