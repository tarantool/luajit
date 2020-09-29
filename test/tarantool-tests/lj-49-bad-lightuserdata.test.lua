local tap = require('tap')

local test = tap.test('lj-49-bad-lightuserdata')
test:plan(1)

local testlightuserdata = require('testlightuserdata')

test:ok(testlightuserdata.longptr())

os.exit(test:check() and 0 or 1)
