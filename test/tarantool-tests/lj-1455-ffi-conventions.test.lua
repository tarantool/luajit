local ffi = require('ffi')
local tap = require('tap')

-- The test file to test various FFI C call conventions.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1455.
local test = tap.test('lj-1455-ffi-conventions')

test:plan(39)

local ffi_ccall = ffi.load('libfficcall')

ffi.cdef[[
  typedef struct hfa_floatx4_a16 {
          float v[4];
  } __attribute__((aligned(16))) hfa_floatx4_a16;

  float test_2_align_hfa(int i, hfa_floatx4_a16 s1, hfa_floatx4_a16 s2);

  typedef struct intx4_a16 {
          int v[4];
  } __attribute__((aligned(16))) intx4_a16;

  int test_2_intx4_a16(int i, intx4_a16 s1, intx4_a16 s2);

  typedef struct large_agg_a16 {
          int v[18];
  } __attribute__((aligned(16))) large_agg_a16;

  int test_2_large_agg_a16(int x, large_agg_a16 s1, large_agg_a16 s2);

  typedef struct intx3_0bitfield {
          int x;
          int : 0;
          int y;
          int z;
  } intx3_0bitfield;

  int test_2_intx3_0bitfield_reg(int i, intx3_0bitfield s1, intx3_0bitfield s2);
  int test_2_intx3_0bitfield_stack(int i, int i2, int i3, int i4, int i5,
                                   int i6, int i7, int i8, int i9,
                                   intx3_0bitfield s1, intx3_0bitfield s2);

  typedef struct intx3_0bitfield_a16 {
          int x;
          int : 0 __attribute__((aligned(16)));
          int y;
          int z;
  } intx3_0bitfield_a16;

  int test_2_intx3_0bitfield_a16_reg(int i, intx3_0bitfield_a16 s1,
                                     intx3_0bitfield_a16 s2);
  int test_2_intx3_0bitfield_a16_stack(int i, int i2, int i3, int i4, int i5,
                                       int i6, int i7, int i8, int i9,
                                       intx3_0bitfield_a16 s1,
                                       intx3_0bitfield_a16 s2);

  typedef struct intx3_full_bitfield_a16 {
          int x;
          int y: 32 __attribute__((aligned(16)));
          int z;
  } intx3_full_bitfield_a16;

  int test_2_intx3_full_bitfield_a16_reg(int i, intx3_full_bitfield_a16 s1,
                                         intx3_full_bitfield_a16 s2);
  int test_2_intx3_full_bitfield_a16_stack(int i, int i2, int i3, int i4,
                                           int i5, int i6, int i7, int i8,
                                           int i9, intx3_full_bitfield_a16 s1,
                                           intx3_full_bitfield_a16 s2);

  typedef struct intx3_half_bitfield {
          int x : 16;
          int y : 16;
          int z;
  } intx3_half_bitfield;

  int test_2_intx3_half_bitfield_reg(int i, intx3_half_bitfield s1,
                                     intx3_half_bitfield s2);
  int test_2_intx3_half_bitfield_stack(int i, int i2, int i3, int i4, int i5,
                                       int i6, int i7, int i8, int i9,
                                       intx3_half_bitfield s1,
                                       intx3_half_bitfield s2);

  typedef struct intx3_half_bitfield_a16 {
          int x : 16;
          int y : 16 __attribute__((aligned(16)));
          int z;
  } intx3_half_bitfield_a16;

  int test_2_intx3_half_bitfield_a16_reg(int i, intx3_half_bitfield_a16 s1,
                                         intx3_half_bitfield_a16 s2);
  int test_2_intx3_half_bitfield_a16_stack(int i, int i2, int i3, int i4,
                                           int i5, int i6, int i7, int i8,
                                           int i9, intx3_half_bitfield_a16 s1,
                                           intx3_half_bitfield_a16 s2);

  typedef struct la16l {
          long long x __attribute__((aligned(16)));
          long long y;
  } la16l;

  int test_2_la16l_reg(int i, la16l s1, la16l s2);
  int test_2_la16l_stack(int i, int i2, int i3, int i4, int i5, int i6, int i7,
                         int i8, int i9, la16l s1, la16l s2);

  typedef struct a16_tsp {
          struct {
                  long long x;
                  long long y;
          } __attribute__((aligned(16)));
  } a16_tsp;

  int test_2_a16_tsp_reg(int i, a16_tsp s1, a16_tsp s2);
  int test_2_a16_tsp_stack(int i, int i2, int i3, int i4, int i5, int i6,
                           int i7, int i8, int i9, a16_tsp s1, a16_tsp s2);

  typedef struct f_a16_tsp {
          struct {
                  long long x __attribute__((aligned(16)));
                  long long y;
          };
  } f_a16_tsp;

  int test_2_f_a16_tsp_reg(int i, f_a16_tsp s1, f_a16_tsp s2);
  int test_2_f_a16_tsp_stack(int i, int i2, int i3, int i4, int i5, int i6,
                             int i7, int i8, int i9, f_a16_tsp s1,
                             f_a16_tsp s2);

  typedef struct is_no_align {
          int i;
          short s;
  } is_no_align;

  int test_2_is_no_align_reg(int i, is_no_align s1, is_no_align s2);
  int test_2_is_no_align_stack(int i, int i2, int i3, int i4, int i5, int i6,
                               int i7, int i8, int i9, is_no_align s1,
                               is_no_align s2);

  typedef struct is_a16 {
          int i;
          short s;
  } __attribute__((aligned(16))) is_a16;

  int test_2_is_a16_reg(int i, is_a16 s1, is_a16 s2);
  int test_2_is_a16_stack(int i, int i2, int i3, int i4, int i5, int i6, int i7,
                          int i8, int i9, is_a16 s1, is_a16 s2);

  typedef struct isis_no_align {
          int i;
          short s;
          int i2;
          short s2;
  } isis_no_align;

  int test_2_isis_no_align_reg(int i, isis_no_align s1, isis_no_align s2);
  int test_2_isis_no_align_stack(int i, int i2, int i3, int i4, int i5, int i6,
                                 int i7, int i8, int i9, isis_no_align s1,
                                 isis_no_align s2);

  typedef struct isis_a16
  {
          int i;
          short s;
          int i2;
          short s2;
  } __attribute__((aligned(16))) isis_a16;

  int test_2_isis_a16_reg(int i, isis_a16 s1, isis_a16 s2);
  int test_2_isis_a16_stack(int i, int i2, int i3, int i4, int i5, int i6,
                            int i7, int i8, int i9, isis_a16 s1, isis_a16 s2);

  typedef struct isisis
  {
          int i;
          short s;
          int i2;
          short s2;
          int i3;
          short s3;
  } isisis_no_align;

  int test_2_isisis_no_align_reg(int i, isisis_no_align s1, isisis_no_align s2);
  int test_2_isisis_no_align_stack(int i, int i2, int i3, int i4, int i5,
                                   int i6, int i7, int i8, int i9,
                                   isisis_no_align s1, isisis_no_align s2);

  typedef struct isisis_a16
  {
          int i;
          short s;
          int i2;
          short s2;
          int i3;
          short s3;
  } __attribute__((aligned(16))) isisis_a16;

  int test_2_isisis_a16_reg(int i, isisis_a16 s1, isisis_a16 s2);
  int test_2_isisis_a16_stack(int i, int i2, int i3, int i4, int i5, int i6,
                              int i7, int i8, int i9, isisis_a16 s1,
                              isisis_a16 s2);

  int test_2_isis_no_align_split(int i, int i2, int i3, int i4, int i5, int i6,
                                 int i7, isis_no_align s1, isis_no_align s2);
  int test_2_isis_a16_split(int i, int i2, int i3, int i4, int i5, int i6,
                            int i7, isis_a16 s1, isis_a16 s2);

  typedef struct ill_packed {
          int x;
          long long y;
  } __attribute__((packed)) ill_packed;

  typedef struct ii {
          int x;
          int y;
  } ii;

  int test_2_ill_packed(int i, ill_packed s1, ill_packed s2);
  int test_2_ill_packed_reord(int i, ill_packed s1, ill_packed s2, int i2,
                              ii s3);
  int test_2_ill_packed_stack(int i, int i2, int i3, int i4, int i5, int i6,
                              int i7, int i8, int i9, ill_packed s1,
                              ill_packed s2);

  typedef struct ill_packed_a16 {
          int x;
          long long y;
  } __attribute__((packed, aligned(16))) ill_packed_a16;

  int test_2_ill_packed_a16(int i, ill_packed_a16 s1, ill_packed_a16 s2);
  int test_2_ill_packed_a16_reord(int i, ill_packed_a16 s1, ill_packed_a16 s2,
                                  int i2, ii s3);
  int test_2_ill_packed_a16_stack(int i, int i2, int i3, int i4, int i5, int i6,
                                  int i7, int i8, int i9, ill_packed_a16 s1,
                                  ill_packed_a16 s2);
]]

