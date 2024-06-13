local tap = require('tap')
local test = tap.test('asan-left-memory-miss')
test:plan(1)

local script = require('utils').exec.makecmd(arg, { redirect = '2>&1' })
local output, status = script()

test:ok(status == 1, output)
test:done(true)