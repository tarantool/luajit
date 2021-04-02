local M = {}

local tap = require('tap')

local function luacmd(args)
  -- arg[-1] is guaranteed to be not nil.
  local idx = -2
  while args[idx] do
    assert(type(args[idx]) == 'string', 'Command part have to be a string')
    idx = idx - 1
  end
  -- return the full command with flags.
  return table.concat(args, ' ', idx + 1, -1)
end

function M.selfrun(arg, checks)
  -- If TEST_SELFRUN is set, it means the test has been run via
  -- <io.popen>, so just return from this routine and proceed
  -- the execution to the test payload, ...
  if os.getenv('TEST_SELFRUN') then return end

  -- ... otherwise initialize <tap>, setup testing environment
  -- and run this chunk via <io.popen> for each case in <checks>.
  -- XXX: The function doesn't return back from this moment. It
  -- checks whether all assertions are fine and exits.

  local test = tap.test(arg[0]:match('/?(.+)%.test%.lua'))

  test:plan(#checks)

  local vars = {
    LUABIN = luacmd(arg),
    SCRIPT = arg[0],
    PATH   = arg[0]:gsub('%.test%.lua', ''),
    SUFFIX = package.cpath:match('?.(%a+);'),
  }

  local cmd = string.gsub('LUA_PATH="<PATH>/?.lua;$LUA_PATH" ' ..
                          'LUA_CPATH="<PATH>/?.<SUFFIX>;$LUA_CPATH" ' ..
                          'LD_LIBRARY_PATH=<PATH>:$LD_LIBRARY_PATH ' ..
                          'TEST_SELFRUN=1' ..
                          '<LUABIN> 2>&1 <SCRIPT>', '%<(%w+)>', vars)

  for _, ch in pairs(checks) do
    local testf = test[ch.test]
    assert(testf, ("tap doesn't provide test.%s function"):format(ch.test))
    local proc = io.popen((cmd .. (' %s'):rep(#ch.arg)):format(unpack(ch.arg)))
    local res = proc:read('*all'):gsub('^%s+', ''):gsub('%s+$', '')
    -- XXX: explicitly pass <test> as an argument to <testf>
    -- to emulate test:is(...), test:like(...), etc.
    testf(test, res, ch.res, ch.msg)
  end

  os.exit(test:check() and 0 or 1)
end

function M.skipcond(condition, message)
  if not condition then return end
  local test = tap.test(arg[0]:match('/?(.+)%.test%.lua'))
  test:plan(1)
  test:skip(message)
  os.exit(test:check() and 0 or 1)
end

return M
