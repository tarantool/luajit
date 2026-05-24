local ffi = require('ffi')
local tap = require('tap')

-- The test file to check FFI correctness for the empty structs.
local test = tap.test('ffi-call-empty-struct')

test:plan(6)

local ffi_ccall = ffi.load('libfficcall')

ffi.cdef[[
  struct empty {};
  struct super_empty {int arg[0];};
  struct sort_of_empty {struct super_empty;};

  struct empty empty_ret(void);
  struct super_empty super_empty_ret(void);
  struct sort_of_empty sort_of_empty_ret(void);

  int super_empty_arg(struct super_empty e, int a);
  int sort_of_empty_arg(struct sort_of_empty e, int a);
  int empty_arg(struct empty e, int a);
]]

local MAGIC = 42LL

local empty_t = ffi.typeof('struct empty')
local super_empty_t = ffi.typeof('struct super_empty')
local sort_of_empty_t = ffi.typeof('struct sort_of_empty')

test:is(ffi.typeof(ffi_ccall.empty_ret()), empty_t, 'correct empty ret type')
test:is(ffi.typeof(ffi_ccall.super_empty_ret()), super_empty_t,
        'correct super_empty ret type')
test:is(ffi.typeof(ffi_ccall.sort_of_empty_ret()), sort_of_empty_t,
        'correct sort_of_empty ret type')

local empty_o = empty_t()
local super_empty_o = super_empty_t()
local sort_of_empty_o = sort_of_empty_t()

test:is(ffi_ccall.empty_arg(empty_o, MAGIC), MAGIC, 'correct empty arg handle')
test:is(ffi_ccall.super_empty_arg(super_empty_o, MAGIC), MAGIC,
        'correct super_empty arg handle')
test:is(ffi_ccall.sort_of_empty_arg(sort_of_empty_o, MAGIC), MAGIC,
        'correct sort_of_empty arg handle')

test:done(true)