test:is(ffi_ccall.test_2_align_hfa(0LL,
    {{0, 1, 2, 3}}, {{4, 5, 6, 7}}),
  28, 'correct align hfa')

test:is(ffi_ccall.test_2_intx4_a16(0LL,
    {{0LL, 1LL, 2LL, 3LL}}, {{4LL, 5LL, 6LL, 7LL}}),
  28, 'correct align hva')

local LARGE_HVA_SZ = 18
local large_agg_sum = 0LL
local large_agg1 = {}
local large_agg2 = {}
for i = 0, LARGE_HVA_SZ - 1 do
  large_agg1[i] = i + 0LL
  large_agg2[i] = LARGE_HVA_SZ + i + 0LL
  large_agg_sum = large_agg_sum + large_agg1[i] + large_agg2[i]
end

test:is(ffi_ccall.test_2_large_agg_a16(0LL, {large_agg1}, {large_agg2}),
        large_agg_sum, 'correct large align agg')

test:is(ffi_ccall.test_2_intx3_0bitfield_reg(0LL,
    {x = 1LL, y = 2LL, z = 3LL}, {x = 4LL, y = 5LL, z = 6LL}),
  21, 'correct intx3 0 bitfield reg')

test:is(ffi_ccall.test_2_intx3_0bitfield_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL, z = 12LL},
    {x = 13LL, y = 14LL, z = 15LL}),
  120, 'correct intx3 0 bitfield stack')

