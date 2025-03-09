local tap = require('tap')
local test = tap.test('lj-noticket-fix-cli-posix-sigint-handling'):skipcond({
  ['Check LuaJIT CLI signal handling'] = _TARANTOOL,
  ['Disabled on POSIX nonconformant OS'] = jit.os ~= 'BSD' and
                                           jit.os ~= 'Linux' and
                                           jit.os ~= 'OSX' and
                                           jit.os ~= 'POSIX',
})

test:plan(1)
local utils = require('utils')
local script = utils.exec.makecmd_bash(arg, {t = test})
local output = script(
  utils.exec.luabin(arg),
  utils.exec.test_data(arg, 'script.lua'))
test:is(output, 'OK')
test:done(true)
