local ffi = require('ffi')
local tap = require('tap')

local ffi_ccall = ffi.load('libfficcall')

-- The test file to check the FFI call for enum arguments.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/205.
local test = tap.test('lj-205-arm64-osx-ffi-enum-arg'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(4)

ffi.cdef[[
  int sprintf(char *str, const char *format, ...);

  typedef enum {
    E1 = 1,
    E2 = 2,
    E3 = 3,
    E4 = 4,
    E5 = 5,
    E6 = 6,
    E7 = 7,
    E8 = 8,
    E9 = 9,
    E10 = 10,
    E11 = 11
  } enum_t;

  int test_enum_reg(enum_t e1, enum_t e2, enum_t e3);

  int test_enum_stack(enum_t e1, enum_t e2, enum_t e3, enum_t e4, enum_t e5,
                      enum_t e6, enum_t e7, enum_t e8, enum_t e9, enum_t e10,
                      enum_t e11);
]]


local str = ffi.new(string.format('char[256]'))

jit.opt.start('hotloop=1')

local enum_t = ffi.typeof('enum_t')

local results = {}
for i = 1, 4 do
  local strlen = ffi.C.sprintf(str, '%d', enum_t(1))
  assert(strlen == 1, 'correct string length for result')
  results[i] = ffi.string(str)
end

test:is(results[1], '1', 'correct result of FFI vararg call for enum')
test:samevalues(results, 'consistent behaviour JIT and VM for vararg enum arg')

test:is(ffi_ccall.test_enum_reg(enum_t(1), enum_t(2), enum_t(3)), 6,
        'correct enum reg pass')

test:is(ffi_ccall.test_enum_stack(enum_t(1), enum_t(2), enum_t(3), enum_t(4),
                                  enum_t(5), enum_t(6), enum_t(7), enum_t(8),
                                  enum_t(9), enum_t(10), enum_t(11)),
        66, 'correct enum stack pass')

test:done(true)
