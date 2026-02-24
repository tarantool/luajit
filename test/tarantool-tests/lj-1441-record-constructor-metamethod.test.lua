local tap = require('tap')

-- The test file to demonstrate LuaJIT's incorrect recording of
-- the __index metamethod invocation on the cdata's constructor.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1441.

local test = tap.test('lj-1441-record-constructor-metamethod'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(3)

local ffi = require('ffi')

ffi.cdef[[
  struct test_recursive {int a;};
  struct test_finite {int a;};
]]

local recursive_t = ffi.typeof('struct test_recursive')
local finite_t = ffi.typeof('struct test_finite')

local MAGIC = 42

local function new_recursive()
  return ffi.new(recursive_t, 0)
end

local function new_finite()
  return ffi.new(finite_t, 0)
end

local function index_func_recursive(v)
  -- Should raise an error (stack overflow).
  return ffi.typeof(v).a
end

-- Special object to invoke metamethod on the cdata<ctypeid>.
local one_more_step = new_finite()

local function index_func_finite(v)
  if v == one_more_step then
    -- XXX: Avoid tail-calls.
    local x = ffi.typeof(v).a
    return x
  else
    return MAGIC
  end
end

ffi.metatype(recursive_t, {
  __index = index_func_recursive,
})

ffi.metatype(finite_t, {
  __index = index_func_finite,
})

jit.opt.start('hotloop=1')

-- Test the recursive call. Expect the stack overflow error.
local o_rec = new_recursive()
local result, errmsg
for _ = 1, 4 do
  result, errmsg = pcall(index_func_recursive, o_rec)
end

test:ok(not result, 'correct status for recursive call')
test:like(errmsg, 'stack overflow', 'correct error message for recursive call')

-- Test the finite call. Expect the specific value.
local got
for _ = 1, 4 do
  got = index_func_finite(one_more_step)
end

test:is(got, MAGIC, 'correct result value on trace for finite call')

test:done(true)
