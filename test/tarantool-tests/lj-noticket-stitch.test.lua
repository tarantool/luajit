local tap = require('tap')

-- Test file to demonstrate unbalanced Lua stack after instruction
-- recording due to throwing an error at recording of a stitched
-- function.

local ffi = require('ffi')
local test = tap.test('lj-noticket-error-stitch-oom-ir-buff'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Disabled on *BSD due to #4819'] = jit.os == 'BSD',
  ['GC64 requried'] = not ffi.abi('gc64'),
})

local jparse = require('utils').jit.parse
local allocinject = require('allocinject')

local IS_DUALNUM = ffi.abi('dualnum')

-- XXX: Avoid other traces compilation due to hotcount collisions
-- for predictable results.
jit.off()
jit.flush()

test:plan(2)

-- We only need the abort reason in the test.
jparse.start('t')

jit.on()
jit.opt.start('hotloop=1', '-loop', '-fold')

allocinject.enable_null_limited_alloc(511)

local math_modf = math.modf
-- luacheck: no unused
local s1, s2, s3
for i = 1, 4 do
  s1 = i + 1
  s2 = i + 2
  s3 = i + 3
  math_modf(42.1)
end

allocinject.disable()

local _, aborted_traces = jparse.finish()

jit.off()

test:ok(true, 'stack is balanced')

-- Tarantool may compile traces on the startup. These traces
-- already exceed the maximum IR amount before the trace in this
-- test is compiled. Hence, there is no need to reallocate the IR
-- buffer, so the check for the IR size is not triggered.
test:skipcond({
  ['Impossible to predict the number of IRs for Tarantool'] = _TARANTOOL,
  -- The amount of IR for traces is different for non x86/x64
  -- arches and DUALNUM mode.
  ['Disabled for non-x86_64 arches'] = jit.arch ~= 'x64' and jit.arch ~= 'x86',
  ['Disabled for DUALNUM mode'] = IS_DUALNUM,
})

assert(aborted_traces and aborted_traces[1], 'aborted trace is persisted')

-- We tried to compile only one trace.
local reason = aborted_traces[1][1].abort_reason

test:like(reason, 'not enough memory',
          'abort reason is correct')

test:done(true)
