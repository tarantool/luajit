local tap = require('tap')

local test = tap.test('lj-556-fix-loop-realignment')
test:plan(1)

-- Test file to demonstrate JIT misbehaviour for loop realignment
-- in LUAJIT_NUMMODE=2. See also
-- https://github.com/LuaJIT/LuaJIT/issues/556.

jit.opt.start('hotloop=1')

local s = 4
while s > 0 do
  s = s - 1
end

test:ok(true, 'loop is compiled and ran successfully')
os.exit(test:check() and 0 or 1)
