local M = {}

local bc = require('jit.bc')

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
