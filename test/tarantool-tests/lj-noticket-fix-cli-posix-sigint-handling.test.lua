local tap = require('tap')

-- The test checks that LuaJIT CLI stop hook is executed on
-- SIGINT on a blocking system call (read(), waitpid(), etc.).
--
-- The test runs LuaJIT CLI with a script, which prints its PID
-- as a ready marker and blocks on a read() call. After the
-- the child's PID number is read from child's pipe, the test
-- sends SIGINT to the child.
-- With a patch applied (no SA_RESTART flag for SIGINT handler)
-- read() call is interrupted and the CLI's Lua stop hook
-- is executed.
-- Without a patch (SA_RESTART flag is present for SIGINT
-- handler) read() call is restarted, the test and the child are
-- blocked on a pipe read until the child is terminated by
-- SIGALRM. The test reads nothing from the child and fails.

local test = tap.test('lj-noticket-fix-cli-posix-sigint-handling'):skipcond({
  -- The patched code is not present in Tarantool binary:
  ["Disabled due to Tarantool uses it's own signal handling"] = _TARANTOOL,
  ['Disabled on POSIX nonconformant OS'] = jit.os ~= 'BSD' and
                                           jit.os ~= 'Linux' and
                                           jit.os ~= 'OSX' and
                                           jit.os ~= 'POSIX',
})

local ffi = require('ffi')
ffi.cdef[[
  int kill(int pid, int sig);
]]
local SIGINT = 2

test:plan(1)
local utils = require('utils')
local script = utils.exec.test_data(arg, 'script.lua')
local cmd = ('exec %s %s 2>&1'):format(utils.exec.luacmd(arg), script)
local proc = io.popen(cmd)

local MARKER = 'CHILD_PID:'
local RMARKER = '^' .. MARKER .. '(%d+)$'
-- The child prints its PID after the CLI has installed the SIGINT
-- handler, so it is a readiness marker. Skip possible noise
-- lines, collect pre-marker output for error reporting.
local lines_for_diag = {'child output:'}
local pid, line
repeat
  line = proc:read('*l')
  if line ~= nil then
    table.insert(lines_for_diag, line)
    local match = line:match(RMARKER)
    if match ~= nil then pid = tonumber(match) end
  end
until line == nil or pid ~= nil
if pid == nil then
  test:diag(table.concat(lines_for_diag, '\n'))
end
assert(pid ~= nil, 'the child process must report its PID')

local res = ffi.C.kill(pid, SIGINT)
assert(res == 0, 'SIGINT delivery failed')
local output = proc:read('*a')
proc:close()
test:diag(output)
test:like(output, 'interrupted!', 'SIGINT interrupts the blocking call')
test:done(true)
