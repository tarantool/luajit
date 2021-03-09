local tap = require("tap")

local test = tap.test("misc-memprof-lapi")
test:plan(9)

jit.off()
jit.flush()

local table_new = require "table.new"

local bufread = require "utils.bufread"
local memprof = require "memprof.parse"
local symtab = require "utils.symtab"

local TMP_BINFILE = arg[0]:gsub(".+/([^/]+)%.test%.lua$", "%.%1.memprofdata.tmp.bin")
local BAD_PATH = arg[0]:gsub(".+/([^/]+)%.test%.lua$", "%1/memprofdata.tmp.bin")

local function payload()
  -- Preallocate table to avoid table array part reallocations.
  local _ = table_new(100, 0)

  -- Want too see 100 objects here.
  for i = 1, 100 do
    -- Try to avoid crossing with "test" module objects.
    _[i] = "memprof-str-"..i
  end

  _ = nil
  -- VMSTATE == GC, reported as INTERNAL.
  collectgarbage()
end

local function generate_output(filename)
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

local function fill_ev_type(events, symbols, event_type)
  local ev_type = {}
  for _, event in pairs(events[event_type]) do
    local addr = event.loc.addr
    if addr == 0 then
      ev_type.INTERNAL = {
        name = "INTERNAL",
        num = event.num,
    }
    elseif symbols[addr] then
      ev_type[event.loc.line] = {
        name = symbols[addr].name,
        num = event.num,
      }
    end
  end
  return ev_type
end

local function check_alloc_report(alloc, line, function_line, nevents)
  assert(string.format("@%s:%d", arg[0], function_line) == alloc[line].name)
  assert(alloc[line].num == nevents, ("got=%d, expected=%d"):format(
    alloc[line].num,
    nevents
  ))
  return true
end

-- Not a directory.
local res, err, errno = misc.memprof.start(BAD_PATH)
test:ok(res == nil and err:match("No such file or directory"))
test:ok(type(errno) == "number")

-- Profiler is running.
res, err = misc.memprof.start(TMP_BINFILE)
assert(res, err)
res, err, errno = misc.memprof.start(TMP_BINFILE)
test:ok(res == nil and err:match("profiler is running already"))
test:ok(type(errno) == "number")

res, err = misc.memprof.stop()
assert(res, err)

-- Profiler is not running.
res, err, errno = misc.memprof.stop()
test:ok(res == nil and err:match("profiler is not running"))
test:ok(type(errno) == "number")

-- Test profiler output and parse.
res, err = pcall(generate_output, TMP_BINFILE)

-- Want to cleanup carefully if something went wrong.
if not res then
  os.remove(TMP_BINFILE)
  error(err)
end

local reader = bufread.new(TMP_BINFILE)
local symbols = symtab.parse(reader)
local events = memprof.parse(reader, symbols)

-- We don't need it any more.
os.remove(TMP_BINFILE)

local alloc = fill_ev_type(events, symbols, "alloc")
local free = fill_ev_type(events, symbols, "free")

-- Check allocation reports. The second argument is a line number
-- of the allocation event itself. The third is a line number of
-- the corresponding function definition. The last one is
-- the number of allocations.
-- 1 event - alocation of table by itself + 1 allocation
-- of array part as far it is bigger than LJ_MAX_COLOSIZE (16).
test:ok(check_alloc_report(alloc, 20, 18, 2))
-- 100 strings allocations.
test:ok(check_alloc_report(alloc, 25, 18, 100))

-- Collect all previous allocated objects.
test:ok(free.INTERNAL.num == 102)

-- Test for https://github.com/tarantool/tarantool/issues/5842.
-- We are not interested in this report.
misc.memprof.start("/dev/null")
-- We need to cause stack resize for local variables at function
-- call. Let's create a new coroutine (all slots are free).
-- It has 1 slot for dummy frame + 39 free slots + 5 extra slots
-- (so-called red zone) + 2 * LJ_FR2 slots. So 50 local variables
-- is enough.
local payload_str = ""
for i = 1, 50 do
  payload_str = payload_str..("local v%d = %d\n"):format(i, i)
end
local f, errmsg = loadstring(payload_str)
assert(f, errmsg)
local co = coroutine.create(f)
coroutine.resume(co)
misc.memprof.stop()

jit.on()
os.exit(test:check() and 0 or 1)
