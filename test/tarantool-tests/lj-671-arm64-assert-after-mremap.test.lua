local tap = require('tap')

-- Test file to demonstrate assertion after `mremap()` on arm64.
-- See also, https://github.com/LuaJIT/LuaJIT/issues/671.

local test = tap.test('lj-671-arm64-assert-after-mremap')
test:plan(1)

-- `mremap()` is used on Linux for remap directly mapped big
-- (>=DEFAULT_MMAP_THRESHOLD) memory chunks.
-- The simplest way to test memory move is to allocate the huge
-- memory chunk for string buffer directly and reallocate it
-- after.
-- To allocate buffer exactly to threshold limit for direct chunk
-- mapping use `string.rep()` with length equals threshold.
-- Then concatenate result string (with length of
-- DEFAULT_MMAP_THRESHOLD) with the other one to reallocate
-- and remap string buffer.

local DEFAULT_MMAP_THRESHOLD = 128 * 1024
local s = string.rep('x', DEFAULT_MMAP_THRESHOLD)..'x'
test:ok(s)

os.exit(test:check() and 0 or 1)