test:is(ffi_ccall.test_2_intx3_0bitfield_a16_reg(0LL,
    {x = 1LL, y = 2LL, z = 3LL},
    {x = 4LL, y = 5LL, z = 6LL}),
  21, 'correct intx3 0 bitfield align 16 reg')

test:is(ffi_ccall.test_2_intx3_0bitfield_a16_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL, z = 12LL},
    {x = 13LL, y = 14LL, z = 15LL}),
  120, 'correct intx3 0 bitfield align 16 stack')

test:is(ffi_ccall.test_2_intx3_full_bitfield_a16_reg(
    0LL,
    {x = 1LL, y = 2LL, z = 3LL},
    {x = 4LL, y = 5LL, z = 6LL}),
  21, 'correct intx3 0 full bitfield align 16 reg')

test:is(ffi_ccall.test_2_intx3_full_bitfield_a16_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL, z = 12LL},
    {x = 13LL, y = 14LL, z = 15LL}),
  120, 'correct intx3 full bitfield align 16 stack')

test:is(ffi_ccall.test_2_intx3_half_bitfield_reg(0LL,
    {x = 1LL, y = 2LL, z = 3LL},
    {x = 4LL, y = 5LL, z = 6LL}),
  21, 'correct intx3 0 half bitfield reg')

test:is(ffi_ccall.test_2_intx3_half_bitfield_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL, z = 12LL},
    {x = 13LL, y = 14LL, z = 15LL}),
  120, 'correct intx3 half bitfield stack')

test:is(ffi_ccall.test_2_intx3_half_bitfield_a16_reg(0LL,
    {x = 1LL, y = 2LL, z = 3LL},
    {x = 4LL, y = 5LL, z = 6LL}),
  21, 'correct intx3 0 half bitfield align 16 reg')

test:is(ffi_ccall.test_2_intx3_half_bitfield_a16_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL, z = 12LL},
    {x = 13LL, y = 14LL, z = 15LL}),
  120, 'correct intx3 half bitfield align 16 stack')

test:is(ffi_ccall.test_2_la16l_reg(0LL, {x = 1LL, y = 2LL}, {x = 3LL, y = 4LL}),
        10, 'correct la16l reg')

test:is(ffi_ccall.test_2_la16l_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL}, {x = 12LL, y = 13LL}),
  91, 'correct la16l stack')

test:is(ffi_ccall.test_2_a16_tsp_reg(0LL,
    {x = 1LL, y = 2LL}, {x = 3LL, y = 4LL}),
  10, 'correct tsp reg')

test:is(ffi_ccall.test_2_a16_tsp_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL}, {x = 12LL, y = 13LL}),
  91, 'correct tsp stack')

test:is(ffi_ccall.test_2_f_a16_tsp_reg(0LL,
    {x = 1LL, y = 2LL}, {x = 3LL, y = 4LL}),
  10, 'correct tsp aligned field reg')

test:is(ffi_ccall.test_2_f_a16_tsp_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL}, {x = 12LL, y = 13LL}),
  91, 'correct tsp aligned field stack')

test:is(ffi_ccall.test_2_is_no_align_reg(0LL,
    {i = 1LL, s = 2LL}, {i = 3LL, s = 4LL}),
  10, 'correct is no align reg')

test:is(ffi_ccall.test_2_is_no_align_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {i = 10LL, s = 11LL}, {i = 12LL, s = 13LL}),
  91, 'correct is no align stack')

test:is(ffi_ccall.test_2_is_a16_reg(0LL,
    {i = 1LL, s = 2LL}, {i = 3LL, s = 4LL}),
  10, 'correct is align 16 reg')

