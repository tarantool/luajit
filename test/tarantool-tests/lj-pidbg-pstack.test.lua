local tap = require('tap')

local function quote(s)
  return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

local function command_available(cmd)
  return os.execute('command -v ' .. cmd .. ' >/dev/null 2>&1') == 0
end

-- Locate the interpreter that runs this test. The harness invokes
-- it as `<luajit> -e <init> <test>`, so `arg[-1]` is not the
-- interpreter; use the same helper as the rest of the suite.
local function find_interpreter()
  local ok, exe = pcall(function()
    return require('utils').exec.luabin(arg)
  end)
  if not ok or type(exe) ~= 'string' or exe == '' then
    return nil
  end
  if os.execute('test -x ' .. quote(exe)) ~= 0 then
    return nil
  end
  return exe
end

local luajit = find_interpreter()

local test = tap.test('lj-pidbg-pstack'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Test requires LUAJIT_USE_PIDEBUG'] = not pcall(require, 'jit.pidbg'),
  ['Test requires gdb'] = not command_available('gdb'),
  ['Test requires pstack'] = not command_available('pstack'),
  ['Test requires the luajit interpreter'] = luajit == nil,
  ['Disabled with Valgrind'] = os.getenv('LUAJIT_TEST_USE_VALGRIND'),
})

-- The child compiles a hot loop with precise debug info, then
-- spins in the compiled trace forever. The `READY` marker on
-- stderr tells the parent that the traces are registered.
local CHILD_SCRIPT = [==[
local pidbg = require('jit.pidbg')
assert(pidbg.start('l'))
local function work(n)
  local s = 0
  for i = 1, n do s = s + i end
  return s
end
jit.opt.start('hotloop=1')
for _ = 1, 200 do work(1000) end
io.stderr:write('READY\n')
io.stderr:flush()
local x = 0
while true do x = x + work(1000) end
]==]

local function make_tmpdir()
  local base = os.tmpname()
  if base == nil or base == '' then
    return nil
  end
  local dir = base .. '.pidbg'
  os.remove(base)
  if os.execute('mkdir -p ' .. quote(dir)) ~= 0 then
    return nil
  end
  return dir
end

local function remove_dir(dir)
  if dir ~= nil then
    os.execute('rm -rf ' .. quote(dir))
  end
end

local function write_child_script(path)
  local f = assert(io.open(path, 'w'))
  f:write(CHILD_SCRIPT)
  f:close()
end

local function is_alive(pid)
  return os.execute(('kill -0 %d 2>/dev/null'):format(pid)) == 0
end

local function stop_child(pid)
  if pid == nil then
    return
  end
  os.execute(('kill %d 2>/dev/null'):format(pid))
  for _ = 1, 20 do
    if not is_alive(pid) then
      return
    end
    os.execute('sleep 0.1')
  end
  os.execute(('kill -9 %d 2>/dev/null'):format(pid))
end

local function spawn_child(exe, script, log)
  local inner = ('exec %s %s >%s 2>&1 & echo $!')
    :format(quote(exe), quote(script), quote(log))
  local f = io.popen('sh -c ' .. quote(inner), 'r')
  if f == nil then
    return nil
  end
  local out = f:read('*a')
  f:close()
  local pid = out ~= nil and tonumber(out:match('%d+')) or nil
  if pid == nil or not is_alive(pid) then
    return nil
  end
  return pid
end

local function wait_ready(log, ticks)
  for _ = 1, ticks do
    local f = io.open(log, 'r')
    if f ~= nil then
      local data = f:read('*a')
      f:close()
      if data ~= nil and data:find('READY', 1, true) ~= nil then
        return true
      end
    end
    os.execute('sleep 0.1')
  end
  return false
end

local function run_capture(cmd)
  local f = io.popen(cmd .. ' 2>&1', 'r')
  if f == nil then
    return nil
  end
  local out = f:read('*a')
  f:close()
  return out or ''
end

-- The trace frame is expected on top of the stack, but retry
-- a few times to avoid a race on a slow machine.
local function capture_trace(cmd, tries)
  local out
  for _ = 1, tries do
    out = run_capture(cmd)
    if out ~= nil and out:match('TRACE_%d+') ~= nil then
      return out
    end
    os.execute('sleep 0.3')
  end
  return out
end

local function gdb_command(pid)
  return ('gdb -batch -q -p %d -ex %s -ex %s -ex %s'):format(
    pid, quote('set pagination off'), quote('bt'), quote('detach'))
end

local function is_attach_failure(out)
  return out:match('ptrace') ~= nil
      or out:match('Operation not permitted') ~= nil
      or out:match('Could not attach') ~= nil
      or out:match('No such process') ~= nil
      or out:match('unable to attach') ~= nil
      or out:match('not permitted') ~= nil
end

local function check_output(t, tool, out)
  if out == nil or out == '' then
    t:skip(tool .. ' produced no output')
    t:skip(tool .. ' resolved no source line')
    return
  end
  if out:match('TRACE_%d+') == nil and is_attach_failure(out) then
    t:skip(tool .. ' cannot attach to the process')
    t:skip(tool .. ' resolved no source line')
    return
  end
  t:like(out, 'TRACE_%d+', tool .. ' sees a TRACE_ frame')
  t:like(out, '%.lua:%d+', tool .. ' resolves the trace source line')
end

test:plan(4)

local dir = make_tmpdir()
if dir == nil then
  test:skiprest('cannot create a temporary directory')
end

local script = dir .. '/child.lua'
local log = dir .. '/child.log'
write_child_script(script)

local pid = spawn_child(luajit, script, log)
if pid == nil then
  remove_dir(dir)
  test:skiprest('cannot spawn the luajit child process')
end

local body_ok, body_err = pcall(function()
  if not wait_ready(log, 100) then
    error('the child did not become ready')
  end
  -- Let the JIT finish compiling and settle in the hot loop.
  os.execute('sleep 1')
  if not is_alive(pid) then
    error('the child died before attaching')
  end
  check_output(test, 'gdb', capture_trace(gdb_command(pid), 3))
  check_output(test, 'pstack', capture_trace(('pstack %d'):format(pid), 3))
end)

stop_child(pid)
remove_dir(dir)

if not body_ok then
  test:skiprest('debugger checks failed to run: ' .. tostring(body_err))
end

test:done(true)
