local tap = require('tap')

local function unconfigured_timezone()
  -- `os.time()` uses `mktime()` to specify time by the given
  -- table. `mktime()` produces the call to `tzset()` to determine
  -- the system's timezone.
  -- If the TZ variable does not appear in the environment, the
  -- system timezone is used. The system timezone is configured by
  -- copying, or linking, a file in the tzfile(5) format to
  -- /etc/localtime. So, if this file is omitted, the errno is
  -- set to a non-zero value. This leads to the nil returned by
  -- the `os.time()` for -1 time value. Let's skip the test if
  -- this file is missed to be sure that we don't obtain any false
  -- positive failures due to system misconfigurations.
  local f = io.open('/etc/localtime', 'r')
  return not f
end

-- The test file demonstrates os.time() fail to return -1 time
-- value.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1470.
local test = tap.test('lj-1470-os-time-epoch-minus-1s'):skipcond({
  ['Unconfigured timezone rules'] = unconfigured_timezone(),
})

test:plan(1)

local minus_1s_time = os.date('*t', -1)
test:is(os.time(minus_1s_time), -1, 'correct os.time()')

test:done(true)
