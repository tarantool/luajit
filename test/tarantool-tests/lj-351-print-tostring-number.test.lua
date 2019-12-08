local utils = require('utils')

local cases = {
  {typename = 'nil', value = 'nil'},
  {typename = 'boolean', value = 'true'},
  {typename = 'number', value = '42'},
  -- FIXME: Test case below is disabled, because __tostring
  -- metamethod isn't checked for string base metatable.
  -- See also https://github.com/tarantool/tarantool/issues/6746.
  -- {typename = 'string', value = '[[teststr]]'},
  {typename = 'table', value = '{}'},
  {typename = 'function', value = 'function() end'},
  {typename = 'userdata', value = 'newproxy()'},
  {typename = 'thread', value = 'coroutine.create(function() end)'},
  {typename = 'cdata', value = '1ULL'}
}

local checks = {}

for i, case in pairs(cases) do
  checks[i] = {
    arg = {('"%s"'):format(case.value), case.typename},
    msg = ('%s'):format(case.typename),
    res = ('__tostring is reloaded for %s'):format(case.typename),
    test = 'is',
  }
end

utils.selfrun(arg, checks)

----- Test payload. ----------------------------------------------

local test = [[
  local testvar = %s
  debug.setmetatable(testvar, {__tostring = function(o)
    return ('__tostring is reloaded for %s'):format(type(o))
  end})
  print(testvar)
]]

pcall(load(test:format(unpack(arg))))
