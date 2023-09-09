local tap = require('tap')

-- The test file to demonstrate incorrect LuaJIT's fusing of the
-- sign extension instruction into logical instructions.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1076.
local test = tap.test('lj-1076-not-fuse-sign-ext-logical'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(5)

jit.opt.start('hotloop=1')

local ffi = require('ffi')
local cast = ffi.cast

local bnot = bit.bnot

local N = -5

-- Test avoiding erroneous fusing of:
-- |  sxtw  x1, w4
-- |  mvn   x0, x1
--
-- to the:
-- | mov   x0, x4, lsl #48

local r = {}
for i = 1, 4 do
  r[i] = bnot(cast('int64_t', N))
end

test:is(r[1], 4LL, 'correct result for bnot')
test:samevalues(r, 'avoid fusion for explicit CONV with sign extension')

-- Test avoiding erroneous fusing of:
-- | sxtw  x21, w23
-- | orr   x20, x20, x21
--
-- to the:
-- | orn   x20, x20, x23, lsl #48

local function logical_shift_unfused(subtest, expected)
  subtest:plan(2)
  jit.flush()
  jit.opt.start('hotloop=1')
  -- Use code generation to avoid using non-constant variables
  -- defining functions preventing folding and fusion.
  local script = string.format([[
    local bor = bit.bor
    local arshift, lshift, rshift = bit.arshift, bit.lshift, bit.rshift
    local N = -5
    local zero = 0LL
    local result = {}
    for i = 1, 4 do
      result[i] = bor(%s(N, 1), zero)
    end
    return result
  ]], subtest.name)
  local f = assert(loadstring(script, 'unfused ' .. subtest.name))
  local result = f()
  subtest:is(result[1], expected, 'correct result for ' .. subtest.name)
  subtest:samevalues(result, 'avoid fusion sxtw and orr for ' .. subtest.name)
end

test:test('arshift', logical_shift_unfused, -3LL)
test:test('lshift',  logical_shift_unfused, -10LL)
test:test('rshift',  logical_shift_unfused, 0x7FFFFFFDLL)

test:done(true)
