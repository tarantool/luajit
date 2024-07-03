local tap = require('tap')

-- The test file demonstrates `string.format()`
-- heap-buffer-overflow under ASAN if the atomic phase of the GC
-- is entered during the first pass of formatting with implicit
-- conversion of the argument to a string via %s.
-- See also: https://github.com/tarantool/tarantool/issues/4171.
local test = tap.test('gh-4171-lj-cf-string-format-atomic')

test:plan(1)

local obj = setmetatable({}, {
  __tostring = function()
    -- Shrinks `tmpbuf`: 256 -> 128 (but length of string is 200).
    collectgarbage()
    return 'x'
  end
})

local prefix = string.rep('a', 200)

-- %s triggers a full GC cycle, including `tmpbuf` shrinking in
-- the atomic phase. '_suffix' was written outside the buffer
-- before the patch.
local res = string.format(prefix .. '%s_suffix', obj)

-- Under ASAN this leads to heap-buffer-overflow.
test:is(res, prefix .. 'x_suffix', 'correct string format result')

test:done(true)
