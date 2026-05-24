local ffi = require('ffi')
local tap = require('tap')

-- The test file to check FFI vector passing correctness.
local test = tap.test('ffi-vector-arguments'):skipcond({
  ['NYI for non-x64 arches'] = jit.arch ~= 'x64',
})

local SIZING
-- Only those are implemented.
if jit.arch == 'x64' then
  SIZING = {2, 4}
else
  SIZING = {}
end

test:plan(#SIZING + 1)

local ffi_ccall = ffi.load('libfficcall')

ffi.cdef[[
  typedef float vfloatx2  __attribute__ ((__vector_size__ (8)));
  typedef float vfloatx4  __attribute__ ((__vector_size__ (16)));

  vfloatx2  vfloatx2_call(vfloatx2 x);
  vfloatx4  vfloatx4_call(vfloatx4 x);

  typedef int int32x4_t __attribute__((__vector_size__ (4 * 4)));
  int32x4_t test_hva_varg(int n, ...);
]]

local function test_self_ret_vector(subtest, nelem)
  subtest:plan(1)
  local typestr = 'vfloatx' .. nelem
  local f = ffi_ccall[typestr .. '_call']
  local arg = {}
  for i = 1, nelem do
    arg[i - 1] = i + 0LL
  end
  local res = f(arg)
  local table_res = {}
  for i = 0, nelem - 1 do
    table_res[i] = res[i]
  end
  subtest:is_deeply(table_res, arg,
                    'correct result for ' .. nelem .. '-sized vec')
end

for i = 1, #SIZING do
  test:test('vec-' .. SIZING[i], test_self_ret_vector, SIZING[i])
end

local hva_arg_vec = ffi.new('int32x4_t', {0LL, 1LL, 2LL, 3LL})
local hva_res = ffi_ccall.test_hva_varg(0LL, hva_arg_vec, hva_arg_vec)
local hva_res_tab = {}
local hva_expected = {[0] = 0, 2, 4, 6}
for i = 0, 3 do
  hva_res_tab[i] = hva_res[i]
end
test:is_deeply(hva_res_tab, hva_expected, 'correct hva with the int type')

test:done(true)
