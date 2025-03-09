local tap = require('tap')

-- The test file to demonstrate LuaJIT's missing coercion for the
-- `io.fseek()` offset argument.
-- See also: https://github.com/LuaJIT/LuaJIT/issues/1343.

local test = tap.test('lj-1343-fseek-offset-coercion')

test:plan(2)

local f = io.tmpfile()

f:write('12345')

f:seek('set', 0)
f:seek('set', '1')
test:is(f:read('*all'), '2345', 'base coercion test')

f:seek('set', 0)
f:seek('set', '1.9')
test:is(f:read('*all'), '2345', 'coercion test for non-integer value')

test:done(true)
