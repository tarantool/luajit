local tap = require('tap')

-- Test file to demonstrate LuaJIT misbehaviour in case of error
-- on growing stack for the coroutine during `coroutine.resume()`.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1066.

local test = tap.test('lj-1066-err-coroutine-resume')

test:plan(2)

local function resume_wrap()
  local function recurser()
    recurser(coroutine.yield())
  end
  local co = coroutine.create(recurser)
  -- Cause the stack overflow and throws an error with incorrect
  -- error message before the patch. Use some arguments to obtain
  -- the stack overflow faster.
  while coroutine.resume(co, 1, 2, 3, 4, 5, 6, 7, 8, 9) do end
end

local status, errmsg = pcall(resume_wrap)

test:is(status, false, 'status is correct')
test:like(errmsg, 'stack overflow', 'error message is correct')

test:done(true)