test:is(ffi_ccall.test_2_is_a16_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {i = 10LL, s = 11LL}, {i = 12LL, s = 13LL}),
  91, 'correct is align 16 stack')

test:is(ffi_ccall.test_2_isis_no_align_reg(0LL,
    {i = 1LL, s = 2LL, i2 = 3LL, s2 = 4LL},
    {i = 5LL, s = 6LL, i2 = 7LL, s2 = 8LL}),
  36, 'correct isis no align reg')

test:is(ffi_ccall.test_2_isis_no_align_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {i = 10LL, s = 11LL, i2 = 12LL, s2 = 13LL},
    {i = 14LL, s = 15LL, i2 = 16LL, s2 = 17LL}),
  153, 'correct isis no align stack')

test:is(ffi_ccall.test_2_isis_a16_reg(0LL,
    {i = 1LL, s = 2LL, i2 = 3LL, s2 = 4LL},
    {i = 5LL, s = 6LL, i2 = 7LL, s2 = 8LL}),
  36, 'correct isis align 16 reg')

test:is(ffi_ccall.test_2_isis_a16_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {i = 10LL, s = 11LL, i2 = 12LL, s2 = 13LL},
    {i = 14LL, s = 15LL, i2 = 16LL, s2 = 17LL}),
  153, 'correct isis align 16 stack')

test:is(ffi_ccall.test_2_isisis_no_align_reg(0LL,
    {i = 1LL, s = 2LL, i2 = 3LL, s2 = 4LL, i3 = 5LL, s3 = 6LL},
    {i = 7LL, s = 8LL, i2 = 9LL, s2 = 10LL}),
  55, 'correct isisis no align reg')

test:is(ffi_ccall.test_2_isisis_no_align_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {i = 10LL, s = 11LL, i2 = 12LL, s2 = 13LL, i3 = 14LL, s3 = 15LL},
    {i = 16LL, s = 17LL, i2 = 18LL, s2 = 19LL, i3 = 20LL, s3 = 21LL}),
  231, 'correct isisis no align stack')

test:is(ffi_ccall.test_2_isisis_a16_reg(0LL,
    {i = 1LL, s = 2LL, i2 = 3LL, s2 = 4LL, i3 = 5LL, s3 = 6LL},
    {i = 7LL, s = 8LL, i2 = 9LL, s2 = 10LL}),
  55, 'correct isisis align 16 reg')

test:is(ffi_ccall.test_2_isisis_a16_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {i = 10LL, s = 11LL, i2 = 12LL, s2 = 13LL, i3 = 14LL, s3 = 15LL},
    {i = 16LL, s = 17LL, i2 = 18LL, s2 = 19LL, i3 = 20LL, s3 = 21LL}),
  231, 'correct isisis align 16 stack')


test:is(ffi_ccall.test_2_isis_no_align_split(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL,
    {i = 8LL, s = 9LL, i2 = 10LL, s2 = 11LL},
    {i = 12LL, s = 13LL, i2 = 14LL, s2 = 15LL}),
  120, 'correct isis no align split')

test:is(ffi_ccall.test_2_isis_a16_split(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL,
    {i = 8LL, s = 9LL, i2 = 10LL, s2 = 11LL},
    {i = 12LL, s = 13LL, i2 = 14LL, s2 = 15LL}),
  120, 'correct isis a16 split')

test:is(ffi_ccall.test_2_ill_packed(0LL,
    {x = 1LL, y = 2LL}, {x = 3LL, y = 4LL}),
  10, 'correct ill packed')

test:is(ffi_ccall.test_2_ill_packed_reord(0LL,
    {x = 1LL, y = 2LL}, {x = 3LL, y = 4LL},
    5LL, {x = 6LL, y = 7LL}),
  28, 'correct ill packed reord')

test:is(ffi_ccall.test_2_ill_packed_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL}, {x = 12LL, y = 13LL}),
  91, 'correct ill packed stack')

test:is(ffi_ccall.test_2_ill_packed_a16(0LL,
    {x = 1LL, y = 2LL}, {x = 3LL, y = 4LL}),
  10, 'correct ill packed a16')

test:is(ffi_ccall.test_2_ill_packed_a16_reord(0LL,
    {x = 1LL, y = 2LL}, {x = 3LL, y = 4LL},
    5LL, {x = 6LL, y = 7LL}),
  28, 'correct ill packed a16 reord')

test:is(ffi_ccall.test_2_ill_packed_a16_stack(
    1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL,
    {x = 10LL, y = 11LL}, {x = 12LL, y = 13LL}),
  91, 'correct ill packed a16 stack')

test:done(true)
