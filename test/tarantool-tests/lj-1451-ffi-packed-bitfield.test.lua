local tap = require('tap')

-- Test file to demonstrate LuaJIT's incorrect behaviour of the
-- `#pragma` pack directive for bitfields in structures.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1451.

local test = tap.test('lj-1451-ffi-packed-bitfield')

local ffi = require('ffi')

ffi.cdef[[
#pragma pack(push, 2)

typedef struct {
  unsigned int bitfield:1;
} packed_struct;

typedef struct {
  unsigned int bitfield0:1;
  unsigned int bitfield15:15;
  unsigned int bitfield16:1;
} packed_struct2;

#pragma pack(pop)
]]

test:plan(5)

local packed = ffi.new('packed_struct')

-- Check that there is no heap overflow for the packed FFI
-- structure. That read/write access leads to the failure when
-- LuaJIT is built with ASAN support.
test:is(packed.bitfield, 0, 'ASAN: correct 0-initialization')

packed.bitfield = 1
test:is(packed.bitfield, 1, 'ASAN: bitfield set correctly')

-- Check correct structure layout.
local byteoffset, bitpos, bitsize = ffi.offsetof('packed_struct2', 'bitfield16')
test:is(byteoffset, 2, 'byteoffset is correct')
test:is(bitpos, 0, 'bitpos is correct')
test:is(bitsize, 1, 'bitsize is correct')

test:done(true)
