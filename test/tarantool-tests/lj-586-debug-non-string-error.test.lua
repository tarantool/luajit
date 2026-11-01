local tap = require('tap')
local utils = require('utils')

local test = tap.test('lj-586-debug-non-string-error')
test:plan(1)

-- XXX: This is quite an exotic test case in that point of view
-- that testing the debug interactive interface always ends with
-- sending commands to another instance via stdin.
-- Since `debug.debug()` captures `io.stdin` and waits at
-- `fgets()` in debug busy loop, we use `utils.exec.luacmd()`
-- function to obtain the interpreter command, run
-- `debug.debug()` with it, send two commands from the
-- `utils.exec.test_data('commands.lua')` file redirecting it to
-- the process stdin, capture its stdout and stderr and test the
-- resulting output against the expected one.
--
-- Debugger prompt.
local ldb = 'lua_debug> '
-- The magic number is passed via MAGIC environment variable.
local magic = 42
local luabin = utils.exec.luacmd(arg)
local stderr = {
  -- XXX: The first debugger prompt printed at the start.
  ldb,
  -- The resulting error yielded by debugger console.
  '(error object is not a string)\n',
  -- XXX: New debugger prompt printed after the `error()` command.
  ldb,
  -- XXX: The last debugger prompt after `print()` command.
  ldb,
}

-- XXX: Since stderr is merged to stdout, debugger prompts and
-- errors are yielded before the magic given to `print()` command
local expected = table.concat(stderr)..magic

local dbg_commands_file = utils.exec.test_data(arg, 'commands.lua')
local command = utils.exec.makecmd_exec(luabin, {
  env = {MAGIC = magic},
  redirect = ('2>&1 <%s'):format(dbg_commands_file),
  args = {'-e', "'debug.debug()'"},
  trace = utils.exec.makecmd_tap_trace(test),
})
local res = command()
test:ok(res == expected, 'handle non-string error in debug.debug()')
test:done(true)
