-- Parser of LuaJIT's symtab binary stream.
-- The format spec can be found in <src/lj_memprof.h>.
--
-- Major portions taken verbatim or adapted from the LuaVela.
-- Copyright (C) 2015-2019 IPONWEB Ltd.

local bit = require "bit"

local band = bit.band
local string_format = string.format

local LJS_MAGIC = "ljs"
local LJS_CURRENT_VERSION = 0x2
local LJS_EPILOGUE_HEADER = 0x80
local LJS_SYMTYPE_MASK = 0x03

local SYMTAB_LFUNC = 0
local SYMTAB_TRACE = 1

local M = {}

-- Parse a single entry in a symtab: lfunc symbol.
local function parse_sym_lfunc(reader, symtab)
  local sym_addr = reader:read_uleb128()
  local sym_chunk = reader:read_string()
  local sym_line = reader:read_uleb128()

  symtab.lfunc[sym_addr] = {
    source = sym_chunk,
    linedefined = sym_line,
  }
end

local function parse_sym_trace(reader, symtab)
  local traceno = reader:read_uleb128()
  local trace_addr = reader:read_uleb128()
  local sym_addr = reader:read_uleb128()
  local sym_line = reader:read_uleb128()

  symtab.trace[traceno] = {
    addr = trace_addr,
    -- The structure <start> is the same as the one
    -- yielded from the <parse_location> function
    -- in the <memprof/parse.lua> module.
    start = {
      addr = sym_addr,
      line = sym_line,
      traceno = 0,
    },
  }
end

local parsers = {
  [SYMTAB_LFUNC] = parse_sym_lfunc,
  [SYMTAB_TRACE] = parse_sym_trace,
}

function M.parse(reader)
  local symtab = {
    lfunc = {},
    trace = {},
  }
  local magic = reader:read_octets(3)
  local version = reader:read_octets(1)

  -- Dummy-consume reserved bytes.
  local _ = reader:read_octets(3)

  if magic ~= LJS_MAGIC then
    error("Bad LJS format prologue: "..magic)
  end

  if string.byte(version) ~= LJS_CURRENT_VERSION then
    error(string_format(
         "LJS format version mismatch:"..
         "the tool expects %d, but your data is %d",
         LJS_CURRENT_VERSION,
         string.byte(version)
    ))

  end

  while not reader:eof() do
    local header = reader:read_octet()
    local is_final = band(header, LJS_EPILOGUE_HEADER) ~= 0

    if is_final then
      break
    end

    local sym_type = band(header, LJS_SYMTYPE_MASK)
    if parsers[sym_type] then
      parsers[sym_type](reader, symtab)
    end
  end

  return symtab
end

function M.id(loc)
  return string_format("f%#xl%dt%d", loc.addr, loc.line, loc.traceno)
end

local function demangle_trace(symtab, loc)
  local traceno = loc.traceno
  local addr = loc.addr

  assert(traceno ~= 0, "Location is a trace")

  local trace_str = string_format("TRACE [%d] %#x", traceno, addr)
  local trace = symtab.trace[traceno]

  -- If trace, which was remembered in the symtab, has not
  -- been flushed, associate it with a proto, where trace
  -- recording started.
  if trace and trace.addr == addr then
    assert(trace.start.traceno == 0, "Trace start is not a trace")
    return trace_str.." started at "..M.demangle(symtab, trace.start)
  end
  return trace_str
end

function M.demangle(symtab, loc)
  if loc.traceno ~= 0 then
    return demangle_trace(symtab, loc)
  end

  local addr = loc.addr

  if addr == 0 then
    return "INTERNAL"
  end

  if symtab.lfunc[addr] then
    return string_format("%s:%d", symtab.lfunc[addr].source, loc.line)
  end

  return string_format("CFUNC %#x", addr)
end

return M
