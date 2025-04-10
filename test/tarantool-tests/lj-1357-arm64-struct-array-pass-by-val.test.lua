local ffi = require('ffi')
local tap = require('tap')

-- The test file to demonstrate incorrect FFI pass-by-value
-- structure with an array HFA member.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1357.
local test = tap.test('lj-1357-arm64-struct-array-pass-by-val')

test:plan(2)

local ffi_ccall = ffi.load('libfficcall')

ffi.cdef[[
  typedef struct hfa_float2 {
    float v[2];
  } hfa_float2;

  float hfa_float2_sum(hfa_float2 h);

  typedef union uhfa_float2 {
    float v[2];
  } uhfa_float2;

  float uhfa_float2_sum(uhfa_float2 h);
]]

test:is(ffi_ccall.hfa_float2_sum({{1, 2}}), 3, 'HFA float correct')
test:is(ffi_ccall.uhfa_float2_sum({{1, 2}}), 3, 'union HFA float correct')

test:done(true)
