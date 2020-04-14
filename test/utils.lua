local M = { }

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

  local cmd = string.gsub('LUA_CPATH="$LUA_CPATH;<PATH>/?.<SUFFIX>" ' ..
                          'LUA_PATH="$LUA_PATH;<PATH>/?.lua" ' ..
                          'LD_LIBRARY_PATH=<PATH> ' ..
                          '<LUABIN> 2>&1 <SCRIPT>', '%<(%w+)>', vars)

  for _, ch in pairs(checks) do
    local res
    local proc = io.popen((cmd .. (' %s'):rep(#ch.arg)):format(unpack(ch.arg)))
    for s in proc:lines() do res = s end
    assert(res, 'proc:lines failed')
    test:is(res, ch.res, ch.msg)
  end

  os.exit(test:check() and 0 or 1)
end

return M
