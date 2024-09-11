local tap = require('tap')

local test = tap.test('lj-726-profile-flush-close'):skipcond({
  ['Disabled with Valgrind (SIGPROF)'] = os.getenv("LJ_USE_VALGRIND") == 'ON',
})
test:plan(1)

local TEST_FILE = 'lj-726-profile-flush-close.profile'

local function payload()
  local r = 0
  for i = 1, 1e8 do
    r = r + i
  end
  return r
end

local p = require('jit.p')
p.start('f', TEST_FILE)
payload()
p.stop()

local f, err = io.open(TEST_FILE)
assert(f, err)

-- Check that file is not empty.
test:ok(f:read(0), 'profile output was flushed and closed')

assert(os.remove(TEST_FILE))

test:done(true)
