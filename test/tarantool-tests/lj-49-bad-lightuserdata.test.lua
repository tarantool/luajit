local tap = require('tap')

local test = tap.test('lj-49-bad-lightuserdata')
test:plan(2)

local testlightuserdata = require('testlightuserdata')

test:ok(testlightuserdata.crafted_ptr())
test:ok(testlightuserdata.mmaped_ptr())

os.exit(test:check() and 0 or 1)
