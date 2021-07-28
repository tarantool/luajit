-- Memprof is implemented for x86 and x64 architectures only.
require("utils").skipcond(
  jit.arch ~= "x86" and jit.arch ~= "x64",
  jit.arch.." architecture is NIY for memprof"
)

local tap = require("tap")

local test = tap.test("misc-memprof-lapi")
test:plan(4)

local jit_opt_default = {
    3, -- level
    "hotloop=56",
    "hotexit=10",
    "minstitch=0",
}

jit.off()
jit.flush()

local table_new = require "table.new"

local bufread = require "utils.bufread"
local memprof = require "memprof.parse"
local process = require "memprof.process"
local symtab = require "utils.symtab"

local TMP_BINFILE = arg[0]:gsub(".+/([^/]+)%.test%.lua$", "%.%1.memprofdata.tmp.bin")
local BAD_PATH = arg[0]:gsub(".+/([^/]+)%.test%.lua$", "%1/memprofdata.tmp.bin")

local function default_payload()
  -- Preallocate table to avoid table array part reallocations.
  local _ = table_new(20, 0)

  -- Want too see 20 objects here.
  for i = 1, 20 do
    -- Try to avoid crossing with "test" module objects.
    _[i] = "memprof-str-"..i
  end

  _ = nil
  -- VMSTATE == GC, reported as INTERNAL.
  collectgarbage()
end

local function generate_output(filename, payload)
  -- Clean up all garbage to avoid pollution of free.
  collectgarbage()

  local res, err = misc.memprof.start(filename)
  -- Should start succesfully.
  assert(res, err)

  payload()

  res, err = misc.memprof.stop()
  -- Should stop succesfully.
  assert(res, err)
end

local function generate_parsed_output(payload)
  local res, err = pcall(generate_output, TMP_BINFILE, payload)

  -- Want to cleanup carefully if something went wrong.
  if not res then
    os.remove(TMP_BINFILE)
    error(err)
  end

  local reader = bufread.new(TMP_BINFILE)
  local symbols = symtab.parse(reader)
  local events = memprof.parse(reader)

  -- We don't need it any more.
  os.remove(TMP_BINFILE)

  return symbols, events
end

local function fill_ev_type(events, symbols, event_type)
  local ev_type = {
    line = {},
    trace = {},
  }
  for _, event in pairs(events[event_type]) do
    local addr = event.loc.addr
    local traceno = event.loc.traceno

    if traceno ~= 0 and symbols.trace[traceno] then
      local trace_loc = symbols.trace[traceno].start
      addr = trace_loc.addr
      ev_type.trace[traceno] = {
        name = string.format("TRACE [%d] %s:%d",
          traceno, symbols.lfunc[addr].source, trace_loc.line
        ),
        num = event.num,
      }
    elseif addr == 0 then
      ev_type.INTERNAL = {
        name = "INTERNAL",
        num = event.num,
      }
    elseif symbols.lfunc[addr] then
      ev_type.line[event.loc.line] = {
        name = string.format(
          "%s:%d", symbols.lfunc[addr].source, symbols.lfunc[addr].linedefined
        ),
        num = event.num,
      }
    end
  end
  return ev_type
end

local function form_source_line(line)
  return string.format("@%s:%d", arg[0], line)
end

local function check_alloc_report(alloc, location, nevents)
  local expected_name, event
  local traceno = location.traceno
  if traceno then
    expected_name = string.format("TRACE [%d] ", traceno)..
                    form_source_line(location.line)
    event = alloc.trace[traceno]
  else
    expected_name = form_source_line(location.linedefined)
    event = alloc.line[location.line]
  end
  assert(expected_name == event.name, ("got='%s', expected='%s'"):format(
    event.name,
    expected_name
  ))
  assert(event.num == nevents, ("got=%d, expected=%d"):format(
    event.num,
    nevents
  ))
  return true
end

