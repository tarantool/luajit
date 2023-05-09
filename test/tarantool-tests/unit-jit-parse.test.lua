local tap = require('tap')
local test = tap.test('unit-jit-parse'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Disabled on *BSD due to #4819'] = jit.os == 'BSD',
})

local jparse = require('utils').jit.parse

local expected_irs = {
  -- The different exotic builds may add different IR
  -- instructions, so just check some IR-s existence.
  -- `%d` is a workaround for GC64 | non-GC64 stack slot number.
  'int SLOAD  #%d',
  'int ADD    0001  %+1',
}
local N_TESTS = #expected_irs

jit.opt.start('hotloop=1')

test:plan(N_TESTS)

-- Reset traces.
jit.flush()

jparse.start('i')

-- Loop to compile:
for _ = 1, 3 do end

local traces = jparse.finish()
local loop_trace = traces[1]

for irnum = 1, N_TESTS do
  local ir_pattern = expected_irs[irnum]
  local irref = loop_trace:has_ir(ir_pattern)
  test:ok(irref, 'find IR refernce by pattern: ' .. ir_pattern)
end

os.exit(test:check() and 0 or 1)
