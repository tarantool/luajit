local tap = require('tap')

-- The test file to demonstrate LuaJIT's incorrect invocation of
-- the VM event handler for the 'errfin' VM event.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1445.

local test = tap.test('lj-1445-errfin-errmsg')

test:plan(2)

local EXPECTED_ERR = 'expected error'
local function bad_fin()
  error(EXPECTED_ERR)
end
local EXPECTED_LOCATION = debug.getinfo(bad_fin).linedefined + 1

local match_err = false
local match_line = false
local function errfin_handler(errmsg)
  match_err = errmsg:match(EXPECTED_ERR)
  match_line = errmsg:match(EXPECTED_LOCATION)
end

jit.attach(errfin_handler, 'errfin')

-- Create the userdata with the finalizer and collect it.
debug.getmetatable(newproxy(true)).__gc = bad_fin
collectgarbage()

test:ok(match_err, 'correct error message in errfin handler')
test:ok(match_line, 'correct source line in errfin handler')

test:done(true)
