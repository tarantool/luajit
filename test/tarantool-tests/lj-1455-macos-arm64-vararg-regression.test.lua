local ffi = require('ffi')
local tap = require('tap')

-- The test file to test various FFI C vararg calls.
-- luacheck: push no max_comment_line_length
-- Originated from: https://github.com/neovim/neovim/blob/a5aa62e37b82214a1d4d1e0a54d193b155fb340c/test/unit/strings_spec.lua
-- luacheck: pop
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1455.

local test = tap.test('lj-1455-macos-arm64-vararg-regression')

test:plan(45)

ffi.cdef('int sprintf(char *str, const char *format, ...);')

local buf = ffi.new('char[64]')

local function t(expected, fmt, ...)
  local args = {...}
  local ctx = string.format('sprintf(buf, "%s"', fmt)
  for _, x in ipairs(args) do
    ctx = ctx .. ', ' .. tostring(x)
  end
  ctx = ctx .. string.format(') = %s', expected)

  test:test(ctx, function(subtest, ...)
    subtest:plan(2)
    subtest:is(ffi.C.sprintf(buf, fmt, ...), #expected,
               ctx .. ' - return status')
    subtest:is(ffi.string(buf), expected, ctx .. ' - result string')
  end, ...)
end

local function i(n)
  return ffi.cast('int', n)
end

local function l(n)
  return ffi.cast('long', n)
end

local function ll(n)
  return ffi.cast('long long', n)
end

local function z(n)
  return ffi.cast('ptrdiff_t', n)
end

local function u(n)
  return ffi.cast('unsigned', n)
end

local function ul(n)
  return ffi.cast('unsigned long', n)
end

local function ull(n)
  return ffi.cast('unsigned long long', n)
end

local function uz(n)
  return ffi.cast('size_t', n)
end

t('1234567', '%d', i(1234567))
t('1234567', '%ld', l(1234567))
t('  1234567', '%9ld', l(1234567))
t('1234567  ', '%-9ld', l(1234567))
t('deadbeef', '%x', u(0xdeadbeef))
t('one two', '%s %s', 'one', 'two')
t('1.234000', '%f', 1.234)
t('1.234000e+00', '%e', 1.234)
t('inf', '%f', 1.0 / 0.0)
t('-inf', '%f', -1.0 / 0.0)
t('-0.000000', '%f', tonumber('-0.0'))
t('%%%', '%%%%%%')
t('0x87654321', '%p', ffi.cast('char *', 0x87654321))
t('0x0087654321', '%012p', ffi.cast('char *', 0x87654321))
t('1234567  ', '%1$*2$ld', l(1234567), i(-9))
t('1234567  ', '%1$*2$.*3$ld', l(1234567), i(-9), i(5))
t('1234567  ', '%1$*3$.*2$ld', l(1234567), i(5), i(-9))
t('1234567  ', '%3$*1$.*2$ld', i(-9), i(5), l(1234567))
t('1234567', '%1$ld', l(1234567))
t('  1234567', '%1$*2$ld', l(1234567), i(9))
t('9 12345 7654321', '%2$ld %1$d %3$lu', i(12345), l(9), ul(7654321))
t('9 1234567 7654321', '%2$d %1$ld %3$lu', l(1234567), i(9), ul(7654321))
t('9 1234567 7654321', '%2$d %1$lld %3$lu', ll(1234567), i(9), ul(7654321))
t('9 12345 7654321', '%2$ld %1$u %3$lu', u(12345), l(9), ul(7654321))
t('9 1234567 7654321', '%2$d %1$lu %3$lu', ul(1234567), i(9), ul(7654321))
t('9 1234567 7654321', '%2$d %1$llu %3$lu', ull(1234567), i(9), ul(7654321))
t('9 deadbeef 7654321', '%2$d %1$x %3$lu', u(0xdeadbeef), i(9), ul(7654321))
t('9 c 7654321', '%2$ld %1$c %3$lu', i(('c'):byte()), l(9), ul(7654321))
t('9 hi 7654321', '%2$ld %1$s %3$lu', 'hi', l(9), ul(7654321))
t('9 0.000000e+00 7654321', '%2$ld %1$e %3$lu', 0.0, l(9), ul(7654321))
t('two one two', '%2$s %1$s %2$s', 'one', 'two', 'three')
t('three one two', '%3$s %1$s %2$s', 'one', 'two', 'three')
t('1234567', '%1$d', i(1234567))
t('deadbeef', '%1$x', u(0xdeadbeef))
t('one two', '%1$s %2$s', 'one', 'two')
t('two one', '%2$s %1$s', 'one', 'two')
t('1.234000', '%1$f', 1.234)
t('1.234000e+00', '%1$e', 1.234)
t('inf', '%1$f', 1.0 / 0.0)
t('-inf', '%1$f', -1.0 / 0.0)
t('-0.000000', '%1$f', tonumber('-0.0'))
t('-1234567 -7654321', '%zd %zd', z(-1234567), z(-7654321))
t('-7654321 -1234567', '%2$zd %1$zd', z(-1234567), z(-7654321))
t('1234567 7654321', '%zu %zu', uz(1234567), uz(7654321))
t('7654321 1234567', '%2$zu %1$zu', uz(1234567), uz(7654321))

test:done(true)
