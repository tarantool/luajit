local tap = require('tap')

-- The test file to demonstrate LuaJIT incorrect FFI vararg call
-- on macOS M1.
-- See also: https://github.com/tarantool/tarantool/issues/6097.
local test = tap.test('gh-6097-arm64-osx-ffi-vararg'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(4)

local ffi = require('ffi')

ffi.cdef('int sprintf(char *str, const char *format, ...)')

local EXPECTED = '1'
local EXPECTED_LEN = #EXPECTED

local str = ffi.new(string.format('char[256]'))

jit.opt.start('hotloop=1')

local results = {}
for i = 1, 4 do
  local strlen = ffi.C.sprintf(str, '%d', 1LL)
  assert(strlen == EXPECTED_LEN, 'correct string length for result')
  results[i] = ffi.string(str)
end

test:is(results[1], EXPECTED, 'correct result of FFI vararg call for int')
test:samevalues(results, 'consistent behaviour JIT and VM for vararg int arg')

results = {}
for i = 1, 4 do
  local strlen = ffi.C.sprintf(str, '%c', ffi.new('char', string.byte('1')))
  assert(strlen == EXPECTED_LEN, 'correct string length for result')
  results[i] = ffi.string(str)
end

test:is(results[1], EXPECTED, 'correct result of FFI vararg call for char')
test:samevalues(results, 'consistent behaviour JIT and VM for vararg char arg')

test:done(true)
