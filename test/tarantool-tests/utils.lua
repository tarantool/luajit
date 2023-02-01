local M = {}

local ffi = require('ffi')
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

local function makeenv(tabenv)
  if tabenv == nil then return '' end
  local flatenv = {}
  for var, value in pairs(tabenv) do
    table.insert(flatenv, ('%s=%s'):format(var, value))
  end
  return table.concat(flatenv, ' ')
end

-- <makecmd> creates a command that runs %testname%/script.lua by
-- <LUAJIT_TEST_BINARY> with the given environment, launch options
-- and CLI arguments. The function yields an object (i.e. table)
-- with the aforementioned parameters. To launch the command just
-- call the object.
function M.makecmd(arg, opts)
  return setmetatable({
    LUABIN = M.luacmd(arg),
    SCRIPT = opts and opts.script or arg[0]:gsub('%.test%.lua$', '/script.lua'),
    ENV = opts and makeenv(opts.env) or '',
    REDIRECT = opts and opts.redirect or '',
  }, {
    __call = function(self, ...)
      -- This line just makes the command for <io.popen> by the
      -- following steps:
      -- 1. Replace the placeholders with the corresponding values
      --    given to the command constructor (e.g. script, env).
      -- 2. Join all CLI arguments given to the __call metamethod.
      -- 3. Concatenate the results of step 1 and step 2 to obtain
      --    the resulting command.
      local cmd = ('<ENV> <LUABIN> <REDIRECT> <SCRIPT>'):gsub('%<(%w+)>', self)
                  .. (' %s'):rep(select('#', ...)):format(...)
      -- Trim both leading and trailing whitespace from the output
      -- produced by the child process.
      return io.popen(cmd):read('*all'):gsub('^%s+', ''):gsub('%s+$', '')
    end
  })
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

function M.profilename(name)
  local vardir = os.getenv('LUAJIT_TEST_VARDIR')
  -- Replace pattern will change directory name of the generated
  -- profile to LUAJIT_TEST_VARDIR if it is set in the process
  -- environment. Otherwise, the original dirname is left intact.
  -- As a basename for this profile the test name is concatenated
  -- with the name given as an argument.
  local replacepattern = ('%s/%s-%s'):format(vardir or '%1', '%2', name)
  -- XXX: return only the resulting string.
  return (arg[0]:gsub('^(.+)/([^/]+)%.test%.lua$', replacepattern))
end

M.const = {
  -- XXX: Max nins is limited by max IRRef, that equals to
  -- REF_DROP - REF_BIAS. Unfortunately, these constants are not
  -- provided to Lua space, so we ought to make some math:
  -- * REF_DROP = 0xffff
  -- * REF_BIAS = 0x8000
  maxnins = 0xffff - 0x8000,
}

return M
