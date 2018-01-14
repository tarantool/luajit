local tap = require('tap')

local test = tap.test('lj-375-ir-bufput-signed-char')
test:plan(3)

-- Avoid store forwarding optimization to store exactly 1 char.
jit.opt.start(3, '-fwd', 'hotloop=1')
for _ = 1, 3 do
  -- Check optimization for single char storing works correct
  -- for -1. Fast function `string.char()` is recorded with
  -- IR_BUFHDR and IR_BUFPUT IRs in case, when there are more than
  -- 1 arguments.
  local s = string.char(0xff, 0)
  test:ok(s:byte(1) == 0xff, 'correct -1 signed char assembling')
end

os.exit(test:check() and 0 or 1)
