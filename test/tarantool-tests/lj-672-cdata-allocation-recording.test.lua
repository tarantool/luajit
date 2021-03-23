-- Disabled on *BSD due to #4819.
require('utils').skipcond(jit.os == 'BSD', 'Disabled due to #4819')

local ffi = require('ffi')
local traceinfo = require('jit.util').traceinfo

local tap = require('tap')
local test = tap.test('lj-672-cdata-allocation-recording')
test:plan(1)

-- Structure with array.
ffi.cdef('struct my_struct {int a; char d[8];}')

-- Be sure that we have no other traces.
jit.off()
jit.flush()
jit.on()

jit.opt.start("hotloop=1")
-- Hoist variable declaration to avoid allocation sinking for the
-- trace below.
local r
for i = 1, 3 do
  r = ffi.new('struct my_struct')
  r.a = i
end

test:ok(traceinfo(1), 'new trace created')

os.exit(test:check() and 0 or 1)
