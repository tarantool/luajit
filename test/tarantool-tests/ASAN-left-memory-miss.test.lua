local tap = require('tap')
local asan_hardening = os.getenv("LJ_ASAN_HARDENING")
local test = tap.test('asan-left-memory-miss'):skipcond({
  ['Test requires ASAN-HARDENING enabled'] = asan_hardening == 'OFF',
})
test:plan(1)

local script = require('utils').exec.makecmd(arg, { redirect = '2>&1' })
local output, status = script()

test:ok(status == 1, output)
test:done(true)