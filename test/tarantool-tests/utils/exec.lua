local M = {}

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

return M
