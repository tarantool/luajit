local tap = require('tap')

-- Test file to demonstrate incorrect snapshot purge for the
-- `pcall()` and `xpcall()`.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1425.

local test = tap.test('lj-1425-pcall-snap-purge'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

-- `pcall()` and `xpcall()`.
test:plan(2)

-- XXX: simplify `jit.dump()` output.
local type = type
local pcall = pcall
local xpcall = xpcall
local math_modf = math.modf
local debug_getlocal = debug.getlocal

local checkers = {}

-- Called twice for the pseudo-type that aliases base Lua type via
-- checkers map.
local function checks(expected_type)
  -- Value expected to be `checks_tab()` or `checks_obj()`
  -- argument. It is always a table.
  local _, value = debug_getlocal(2, 1)
  -- Simple stitching function. Additional arguments are needed to
  -- occupy the corresponding slot.
  math_modf(0, nil, nil)
  -- Start trace now, one iteration only.
  -- luacheck: ignore 512
  while true do
    -- Base type?
    if type(value) == expected_type then
      return true
    end
    -- Pseudo types fallbacks to the map.
    local checker = checkers[expected_type]
    -- For the xpcall.
    if checker(value) == true then
      return true
    end
    break
  end
  error('Unreachable path taken')
end

-- Need to be pcalled.
local function checks_tab(_)
  checks('table')
end

local function checks_tab_p(map)
  return pcall(checks_tab, map)
end

local function nop()
end

local function checks_tab_xp(map)
  return xpcall(checks_tab, nop, map)
end

local function checks_obj(_)
  checks('obj')
end

local function check_ff(name, checks_func)
  test:test(name, function(subtest)
    subtest:plan(1)

    checkers['obj'] = checks_func

    jit.flush()
    jit.opt.start('hotloop=1')

    checks_obj({})
    -- Forcify stack reallocation on trace in `checks()`. The
    -- source stack lacks the needed slot.
    coroutine.wrap(function()
      checks_obj({})
    end)()

    subtest:ok(true, 'No error for ' .. name)
  end)
end

check_ff('pcall', checks_tab_p)
check_ff('xpcall', checks_tab_xp)

test:done(true)
