local tap = require('tap')
local test = tap.test('gh-6098-fix-side-exit-patching-on-arm64')
test:plan(1)

-- The function to be tested for side exit patching:
-- * At the beginning of the test case, the <if> branch is
--   recorded as a root trace.
-- * After <refuncs> (and some other hotspots) are recorded, the
--   <else> branch is recorded as a side trace.
-- When JIT is linking the side trace to the corresponding side
-- exit, it patches the jump targets.
local function cbool(cond)
  if cond then
    return 1
  else
    return 0
  end
end

-- XXX: Function template below produces 8Kb mcode for ARM64, so
-- we need to compile at least 128 traces to exceed 1Mb delta
-- between <cbool> root trace side exit and <cbool> side trace.
-- Unfortunately, we have no other option for extending this jump
-- delta, since the base of the current mcode area (J->mcarea) is
-- used as a hint for mcode allocator (see lj_mcode.c for info).
local FUNCS = 128
local recfuncs = { }
for i = 1, FUNCS do
  -- This is a quite heavy workload (though it doesn't look like
  -- one at first). Each load from a table is type guarded. Each
  -- table lookup (for both stores and loads) is guarded for table
  -- <hmask> value and metatable presence. The code below results
  -- to 8Kb of mcode for ARM64 in practice.
  recfuncs[i] = assert(load(([[
    return function(src)
      local p = %d
      local tmp = { }
      local dst = { }
      for i = 1, 3 do
        tmp.a = src.a * p   tmp.j = src.j * p   tmp.s = src.s * p
        tmp.b = src.b * p   tmp.k = src.k * p   tmp.t = src.t * p
        tmp.c = src.c * p   tmp.l = src.l * p   tmp.u = src.u * p
        tmp.d = src.d * p   tmp.m = src.m * p   tmp.v = src.v * p
        tmp.e = src.e * p   tmp.n = src.n * p   tmp.w = src.w * p
        tmp.f = src.f * p   tmp.o = src.o * p   tmp.x = src.x * p
        tmp.g = src.g * p   tmp.p = src.p * p   tmp.y = src.y * p
        tmp.h = src.h * p   tmp.q = src.q * p   tmp.z = src.z * p
        tmp.i = src.i * p   tmp.r = src.r * p

        dst.a = tmp.z + p   dst.j = tmp.q + p   dst.s = tmp.h + p
        dst.b = tmp.y + p   dst.k = tmp.p + p   dst.t = tmp.g + p
        dst.c = tmp.x + p   dst.l = tmp.o + p   dst.u = tmp.f + p
        dst.d = tmp.w + p   dst.m = tmp.n + p   dst.v = tmp.e + p
        dst.e = tmp.v + p   dst.n = tmp.m + p   dst.w = tmp.d + p
        dst.f = tmp.u + p   dst.o = tmp.l + p   dst.x = tmp.c + p
        dst.g = tmp.t + p   dst.p = tmp.k + p   dst.y = tmp.b + p
        dst.h = tmp.s + p   dst.q = tmp.j + p   dst.z = tmp.a + p
        dst.i = tmp.r + p   dst.r = tmp.i + p
      end
      dst.tmp = tmp
      return dst
    end
  ]]):format(i)), ('Syntax error in function recfuncs[%d]'):format(i))()
end

-- Make compiler work hard:
-- * No optimizations at all to produce more mcode.
-- * Try to compile all compiled paths as early as JIT can.
-- * Allow to compile 2Mb of mcode to be sure the issue occurs.
jit.opt.start(0, 'hotloop=1', 'hotexit=1', 'maxmcode=2048')

-- First call makes <cbool> hot enough to be recorded next time.
cbool(true)
-- Second call records <cbool> body (i.e. <if> branch). This is
-- a root trace for <cbool>.
cbool(true)

for i = 1, FUNCS do
  -- XXX: FNEW is NYI, hence loop recording fails at this point.
  -- The recording is aborted on purpose: we are going to record
  -- <FUNCS> number of traces for functions in <recfuncs>.
  -- Otherwise, loop recording might lead to a very long trace
  -- error (via return to a lower frame), or a trace with lots of
  -- side traces. We need neither of this, but just bunch of
  -- traces filling the available mcode area.
  local function tnew(p)
    return {
      a = p + 1, f = p + 6,  k = p + 11, p = p + 16, u = p + 21, z = p + 26,
      b = p + 2, g = p + 7,  l = p + 12, q = p + 17, v = p + 22,
      c = p + 3, h = p + 8,  m = p + 13, r = p + 18, w = p + 23,
      d = p + 4, i = p + 9,  n = p + 14, s = p + 19, x = p + 24,
      e = p + 5, j = p + 10, o = p + 15, t = p + 20, y = p + 25,
    }
  end
  -- Each function call produces a trace (see the template for the
  -- function definition above).
  recfuncs[i](tnew(i))
end

-- XXX: I tried to make the test in pure Lua, but I failed to
-- implement the robust solution. As a result I've implemented a
-- tiny Lua C API module to route the flow through C frames and
-- make JIT work the way I need to reproduce the fail. See the
-- usage below.
-- <pxcall> is just a wrapper for <lua_call> with "multiargs" and
-- "multiret" with the same signature as <pcall>.
local pxcall = require('libproxy').proxycall

-- XXX: Here is the dessert: JIT is aimed to work better for
-- highly biased code. It means, the root trace should be the
-- most popular flow. Furthermore, JIT also considers the fact,
-- that frequently taken side exits are *also* popular, and
-- compiles the side traces for such popular exits. However,
-- to recoup his attempts JIT try to compile the flow as far
-- as it can (see <lj_record_ret> in lj_record.c for more info).
--
-- Such "kind" behaviour occurs in our case: if one calls <cbool>
-- the native way, JIT continues recording in a lower frame after
-- returning from <cbool>. As a result, the second call is also
-- recorded, but it has to trigger the far jump to the side trace.
-- However, if the lower frame is not the Lua one, JIT doesn't
-- proceed the further flow recording and assembles the trace. In
-- this case, the second call jumps to <cbool> root trace, hits
-- the assertion guard and jumps to <cbool> side trace.
pxcall(cbool, false)
cbool(false)

test:ok(true)
os.exit(test:check() and 0 or 1)
