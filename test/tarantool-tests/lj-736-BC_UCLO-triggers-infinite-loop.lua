local tap = require('tap')
local test = tap.test('lj-736-BC_UCLO-triggers-infinite-loop'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
})

test:plan(1)

-- Test reproduces an issue when BC_UCLO triggers an infinite loop.
-- See details in https://github.com/LuaJIT/LuaJIT/issues/736.
--
-- Listing below demonstrates a problem -
-- the bytecode UCLO on the line 13 makes a loop at 0013-0014:
--
-- - BYTECODE -- bc_uclo.lua:0-20
-- 0001    KPRI     0   0
-- 0002    FNEW     1   0      ; bc_uclo.lua:5
-- 0003    KSHORT   2   1
-- 0004    KSHORT   3   4
-- 0005    KSHORT   4   1
-- 0006    FORI     2 => 0011
-- 0007 => ISNEN    5   0      ; 2
-- 0008    JMP      6 => 0010
-- 0009    UCLO     0 => 0012
-- 0010 => FORL     2 => 0007
-- 0011 => UCLO     0 => 0012
-- 0012 => KPRI     0   0
-- 0013    UCLO     0 => 0012
-- 0014    FNEW     1   1      ; bc_uclo.lua:18
-- 0015    UCLO     0 => 0016
-- 0016 => RET0     0   1

jit.opt.start('hotloop=1')

do
  local uv = 0
  local w = function() return uv end -- luacheck: no unused
  for i = 1, 2 do
    -- Infinite loop is here.
    if i == 2 then
      if i == 2 then
        goto pass
      end
      goto unreachable
    end
  end
end

::unreachable::
-- Lua chunk below is required for reproducing a bug.
do
  local uv = 0 -- luacheck: no unused
  goto unreachable
  local w = function() return uv end -- luacheck: ignore
end

::pass::

test:ok(true, 'BC_UCLO does not trigger an infinite loop')
os.exit(test:check() and 0 or 1)
