local tap = require('tap')
local test = tap.test('lj-1117-fuse-loads'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)
local clear = require('table.clear')
local ffi = require('ffi')

local tab = {0}
local alias = tab
local result = {}

jit.opt.start('hotloop=1')
for i = 1, 4 do
  local val = tab[1]
  clear(tab)
  result[i] = ffi.cast('int64_t', val)
  alias[1] = 0
end

test:samevalues(result, 'no fusion across table.clear')
test:done(true)
