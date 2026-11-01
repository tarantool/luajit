local tap = require('tap')
-- The test reproduces the problem only for GC64 mode with enabled
-- JIT.
local test = tap.test('lj-962-stack-overflow-report')
test:plan(1)

local utils = require('utils')
local script = utils.exec.makecmd(arg, {redirect = '2>&1'})
local output = script()
test:like(output, 'stack overflow', 'stack overflow reported correctly')
test:done(true)
