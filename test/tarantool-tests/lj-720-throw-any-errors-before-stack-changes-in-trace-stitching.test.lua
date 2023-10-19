local tap = require('tap')

local test = tap.test('lj-720-throw-any-errors-before-stack-changes-in-trace-stitching'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})
test:plan(1)

jit.opt.start('hotloop=2', 'hotexit=1', 'maxsnap=8')

local function a(b)
  if b >= 2 then  -- luacheck: ignore
    -- Empty.
  end
end

a(1)
a(1)
a(1)
a(1)

local function bar()
  for c = 2, 3 do
    a(c)
  end
  d = 0 -- luacheck: ignore

  -- NYI
  print()
end

bar()

test:ok(true, 'throw-any-errors-before-stack-changes-in-trace-stitching')

test:done(true)
