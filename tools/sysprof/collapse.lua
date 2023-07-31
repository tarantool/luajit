local parse = require "sysprof.parse"
local vmdef = require "jit.vmdef"
local symtab = require "utils.symtab"

local VMST_NAMES = {
  [parse.VMST.INTERP] = "VMST_INTERP",
  [parse.VMST.LFUNC]  = "VMST_LFUNC",
  [parse.VMST.FFUNC]  = "VMST_FFUNC",
  [parse.VMST.CFUNC]  = "VMST_CFUNC",
  [parse.VMST.GC]     = "VMST_GC",
  [parse.VMST.EXIT]   = "VMST_EXIT",
  [parse.VMST.RECORD] = "VMST_RECORD",
  [parse.VMST.OPT]    = "VMST_OPT",
  [parse.VMST.ASM]    = "VMST_ASM",
  [parse.VMST.TRACE]  = "VMST_TRACE",
}

local M = {}

local function new_node(name, is_leaf)
  return {
    name = name,
    count = 0,
    is_leaf = is_leaf,
    children = {}
  }
end

-- insert new child into a node (or increase counter in existing one)
local function insert(name, node, is_leaf)
  if node.children[name] == nil then
    node.children[name] = new_node(name, is_leaf)
  end

  local child = node.children[name]
  child.count = child.count + 1

  return child
end

local function insert_lua_callchain(chain, lua, symbols)
  local ins_cnt = 0
  for _,fr in pairs(lua.callchain) do
    local name_lua

    ins_cnt = ins_cnt + 1
    if fr.type == parse.FRAME.FFUNC then
      name_lua = vmdef.ffnames[fr.ffid]
    else
      name_lua = symtab.demangle(symbols, {
        addr = fr.addr,
        line = fr.line,
        gen = fr.gen
      })
      if lua.trace.traceno ~= nil and lua.trace.addr == fr.addr and
          lua.trace.line == fr.line then
        name_lua = symtab.demangle(symbols, {
          addr = fr.addr,
          traceno = lua.trace.traceno,
          gen = fr.gen
        })
      end

      if fr.type == parse.FRAME.CFUNC then
        -- C function encountered, the next chunk
        -- of frames is located on the C stack.
        break
      end
    end

    table.insert(chain, 1, { name = name_lua })
  end
  table.remove(lua.callchain, ins_cnt)
end

-- merge lua and host callchains into one callchain representing
-- transfer of control
local function merge(event, symbols)
  local cc = {}

  for _,h_fr in pairs(event.host.callchain) do
    local name_host = symtab.demangle(symbols, {
      addr = h_fr.addr,
      gen = h_fr.gen
    })
    table.insert(cc, 1, { name = name_host })

    if string.match(name_host, '^lua_cpcall') ~= nil then
      -- Any C function is present on both the C and the Lua
      -- stacks. It is more convenient to get its info from the
      -- host stack, since it has information about child frames.
      table.remove(event.lua.callchain, 1)
    end

    if string.match(name_host, '^lua_p?call') ~= nil then
      insert_lua_callchain(cc, event.lua, symbols)
    end

  end

  return cc
end

-- Collapse all the events into call tree
function M.collapse(events, symbols)
  local root = new_node('root', false)

  for _,ev in pairs(events) do
    local callchain = merge(ev, symbols)
    local curr_node = root
    for i=#callchain,1,-1 do
      curr_node = insert(callchain[i].name, curr_node, false)
    end
    insert('', curr_node, true)
  end

  return root
end

return M
