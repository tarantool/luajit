local ffi = require('ffi')
local tap = require('tap')

-- Test file to demonstrate the incorrect JIT recording for
-- `tonumber()` function with cdata argument for failed
-- conversions.
-- See also https://github.com/LuaJIT/LuaJIT/issues/408,
-- https://github.com/LuaJIT/LuaJIT/pull/412,
-- https://github.com/LuaJIT/LuaJIT/pull/412,
-- https://github.com/tarantool/tarantool/issues/7655.
local test = tap.test('lj-408-tonumber-cdata-record')

local NULL = ffi.cast('void *', 0)

test:plan(4)

-- This test won't fail for GC64 on x86_64. This happens due to
-- wrong instruction emitting for SLOAD IR -- we always exit by
-- the assertion guard on the argument type check. See also
-- https://github.com/LuaJIT/LuaJIT/pull/350.
-- The test fails without fix in the current commit, if the
-- following commit is backported:
-- https://github.com/LuaJIT/LuaJIT/commit/05fbdf56
-- Feel free to remove this comment after backporting of the
-- aforementioned commit.
local function check(x)
  -- Don't use a tail call to avoid "leaving loop in root trace"
  -- error, so the trace will be compiled.
  local res = tonumber(x)
  return res
end

jit.opt.start('hotloop=1')
-- Record `check()` with `tonumber(NULL)` -- not converted.
check(NULL)
check(NULL)

test:ok(not check(NULL), 'recorded with NULL and not converted for NULL')
test:ok(check(0LL), 'recorded with NULL and converted for 0LL')

-- Reset JIT.
jit.off()
jit.flush()
jit.on()

-- Record `check()` with `tonumber(0LL)` -- converted.
check(0LL)
check(0LL)

test:ok(check(0LL), 'recorded with 0LL and converted for 0LL')
test:ok(not check(NULL), 'recorded with 0LL and not converted for NULL')

os.exit(test:check() and 0 or 1)
