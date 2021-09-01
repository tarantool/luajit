-- Parser of LuaJIT's sysprof binary stream.
-- The format spec can be found in <src/lj_sysprof.h>.

local symtab = require "utils.symtab"

local string_format = string.format

local LJP_MAGIC = "ljp"
local LJP_CURRENT_VERSION = 1

local M = {}

M.VMST = {
  INTERP = 0,
  LFUNC  = 1,
  FFUNC  = 2,
  CFUNC  = 3,
  GC     = 4,
  EXIT   = 5,
  RECORD = 6,
  OPT    = 7,
  ASM    = 8,
  TRACE  = 9,
  SYMTAB = 10,
}


M.FRAME = {
  LFUNC  = 1,
  CFUNC  = 2,
  FFUNC  = 3,
  BOTTOM = 0x80
}

local STREAM_END = 0x80
local SYMTAB_EVENT = 10

local function new_event()
  return {
    lua = {
      vmstate = 0,
      callchain = {},
      trace = {
        traceno = nil,
        addr = 0,
        line = 0,
      }
    },
    host = {
      callchain = {}
    }
  }
end

local function parse_lfunc(reader, event, symbols)
  local addr = reader:read_uleb128()
  local line = reader:read_uleb128()
  local loc = symtab.loc(symbols, { addr = addr, line = line })
  loc.type = M.FRAME.LFUNC
  table.insert(event.lua.callchain, 1, loc)
end

local function parse_ffunc(reader, event, _)
  local ffid = reader:read_uleb128()
  table.insert(event.lua.callchain, 1, {
    type = M.FRAME.FFUNC,
    ffid = ffid,
  })
end

local function parse_cfunc(reader, event, symbols)
  local addr = reader:read_uleb128()
  local loc = symtab.loc(symbols, { addr = addr })
  loc.type = M.FRAME.CFUNC
  table.insert(event.lua.callchain, 1, loc)
end

local frame_parsers = {
  [M.FRAME.LFUNC] = parse_lfunc,
  [M.FRAME.FFUNC] = parse_ffunc,
  [M.FRAME.CFUNC] = parse_cfunc
}

local function parse_lua_callchain(reader, event, symbols)
  while true do
    local frame_header = reader:read_octet()
    if frame_header == M.FRAME.BOTTOM then
      break
    end
    frame_parsers[frame_header](reader, event, symbols)
  end
end

--~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~--

local function parse_host_callchain(reader, event, symbols)
  local addr = reader:read_uleb128()

  while addr ~= 0 do
    local loc = symtab.loc(symbols, { addr = addr })
    table.insert(event.host.callchain, 1, loc)
    addr = reader:read_uleb128()
  end
end

--~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~--

local function parse_trace_callchain(reader, event, symbols)
  event.lua.trace.traceno  = reader:read_uleb128()
  event.lua.trace.addr = reader:read_uleb128()
  event.lua.trace.line = reader:read_uleb128()
  event.lua.trace.gen = symtab.loc(symbols, event.lua.trace).gen
end

--~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~--

local function parse_host_only(reader, event, symbols)
  parse_host_callchain(reader, event, symbols)
end

local function parse_lua_host(reader, event, symbols)
  parse_lua_callchain(reader, event, symbols)
  parse_host_callchain(reader, event, symbols)
end

local function parse_trace(reader, event, symbols)
  parse_trace_callchain(reader, event, symbols)
  -- parse_lua_callchain(reader, event)
end

local function parse_symtab(reader, symbols)
  symtab.parse_sym_cfunc(reader, symbols)
end

local event_parsers = {
  [M.VMST.INTERP] = parse_host_only,
  [M.VMST.LFUNC]  = parse_lua_host,
  [M.VMST.FFUNC]  = parse_lua_host,
  [M.VMST.CFUNC]  = parse_lua_host,
  [M.VMST.GC]     = parse_host_only,
  [M.VMST.EXIT]   = parse_host_only,
  [M.VMST.RECORD] = parse_host_only,
  [M.VMST.OPT]    = parse_host_only,
  [M.VMST.ASM]    = parse_host_only,
  [M.VMST.TRACE]  = parse_trace,
}

local function parse_event(reader, events, symbols)
  local event = new_event()

  local vmstate = reader:read_octet()
  if vmstate == STREAM_END then
    -- TODO: samples & overruns
    return false
  elseif vmstate == SYMTAB_EVENT then
    parse_symtab(reader, symbols)
    return true
  end

  assert(0 <= vmstate and vmstate <= 9, "Vmstate "..vmstate.." is not valid")
  event.lua.vmstate = vmstate

  event_parsers[vmstate](reader, event, symbols)

  table.insert(events, event)
  return true
end

function M.parse(reader, symbols)
  local events = {}

  local magic = reader:read_octets(3)
  local version = reader:read_octets(1)
  -- Dummy-consume reserved bytes.
  local _ = reader:read_octets(3)

  if magic ~= LJP_MAGIC then
    error("Bad LJP format prologue: "..magic)
  end

  if string.byte(version) ~= LJP_CURRENT_VERSION then
    error(string_format(
      "LJP format version mismatch: the tool expects %d, but your data is %d",
      LJP_CURRENT_VERSION,
      string.byte(version)
    ))
  end

  while parse_event(reader, events, symbols) do
    -- Empty body.
  end

  return events
end

return M
