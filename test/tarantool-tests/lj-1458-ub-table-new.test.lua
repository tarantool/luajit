local tap = require('tap')

-- The test file to demonstrate UBSan warning for `table.new()`
-- with a minimal and maximum array and hash parts values.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1458.
local test = tap.test('lj-1458-ub-table-new')

local INT_MAX = 2 ^ 31 - 1
local INT_MIN = -2 ^ 31

local table_sizes = {
  { 0, INT_MIN },
  { 0, INT_MAX },
  { INT_MIN, 0 },
  { INT_MAX, 0 },
}

test:plan(#table_sizes * 2)

local table_new = require('table.new')

for _, case in ipairs(table_sizes) do
  local apart, hpart = unpack(case)
  local ok, err = pcall(table_new, apart, hpart)
  local message = ('table.new(%d, %d)'):format(apart, hpart)
  test:is(ok, false, message .. ' is ok')
  test:ok(err:match('table overflow'), message .. ' correct error message')
end

test:done(true)
