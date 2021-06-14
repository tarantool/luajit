local tap = require('tap')
local test = tap.test('lj-720-errors-before-stitch'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})
test:plan(1)

-- `math.modf` recording is NYI.
-- Local `modf` simplifies `jit.dump()` output.
local modf = math.modf
jit.opt.start('hotloop=1', 'maxsnap=1')

-- The loop has only two iterations: the first to detect its
-- hotness and the second to record it. The snapshot limit is
-- set to one and is certainly reached.
for _ = 1, 2 do
  -- Forcify stitch.
  modf(1.2)
end

test:ok(true, 'stack is balanced')
test:done(true)
