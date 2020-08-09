local tap = require('tap')

-- Test to demonstrate the incorrect JIT behaviour when an error
-- is raised on restoration from the snapshot.
-- See also https://github.com/LuaJIT/LuaJIT/issues/603.
local test = tap.test('lj-603-err-snap-restore.test.lua')
test:plan(1)

local recursive_f
local function errfunc()
  xpcall(recursive_f, errfunc)
end

-- A recursive call to itself leads to trace with up-recursion.
-- When the Lua stack can't be grown more, error is raised on
-- restoration from the snapshot.
recursive_f = function()
  xpcall(recursive_f, errfunc)
  errfunc = function() end
  recursive_f = function() end
end
recursive_f()

test:ok(true)

-- XXX: Don't use `os.exit()` here by intention. When error on
-- snap restoration is raised, `err_unwind()` doesn't stop on
-- correct cframe. So later, on exit from VM this corrupted cframe
-- chain shows itself. `os.exit()` literally calls `exit()` and
-- doesn't show the issue.
