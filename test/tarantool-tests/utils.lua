local M = {}

local tap = require('tap')

function M.selfrun(arg, checks)
  local test = tap.test(arg[0]:match('/?(.+)%.test%.lua'))

  test:plan(#checks)

  local vars = {
    LUABIN = arg[-1],
    SCRIPT = arg[0],
    PATH   = arg[0]:gsub('%.test%.lua', ''),
    SUFFIX = package.cpath:match('?.(%a+);'),
  }

  local cmd = string.gsub('LUA_PATH="<PATH>/?.lua;$LUA_PATH" ' ..
                          'LUA_CPATH="<PATH>/?.<SUFFIX>;$LUA_CPATH" ' ..
                          'LD_LIBRARY_PATH=<PATH>:$LD_LIBRARY_PATH ' ..
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
