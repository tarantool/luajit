local tap = require('tap')
local utils = require('utils')

local test = tap.test('bc-jit-unpatching')
test:plan(1)

-- Function with up-recursion.
local function f(n)
  return n < 2 and n or f(n - 1) + f(n - 2)
end

local ret1bc = 'RET1%s*1%s*2'
-- Check that this bytecode still persists.
assert(utils.hasbc(load(string.dump(f)), ret1bc))

jit.opt.start('hotloop=1', 'hotexit=1')
-- Compile function to get JLOOP bytecode in recursion.
f(5)

test:ok(utils.hasbc(load(string.dump(f)), ret1bc), 'bytecode unpatching is OK ')

os.exit(test:check() and 0 or 1)
