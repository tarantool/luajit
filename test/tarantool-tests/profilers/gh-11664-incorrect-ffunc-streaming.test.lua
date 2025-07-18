local tap = require('tap')

local test = tap.test('gh-11664-incorrect-ffunc-streaming')

test:plan(1)

local f = function()
  while next({1}) do
    -- Nope.
  end
end

misc.sysprof.start({mode = 'C', path = '/dev/null', interval = 1})
f()
misc.sysprof.stop()

test:ok(true, 'incorrect FFUNC streaming')
test:done(true)
