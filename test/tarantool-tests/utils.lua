local M = {}

local ffi = require('ffi')
local tap = require('tap')
local bc = require('jit.bc')
local bit = require('bit')

local LJ_GC_BLACK = 0x04
local LJ_STR_HASHLEN = 8
local GCref = ffi.abi('gc64') and 'uint64_t' or 'uint32_t'

ffi.cdef([[
  typedef struct {
]]..GCref..[[ nextgc;
    uint8_t   marked;
    uint8_t   gct;
    /* Need this fields for correct alignment and sizeof. */
    uint8_t   misc1;
    uint8_t   misc2;
  } GCHeader;
]])

function M.gcisblack(obj)
  local objtype = type(obj)
  local address = objtype == 'string'
    -- XXX: get strdata first and go back to GCHeader.
    and ffi.cast('char *', obj) - (ffi.sizeof('GCHeader') + LJ_STR_HASHLEN)
    -- XXX: FFI ABI forbids to cast functions objects
    -- to non-functional pointers, but we can get their address
    -- via tostring.
    or tonumber((tostring(obj):gsub(objtype .. ': ', '')))
  local marked = ffi.cast('GCHeader *', address).marked
  return bit.band(marked, LJ_GC_BLACK) == LJ_GC_BLACK
end

function M.luacmd(args)
  -- arg[-1] is guaranteed to be not nil.
  local idx = -2
  while args[idx] do
    assert(type(args[idx]) == 'string', 'Command part have to be a string')
    idx = idx - 1
  end
  -- return the full command with flags.
  return table.concat(args, ' ', idx + 1, -1)
end

local function unshiftenv(variable, value, sep)
  local envvar = os.getenv(variable)
  return ('%s="%s%s"'):format(variable, value,
                              envvar and ('%s%s'):format(sep, envvar) or '')
end

function M.selfrun(arg, checks)
  -- If TEST_SELFRUN is set, it means the test has been run via
  -- <io.popen>, so just return from this routine and proceed
  -- the execution to the test payload, ...
  if os.getenv('TEST_SELFRUN') then return end

  -- ... otherwise initialize <tap>, setup testing environment
  -- and run this chunk via <io.popen> for each case in <checks>.
  -- XXX: The function doesn't return back from this moment. It
  -- checks whether all assertions are fine and exits.

  local test = tap.test(arg[0]:match('/?(.+)%.test%.lua'))

  test:plan(#checks)

  local libext = package.cpath:match('?.(%a+);')
  local vars = {
    LUABIN = M.luacmd(arg),
    SCRIPT = arg[0],
    PATH   = arg[0]:gsub('%.test%.lua', ''),
    SUFFIX = libext,
    ENV = table.concat({
      unshiftenv('LUA_PATH', '<PATH>/?.lua', ';'),
      unshiftenv('LUA_CPATH', '<PATH>/?.<SUFFIX>', ';'),
      unshiftenv((libext == 'dylib' and 'DYLD' or 'LD') .. '_LIBRARY_PATH',
                 '<PATH>', ':'),
      'TEST_SELFRUN=1',
    }, ' '),
  }

  local cmd = string.gsub('<ENV> <LUABIN> 2>&1 <SCRIPT>', '%<(%w+)>', vars)

  for _, ch in pairs(checks) do
    local testf = test[ch.test]
    assert(testf, ("tap doesn't provide test.%s function"):format(ch.test))
    local proc = io.popen((cmd .. (' %s'):rep(#ch.arg)):format(unpack(ch.arg)))
    local res = proc:read('*all'):gsub('^%s+', ''):gsub('%s+$', '')
    -- XXX: explicitly pass <test> as an argument to <testf>
    -- to emulate test:is(...), test:like(...), etc.
    testf(test, res, ch.res, ch.msg)
  end

  os.exit(test:check() and 0 or 1)
end

function M.skipcond(condition, message)
  if not condition then return end
  local test = tap.test(arg[0]:match('/?(.+)%.test%.lua'))
  test:plan(1)
  test:skip(message)
  os.exit(test:check() and 0 or 1)
end

function M.hasbc(f, bytecode)
  assert(type(f) == 'function', 'argument #1 should be a function')
  assert(type(bytecode) == 'string', 'argument #2 should be a string')
  local function empty() end
  local hasbc = false
  -- Check the bytecode entry line by line.
  local out = {
    write = function(out, line)
      if line:match(bytecode) then
        hasbc = true
        out.write = empty
      end
    end,
    flush = empty,
    close = empty,
  }
  bc.dump(f, out)
  return hasbc
end

return M
