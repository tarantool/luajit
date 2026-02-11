local tap = require('tap')

-- Test file to demonstrate incorrect allocation limit for the
-- non-GC64 build with disabled JIT.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1430.

local test = tap.test('lj-1430-internal-alloc-limit')

test:plan(1)

-- This function creates a bunch of long array-like tables.
-- Eventually for one of the tables the address of the array
-- element will not fit in the 31-bit range, causing the incorrect
-- arithmetic inside the VM and a crash or assertion failure
-- during the reallocation.
local function test_payload()
  local POOL_SZ = 8
  -- luacheck: no unused
  local pools = {}
  for i = 1, POOL_SZ do
    pools[i] = {}
  end

  local v = 1
  for j = 1, POOL_SZ do
    for i = 1, 0x2000000 do
      pools[j][i] = v
    end
  end
end

-- XXX: We are interested in the VM semantics in the first place.
-- Enabling JIT may lead to the PANIC when the OOM is raised on
-- the trace for the 2.11 branch.
jit.off()

-- Protect the call to avoid the OOM.
pcall(test_payload)

-- Free memory for the TAP tests.
collectgarbage()

test:ok(true, 'no crash or assertion failure')
test:done(true)
