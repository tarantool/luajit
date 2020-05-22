local tap = require('tap')
local test = tap.test('gh-6227-bytecode-allocator-for-comparisons')
test:plan(1)

-- Test file to demonstrate assertion failure during recording
-- wrong allocated bytecode for comparisons.
-- See also https://github.com/tarantool/tarantool/issues/6227.

-- Need function with RET0 bytecode to avoid reset of
-- the first JIT slot with frame info. Also need no assignments
-- by the caller.
local function empty() end

local uv = 0

-- This function needs to reset register enumerating.
-- Also set `J->maxslot` to zero.
-- The upvalue function to call is loaded to 0 slot.
local function bump_frame()
  -- First call function with RET0 to set TREF_FRAME in the
  -- last slot.
  empty()
  -- Test ISGE or ISGT bytecode. These bytecodes swap their
  -- operands. Also, a constant is always loaded into the slot
  -- smaller than upvalue. So, if upvalue loads before KSHORT,
  -- then the difference between registers is more than 2 (2 is
  -- needed for LJ_FR2) and TREF_FRAME slot is not rewriting by
  -- the bytecode after call and return as expected. That leads
  -- to recording slots inconsistency and assertion failure at
  -- `rec_check_slots()`.
  empty(1>uv)
end

jit.opt.start('hotloop=1')

for _ = 1,3 do
  bump_frame()
end

test:ok(true)
os.exit(test:check() and 0 or 1)
