local ffi = require('ffi')
local tap = require('tap')

-- The test file demonstrates incorrect FFI attributes for the
-- structure with a zero-sized bitfield.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1455.
local test = tap.test('lj-1455-ffi-conventions')

test:plan(3)

ffi.cdef[[
  typedef struct {
          int x;
          int : 0 __attribute__((aligned(16)));
          int y;
          int z;
  } intx3_0bitfield_a16;
]]

test:is(ffi.sizeof(ffi.new('intx3_0bitfield_a16')), 24,
        'correct size of struct with 0 bitfield')
test:is(ffi.offsetof('intx3_0bitfield_a16', 'y'), 16,
        'correct offset of field after 0 bitfield')
test:is(ffi.alignof('intx3_0bitfield_a16'), 4,
        'correct total align of struct with 0 bitfield')

test:done(true)
