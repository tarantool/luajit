local tap = require('tap')

-- Test file to demonstrate LuaJIT incorrect behaviour during
-- parsing and working with ctypes with attributes.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/861.

local test = tap.test('lj-861-ctype-attributes')
local ffi = require('ffi')

test:plan(2)

local EXPECTED_ALIGN = 4

ffi.cdef([[
struct __attribute__((aligned($))) s_aligned {
  uint8_t a;
};
]], EXPECTED_ALIGN)

local ref_align = ffi.alignof(ffi.typeof('struct s_aligned &'))

test:is(ref_align, EXPECTED_ALIGN, 'the reference alignment is correct')
test:is(ref_align, ffi.alignof(ffi.typeof('struct s_aligned')),
        'the alignment of a reference is the same as for the referenced type')

test:done(true)
