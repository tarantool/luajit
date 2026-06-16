local tap = require('tap')
local bit = require('bit')
local jutil = require('jit.util')
local vmdef = require('jit.vmdef')

-- The test checks the optional `getpos` argument of
-- `jit.util.tracesnap()` that makes the function return the PC
-- position of the snapshot in the function bytecode.
-- See also https://github.com/LuaJIT/LuaJIT/issues/1472.

local test = tap.test('lj-1472-tracesnap-getpos'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(8)

-- Entries in `vmdef.bcnames` are 6 characters long.
local BC_NAME_LENGTH = 6

-- Return the name of the bytecode operation for the given
-- instruction, that is encoded in the low byte.
local function opname(ins)
  local oidx = BC_NAME_LENGTH * bit.band(ins, 0xff)
  local name = vmdef.bcnames:sub(oidx + 1, oidx + BC_NAME_LENGTH)
  return (name:gsub('%s+$', ''))
end

local function payload()
  local sum = 0
  for i = 1, 100 do
    sum = sum + i
  end
  return sum
end

-- Find the loop back-edge (FORL) in the function bytecode and
-- compute its jump target, that is the first instruction of the
-- loop body. `pc == 0` is the JCproto header, so real
-- instructions start from `pc == 1`. JIT compilation is disabled
-- while scanning, so this loop is not recorded as a trace.
jit.off()
local nbc = jutil.funcinfo(payload).bytecodes
local loop_entry
for pc = 1, nbc - 1 do
  local ins = jutil.funcbc(payload, pc)
  if opname(ins) == 'FORL' then
    -- The jump offset is relative to the next instruction and is
    -- biased by `BCBIAS_J`.
    local jmp = bit.rshift(ins, 16) - 0x8000
    loop_entry = pc + 1 + jmp
    break
  end
end
test:isnt(loop_entry, nil, 'FORL instruction is found')

-- Record a root loop trace in `payload`. Snapshot #0 points to
-- the loop entry (the FORL jump target).
jit.on()
jit.flush()
jit.opt.start('hotloop=1')
payload()

local info = jutil.traceinfo(1)
test:ok(info, 'the root loop trace is recorded')

local snap, pos = jutil.tracesnap(1, 0, true)
test:istable(snap, 'the snapshot table is returned')
test:is(pos, loop_entry, 'the PC position points to the loop entry')

local _, pos_without = jutil.tracesnap(1, 0)
test:is(pos_without, nil, 'no PC position without getpos')

local _, pos_false = jutil.tracesnap(1, 0, false)
test:is(pos_false, nil, 'no PC position with getpos=false')

local all_valid = true
for sn = 0, info.nexit - 1 do
  local _, p = jutil.tracesnap(1, sn, true)
  if type(p) ~= 'number' or p < 0 or p >= nbc or
     jutil.funcbc(payload, p) == nil then
    all_valid = false
  end
end
test:ok(all_valid, 'positions of all snapshots are valid offsets')

test:is(select('#', jutil.tracesnap(1, info.nexit, true)), 0,
        'out-of-range snapshot returns nothing')

test:done(true)
