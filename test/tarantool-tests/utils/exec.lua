local M = {}

local function executable_idx(args)
  -- arg[-1] is guaranteed to be not nil.
  local idx = -2
  while args[idx] do
    assert(type(args[idx]) == 'string', 'Command part have to be a string')
    idx = idx - 1
  end
  return idx + 1
end

function M.luabin(args)
  -- Return only the executable.
  return args[executable_idx(args)]
end

function M.luacmd(args)
  -- Return the full command with flags.
  return table.concat(args, ' ', executable_idx(args), -1)
end

local function makeenv(tabenv)
  if tabenv == nil then return '' end
  local flatenv = {}
  for var, value in pairs(tabenv) do
    if var == 'LD_PRELOAD' then
      -- XXX: For ASan used by GCC, the ASan library should go
      -- first in the `LD_PRELOAD` list, or we get the error:
      -- "ASan runtime does not come first in initial library
      -- list;".
      -- See https://github.com/tarantool/tarantool/issues/9656
      -- for details.
      -- So, prepend the given library from `LD_PRELOAD` to the
      -- start of the list. The separator may be ':' or ' ', see
      -- man ld.so(8).so. Use ':' as the most robust.
      local ld_preload = os.getenv('LD_PRELOAD')
      local ld_preload_prefix = ld_preload and ld_preload .. ':' or ''
      value = ld_preload_prefix .. value
    end
    table.insert(flatenv, ('%s=%s'):format(var, value))
  end
  return table.concat(flatenv, ' ')
end

-- <makecmd_exec> creates a command that runs given binary
-- with the given environment, launch options and zero or
-- more permanent arguments.
-- The function yields an object (i.e. table) with the
-- aforementioned parameters. To launch the command just call
-- the object. Additional arguments which may vary from call
-- to call are the `__call` args.
-- Pass tap.test() object as opt.t for diagnostic.
function M.makecmd_exec(bin, opts)
  assert(type(bin) == 'string')
  assert(opts == nil or type(opts) == 'table')
  local perm_args = opts and opts.args or {}
  assert(type(perm_args) == 'table')
  return setmetatable({
    BIN = bin,
    ENV = opts and makeenv(opts.env) or '',
    REDIRECT = opts and opts.redirect or '',
    PERMARGS = (' %s'):rep(#perm_args):format(unpack(perm_args)),
    t = opts and opts.t,
  }, {
    __call = function(self, ...)
      -- This line just makes the command for <io.popen> by the
      -- following steps:
      -- 1. Replace the placeholders with the corresponding values
      --    given to the command constructor (e.g. bin, env).
      -- 2. Join all CLI arguments given to the __call metamethod.
      -- 3. Concatenate the results of step 1 and step 2 to obtain
      --    the resulting command.
      local cmd = ('<ENV> <BIN> <REDIRECT> <PERMARGS>'):gsub('%<(%w+)>', self)
                  .. (' %s'):rep(select('#', ...)):format(...)
      if self.t ~= nil then self.t:diag('cmd: '..cmd) end
      -- Trim both leading and trailing whitespace from the output
      -- produced by the child process.
      local output = io.popen(cmd):
        read('*all'):gsub('^%s+', ''):gsub('%s+$', '')
      if self.t ~= nil then self.t:diag('output: '..output) end
      return output
    end
  })
end

-- Makes a file name for running test's data file in
-- '%testname%' directory.
function M.test_data(arg, name)
  return arg[0]:gsub('%.test%.lua$', '/'..name)
end

-- <makecmd_bash> creates a command that runs %testname%/script.sh
-- with the given environment, launch options and CLI arguments.
function M.makecmd_bash(arg, opts)
  local script = opts and opts.script or M.test_data(arg, 'script.sh')
  return M.makecmd_exec('/bin/bash', {
    env = opts and opts.env or nil,
    redirect = opts and opts.redirect or nil,
    args = {script},
    t = opts and opts.t or nil,
  })
end

-- <makecmd> creates a command that runs %testname%/script.lua by
-- <LUAJIT_TEST_BINARY> with the given environment, launch options
-- and CLI arguments.
function M.makecmd(arg, opts)
  local luabin = M.luacmd(arg)
  local script = opts and opts.script or M.test_data(arg, 'script.lua')
  return M.makecmd_exec(luabin, {
    env = opts and opts.env or nil,
    redirect = opts and opts.redirect or nil,
    args = {script},
    t = opts and opts.t or nil,
  })
end

return M
