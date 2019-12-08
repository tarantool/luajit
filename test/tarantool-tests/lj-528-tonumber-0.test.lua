local tap = require('tap')

-- Test disabled for DUALNUM mode default for some arches.
-- See also https://github.com/LuaJIT/LuaJIT/pull/787.
require('utils').skipcond(
  jit.arch ~= 'x86' and jit.arch ~= 'x64',
  jit.arch..' in DUALNUM mode is clumsy for now'
)

-- Test file to demonstrate LuaJIT `tonumber('-0')` incorrect
-- behaviour.
-- See also https://github.com/LuaJIT/LuaJIT/issues/528.
local test = tap.test('lj-528-tonumber-0')
test:plan(1)

-- As numbers -0 equals to 0, so convert it back to string.
test:ok(tostring(tonumber('-0')) == '-0', 'correct "-0" string parsing')

os.exit(test:check() and 0 or 1)
