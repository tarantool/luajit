local tap = require('tap')

-- Test file to demonstrate fd leakage in case of OOM during the
-- `loadfile()` call. The test fails before the patch when run
-- under Valgrind with the `--track-fds=yes` option.
-- See also, https://github.com/LuaJIT/LuaJIT/issues/1249.
local test = tap.test('lj-1249-loadfile-fd-leak')

test:plan(2)

local allocinject = require('allocinject')

allocinject.enable_null_alloc()

-- Just use the /dev/null as the surely available file.
-- OOM is due to the creation of the string "@/dev/null" as the
-- filename to be stored.
local res, errmsg = pcall(loadfile, '/dev/null')

allocinject.disable()

-- Sanity checks.
test:ok(not res, 'correct status, OOM on filename creation')
test:like(errmsg, 'not enough memory',
          'correct error message, OOM on filename creation')

test:done(true)