-- Test profiler API.
test:test("smoke", function(subtest)
  subtest:plan(6)

  -- Not a directory.
  local res, err, errno = misc.memprof.start(BAD_PATH)
  subtest:ok(res == nil and err:match("No such file or directory"))
  subtest:ok(type(errno) == "number")

  -- Profiler is running.
  res, err = misc.memprof.start("/dev/null")
  assert(res, err)
  res, err, errno = misc.memprof.start("/dev/null")
  subtest:ok(res == nil and err:match("profiler is running already"))
  subtest:ok(type(errno) == "number")

  res, err = misc.memprof.stop()
  assert(res, err)

  -- Profiler is not running.
  res, err, errno = misc.memprof.stop()
  subtest:ok(res == nil and err:match("profiler is not running"))
  subtest:ok(type(errno) == "number")
end)

-- Test profiler output and parse.
test:test("output", function(subtest)
  subtest:plan(7)

  local symbols, events = generate_parsed_output(default_payload)

  local alloc = fill_ev_type(events, symbols, "alloc")
  local free = fill_ev_type(events, symbols, "free")

  -- Check allocation reports. The second argument is a line
  -- number of the allocation event itself. The third is a line
  -- number of the corresponding function definition. The last
  -- one is the number of allocations. 1 event - alocation of
  -- table by itself + 1 allocation of array part as far it is
  -- bigger than LJ_MAX_COLOSIZE (16).
  subtest:ok(check_alloc_report(alloc, { line = 34, linedefined = 32 }, 2))
  -- 20 strings allocations.
  subtest:ok(check_alloc_report(alloc, { line = 39, linedefined = 32 }, 20))

  -- Collect all previous allocated objects.
  subtest:ok(free.INTERNAL.num == 22)

  -- Tests for leak-only option.
  -- See also https://github.com/tarantool/tarantool/issues/5812.
  local heap_delta = process.form_heap_delta(events, symbols)
  local tab_alloc_stats = heap_delta[form_source_line(34)]
  local str_alloc_stats = heap_delta[form_source_line(39)]
  subtest:ok(tab_alloc_stats.nalloc == tab_alloc_stats.nfree)
  subtest:ok(tab_alloc_stats.dbytes == 0)
  subtest:ok(str_alloc_stats.nalloc == str_alloc_stats.nfree)
  subtest:ok(str_alloc_stats.dbytes == 0)
end)

-- Test for https://github.com/tarantool/tarantool/issues/5842.
test:test("stack-resize", function(subtest)
  subtest:plan(0)

  -- We are not interested in this report.
  misc.memprof.start("/dev/null")
  -- We need to cause stack resize for local variables at function
  -- call. Let's create a new coroutine (all slots are free).
  -- It has 1 slot for dummy frame + 39 free slots + 5 extra slots
  -- (so-called red zone) + 2 * LJ_FR2 slots. So 50 local
  -- variables is enough.
  local payload_str = ""
  for i = 1, 50 do
    payload_str = payload_str..("local v%d = %d\n"):format(i, i)
  end
  local f, errmsg = loadstring(payload_str)
  assert(f, errmsg)
  local co = coroutine.create(f)
  coroutine.resume(co)
  misc.memprof.stop()
end)

-- Test profiler with enabled JIT.
jit.on()

test:test("jit-output", function(subtest)
  -- Disabled on *BSD due to #4819.
  if jit.os == 'BSD' then
    subtest:plan(1)
    subtest:skip('Disabled due to #4819')
    return
  end

  subtest:plan(3)

  jit.opt.start(3, "hotloop=10")
  jit.flush()

  -- On this run traces are generated, JIT-related allocations
  -- will be recorded as well.
  local symbols, events = generate_parsed_output(default_payload)

  local alloc = fill_ev_type(events, symbols, "alloc")

  -- Test for marking JIT-related allocations as internal.
  -- See also https://github.com/tarantool/tarantool/issues/5679.
  subtest:ok(alloc.line[0] == nil)

  -- Run already generated traces.
  symbols, events = generate_parsed_output(default_payload)

  alloc = fill_ev_type(events, symbols, "alloc")

  -- We expect, that loop will be compiled into a trace.
  subtest:ok(check_alloc_report(alloc, { traceno = 1, line = 37 }, 20))
  -- See same checks with jit.off().
  subtest:ok(check_alloc_report(alloc, { line = 34, linedefined = 32 }, 2))

  -- Restore default JIT settings.
  jit.opt.start(unpack(jit_opt_default))
end)

os.exit(test:check() and 0 or 1)
