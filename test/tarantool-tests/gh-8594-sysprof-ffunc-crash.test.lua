local tap = require('tap')
local test = tap.test('gh-8594-sysprof-ffunc-crash'):skipcond({
  ['Sysprof is implemented for x86_64 only'] = jit.arch ~= 'x86' and
                                               jit.arch ~= 'x64',
  ['Sysprof is implemented for Linux only'] = jit.os ~= 'Linux',
  -- luacheck: no global
  ['Prevent hanging Tarantool CI due to #9387'] = _TARANTOOL,
})

test:plan(1)

jit.off()
-- XXX: Run JIT tuning functions in a safe frame to avoid errors
-- thrown when LuaJIT is compiled with JIT engine disabled.
pcall(jit.flush)

local TMP_BINFILE = '/dev/null'

-- XXX: The best way to test the issue is to set the profile
-- interval to be as short as possible. However, our CI is
-- not capable of handling such intense testing, so it was a
-- forced decision to reduce the sampling frequency for it. As a
-- result, it is now less likely to reproduce the issue
-- statistically, but the test case is still valid.

-- GitHub always sets[1] the `CI` environment variable to `true`
-- for every step in a workflow.
-- [1]: https://docs.github.com/en/actions/learn-github-actions/variables#default-environment-variables
local CI = os.getenv('CI') == 'true'

-- Profile interval and number of iterations for CI are
-- empirical. Non-CI profile interval is set to be as short
-- as possible, so the issue is more likely to reproduce.
-- Non-CI number of iterations is greater for the same reason.
local PROFILE_INTERVAL = CI and 3 or 1
local N_ITERATIONS = CI and 1e5 or 1e6

local res, err = misc.sysprof.start{
  mode = 'C',
  interval = PROFILE_INTERVAL,
  path = TMP_BINFILE,
}
assert(res, err)

for i = 1, N_ITERATIONS do
  -- XXX: `tostring` is FFUNC.
  tostring(i)
end

res, err = misc.sysprof.stop()
assert(res, err)

test:ok(true, 'FFUNC frames were streamed correctly')

os.exit(test:check() and 0 or 1)
