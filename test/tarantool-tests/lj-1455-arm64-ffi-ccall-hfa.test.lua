local ffi = require('ffi')
local tap = require('tap')

-- The test file to test various FFI C call conventions for HFA
-- aggregates.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1455.
local test = tap.test('lj-1455-arm64-ffi-ccall-hfa')

test:plan(7)

local ffi_ccall = ffi.load('libfficcall')

ffi.cdef[[
  typedef struct hfa_float22 {
    float v[2][2];
  } hfa_float22;


  typedef struct non_hfa_float222 {
    float v[2][2][2];
  } non_hfa_float222;

  typedef struct hfa_float_hole {
    float x;
    float hole[0][2][2];
    float y;
  } hfa_float_hole;

  typedef struct hfa_double2 {
    double v[2];
  } hfa_double2;

  typedef struct hfa_double2_a16 {
    __attribute__((__aligned__(16))) double v[2];
  } hfa_double2_a16;

  typedef struct hfa_double2_a32 {
    __attribute__((__aligned__(32))) double v[4];
  } hfa_double2_a32;

  float hfa_float22_sum(hfa_float22 h);
  double hfa_double2_sum(hfa_double2 h);
  double hfa_double2_a16_sum(hfa_double2_a16 h);
  double hfa_double2_a32_sum(hfa_double2_a32 h);

  typedef struct hfa_0bitfield {
    float x;
    int : 0;
    float y;
    float z;
  } hfa_0bitfield;

  float hfa_0bitfield_sum(hfa_0bitfield h);

  float non_hfa_float222_sum(non_hfa_float222 h);

  float hfa_float_hole_sum(hfa_float_hole h);
]]

test:is(ffi_ccall.hfa_float22_sum({{{1, 2}, {3, 4}}}), 10,
        'HFA 2 dimensional correct')
test:is(ffi_ccall.non_hfa_float222_sum({{{{1, 2}, {3, 4}},{{5, 6}, {7, 8}}}}),
        36, 'non HFA array correct')
local supported, func = pcall(function()
  return ffi_ccall.hfa_float_hole_sum
end)
if supported then
  test:is(func({x = 1, y = 2}), 3, 'HFA float hole correct')
else
  test:skip('HFA float hole -- Unsupported by C compiler')
end
test:is(ffi_ccall.hfa_double2_sum({{1, 2}}), 3, 'HFA double correct')
test:is(ffi_ccall.hfa_double2_a16_sum({{1, 2}}), 3, 'align 16 correct')
test:is(ffi_ccall.hfa_double2_a32_sum({{1, 2, 3, 4}}), 10, 'align 32 correct')
supported, func = pcall(function() return ffi_ccall.hfa_0bitfield_sum end)
if supported then
  test:is(func({x = 1, y = 2, z = 3}), 6, 'HFA 0 bitfield correct')
else
  test:skip('HFA 0 bitfield -- Unsupported by C compiler')
end

test:done(true)
