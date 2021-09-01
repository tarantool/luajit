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
  for _,fr in pairs(lua.callchain) do
    local name_lua

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
    end

    table.insert(chain, 1, { name = name_lua })
  end
end

-- merge lua and host callchains into one callchain representing
-- transfer of control
local function merge(event, symbols, sep_vmst)
  local cc = {}
  local lua_inserted = false

  for _,h_fr in pairs(event.host.callchain) do
    local name_host = symtab.demangle(symbols, {
      addr = h_fr.addr,
      gen = h_fr.gen
    })

    -- We assume that usually the transfer of control
    -- looks like:
    --    HOST -> LUA -> HOST
    -- so for now, lua callchain starts from lua_pcall() call
    if name_host == 'lua_pcall' then
      insert_lua_callchain(cc, event.lua, symbols)
      lua_inserted = true
    end

    table.insert(cc, 1, { name = name_host })
  end

  if lua_inserted == false then
    insert_lua_callchain(cc, event.lua, symbols)
  end

  if sep_vmst == true then
    table.insert(cc, { name = VMST_NAMES[event.lua.vmstate] })
  end

  return cc
end

-- Collapse all the events into call tree
function M.collapse(events, symbols, sep_vmst)
  local root = new_node('root', false)

  for _,ev in pairs(events) do
    local callchain = merge(ev, symbols, sep_vmst)
    local curr_node = root
    for i=#callchain,1,-1 do
      curr_node = insert(callchain[i].name, curr_node, false)
    end
    insert('', curr_node, true)
  end

  return root
end

return M
