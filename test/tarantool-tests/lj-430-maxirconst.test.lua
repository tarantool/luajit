-- XXX: avoid any other traces compilation due to hotcount
-- collisions for predictable results.
jit.off()
jit.flush()

-- Disabled on *BSD due to #4819.
require('utils').skipcond(jit.os == 'BSD', 'Disabled due to #4819')

local tap = require('tap')
local traceinfo = require('jit.util').traceinfo

local test = tap.test('lj-430-maxirconst')
test:plan(2)

-- XXX: trace always has at least 3 IR constants: for nil, false
-- and true.
jit.opt.start('hotloop=1', 'maxirconst=3')

-- This function has only 3 IR constant.
local function irconst3()
end

-- This function has 4 IR constants before optimizations.
local function irconst4()
  local _ = 42
end

assert(not traceinfo(1), 'no traces compiled after flush')
jit.on()
irconst3()
irconst3()
jit.off()
test:ok(traceinfo(1), 'new trace created')

jit.on()
irconst4()
irconst4()
jit.off()
test:ok(not traceinfo(2), 'trace should not appear due to maxirconst limit')

os.exit(test:check() and 0 or 1)
