local tap = require("tap")
local test = tap.test("misc-sysprof-lapi"):skipcond({
  ["Sysprof is implemented for x86_64 only"] = jit.arch ~= "x86" and
                                               jit.arch ~= "x64",
  ["Sysprof is implemented for Linux only"] = jit.os ~= "Linux",
  ['Disabled with Valgrind (SIGPROF)'] = os.getenv("LJ_USE_VALGRIND") == 'ON',
})

test:plan(19)

jit.off()
-- XXX: Run JIT tuning functions in a safe frame to avoid errors
-- thrown when LuaJIT is compiled with JIT engine disabled.
pcall(jit.flush)

local bufread = require("utils.bufread")
local symtab = require("utils.symtab")
local sysprof = require("sysprof.parse")
local profilename = require("utils").tools.profilename

local TMP_BINFILE = profilename("sysprofdata.tmp.bin")
local BAD_PATH = profilename("sysprofdata/tmp.bin")

local function payload()
  local function fib(n)
    if n <= 1 then
      return n
    end
    return fib(n - 1) + fib(n - 2)
  end
  return fib(32)
end

local function generate_output(opts)
  local res, err = misc.sysprof.start(opts)
  assert(res, err)

  payload()

  res,err = misc.sysprof.stop()
  assert(res, err)
end

local function check_mode(mode, interval)
  local res = pcall(
    generate_output,
    { mode = mode, interval = interval, path = TMP_BINFILE }
  )

  if not res then
    test:fail(mode .. ' mode with interval ' .. interval)
    os.remove(TMP_BINFILE)
  end

  local reader = bufread.new(TMP_BINFILE)
  local symbols = symtab.parse(reader)
  sysprof.parse(reader, symbols)
end

-- GENERAL

-- Wrong profiling mode.
local res, err, errno = misc.sysprof.start{ mode = "A" }
test:ok(res == nil and err:match("profiler misuse"))
test:ok(type(errno) == "number")

-- Already running.
res, err = misc.sysprof.start{ mode = "D" }
assert(res, err)

res, err, errno = misc.sysprof.start{ mode = "D" }
test:ok(res == nil and err:match("profiler is running already"))
test:ok(type(errno) == "number")

res, err = misc.sysprof.stop()
assert(res, err)

-- Not running.
res, err, errno = misc.sysprof.stop()
test:ok(res == nil and err)
test:ok(type(errno) == "number")

-- Bad path.
res, err, errno = misc.sysprof.start({ mode = "C", path = BAD_PATH })
test:ok(res == nil and err:match("No such file or directory"))
test:ok(type(errno) == "number")

-- Bad interval.
res, err, errno = misc.sysprof.start{ mode = "C", interval = -1 }
test:ok(res == nil and err:match("profiler misuse"))
test:ok(type(errno) == "number")

-- DEFAULT MODE

if not pcall(generate_output, { mode = "D", interval = 100 }) then
  test:fail('`default` mode with interval 100')
end

local report = misc.sysprof.report()

-- Check the profile is not empty
test:ok(report.samples > 0)
-- There is a Lua function with FNEW bytecode in it. Hence there
-- are only three possible sample types:
-- * LFUNC -- Lua payload is sampled.
-- * GC -- Lua GC machinery triggered in scope of FNEW bytecode
--   is sampled.
-- * INTERP -- VM is in a specific state when the sample is taken.
test:ok(report.vmstate.LFUNC + report.vmstate.GC + report.vmstate.INTERP > 0)
-- There is no fast functions and C function in default payload.
test:ok(report.vmstate.FFUNC + report.vmstate.CFUNC == 0)
-- Check all JIT-related VM states are not sampled.
for _, vmstate in pairs({ 'TRACE', 'RECORD', 'OPT', 'ASM', 'EXIT' }) do
  test:ok(report.vmstate[vmstate] == 0)
end

-- With very big interval.
if not pcall(generate_output, { mode = "D", interval = 1000 }) then
  test:fail('`default` mode with interval 1000')
end

report = misc.sysprof.report()
test:ok(report.samples == 0)

-- LEAF MODE
check_mode("L", 100)

-- CALL MODE
check_mode("C", 100)

os.remove(TMP_BINFILE)

test:done(true)
