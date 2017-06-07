local tap = require('tap')
local test = tap.test('fix-mips64-spare-side-exit-patching'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Disabled on *BSD due to #4819'] = jit.os == 'BSD',
  -- We need to fix the MIPS behaviour first.
  ['Disabled for MIPS architectures'] = jit.arch:match('mips'),
})

local generators = require('utils').jit.generators
local frontend = require('utils').frontend

test:plan(1)

-- Make compiler work hard.
jit.opt.start(
  -- No optimizations at all to produce more mcode.
  0,
  -- Try to compile all compiled paths as early as JIT can.
  'hotloop=1',
  'hotexit=1',
  -- Allow compilation of up to 2000 traces to avoid flushes.
  'maxtrace=2000',
  -- Allow to compile 8Mb of mcode to be sure the issue occurs.
  'maxmcode=8192',
  -- Use big mcode area for traces to avoid usage of different
  -- spare slots.
  'sizemcode=256'
)

-- See the define in the <src/lj_asm_mips.h>.
local MAX_SPARE_SLOT = 4
local function parent(marker)
  -- Use several side exits to fill spare exit space (default is
  -- 4 slots, each slot has 2 instructions -- jump and nop).
  -- luacheck: ignore
  if marker > MAX_SPARE_SLOT then end
  if marker > 3 then end
  if marker > 2 then end
  if marker > 1 then end
  if marker > 0 then end
  -- XXX: use `fmod()` to avoid leaving the function and use
  -- stitching here.
  return math.fmod(1, 1)
end

-- Compile parent trace first.
parent(0)
parent(0)

local parent_traceno = frontend.gettraceno(parent)
local last_traceno = parent_traceno

-- Now generate some mcode to forcify long jump with a spare slot.
-- Each iteration provides different addresses and uses a
-- different spare slot. After that, compiles and executes a new
-- side trace.
for i = 1, MAX_SPARE_SLOT + 1 do
  generators.fillmcode(last_traceno, 1024 * 1024)
  parent(i)
  parent(i)
  parent(i)
  last_traceno = misc.getmetrics().jit_trace_num
end

test:ok(true, 'all traces executed correctly')

test:done(true)
