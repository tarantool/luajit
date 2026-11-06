local tap = require('tap')

-- The sysprof fast-function prologue on x86 reads the function
-- object from `[BASE - 4]`, but this slot stores the saved PC. As a
-- result, `LFUNC:ecx->ffid` is dereferenced through an invalid
-- pointer and trace stitching around `tonumber()` crashes instead
-- of returning nil. Use `[BASE - 8]` instead, as the x64 branch
-- already does.
local test = tap.test('sysprof-ffunc-x86-crash'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Sysprof is implemented for Linux only'] = jit.os ~= 'Linux',
  ['The bug is specific to 32-bit x86'] = jit.arch ~= 'x86',
  ['Sysprof is disabled'] = os.getenv('LUAJIT_DISABLE_SYSPROF'),
})

test:plan(1)

jit.opt.start('hotloop=1', 'hotexit=1')

local y
for _ = 1, 100 do
  y = tonumber('not a number')
end

test:is(y, nil, 'tonumber() with a non-number string')

test:done(true)
