local ffi = require('ffi')
local tap = require('tap')

local ffi_ccall = ffi.load('libfficcall')

-- The test file to check the FFI call for small (<8 bytes)
-- arguments give on stack.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/205.
local test = tap.test('lj-205-arm64-osx-ffi-small-arg')
test:plan(2)

ffi.cdef[[
  uint8_t test_u8_stack(uint8_t u1, uint8_t u2, uint8_t u3, uint8_t u4,
                        uint8_t u5, uint8_t u6, uint8_t u7, uint8_t u8,
                        uint8_t u9, uint8_t u10, uint8_t u11);

  float test_float_stack(float f1, float f2, float f3, float f4, float f5,
                         float f6, float f7, float f8, float f9, float f10,
                         float f11);
]]

test:is(ffi_ccall.test_u8_stack(1ULL, 2ULL, 3ULL, 4ULL, 5ULL, 6ULL, 7ULL,
                                8ULL, 9ULL, 10ULL, 11ULL),
        66, 'correct uint8_t stack pass')

test:is(ffi_ccall.test_float_stack(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11), 66,
        'correct float stack pass')

test:done(true)
