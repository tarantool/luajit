-- Parser of LuaJIT's memprof binary stream.
-- The format spec can be found in <src/lj_memprof.h>.
--
-- Major portions taken verbatim or adapted from the LuaVela.
-- Copyright (C) 2015-2019 IPONWEB Ltd.

local bit = require "bit"
local band = bit.band
local lshift = bit.lshift

local string_format = string.format

local LJM_MAGIC = "ljm"
local LJM_CURRENT_VERSION = 1

local LJM_EPILOGUE_HEADER = 0x80

local AEVENT_ALLOC = 1
local AEVENT_FREE = 2
local AEVENT_REALLOC = 3

local AEVENT_MASK = 0x3

local ASOURCE_INT = lshift(1, 2)
local ASOURCE_LFUNC = lshift(2, 2)
local ASOURCE_CFUNC = lshift(3, 2)

local ASOURCE_MASK = lshift(0x3, 2)

local M = {}

local function new_event(loc)
  return {
    loc = loc,
    num = 0,
    free = 0,
    alloc = 0,
    primary = {},
  }
end

local function link_to_previous(heap_chunk, e)
  -- Memory at this chunk was allocated before we start tracking.
  if heap_chunk then
    -- Save Lua code location (line) by address (id).
    e.primary[heap_chunk[2]] = heap_chunk[3]
  end
end

local function id_location(addr, line)
  return string_format("f%#xl%d", addr, line), {
    addr = addr,
    line = line,
  }
end

local function parse_location(reader, asource)
  if asource == ASOURCE_INT then
    return id_location(0, 0)
  elseif asource == ASOURCE_CFUNC then
    return id_location(reader:read_uleb128(), 0)
  elseif asource == ASOURCE_LFUNC then
    return id_location(reader:read_uleb128(), reader:read_uleb128())
  end
  error("Unknown asource "..asource)
end

local function parse_alloc(reader, asource, events, heap)
  local id, loc = parse_location(reader, asource)

  local naddr = reader:read_uleb128()
  local nsize = reader:read_uleb128()

  if not events[id] then
    events[id] = new_event(loc)
  end
  local e = events[id]
  e.num = e.num + 1
  e.alloc = e.alloc + nsize

  heap[naddr] = {nsize, id, loc}
end

local function parse_realloc(reader, asource, events, heap)
  local id, loc = parse_location(reader, asource)

  local oaddr = reader:read_uleb128()
  local osize = reader:read_uleb128()
  local naddr = reader:read_uleb128()
  local nsize = reader:read_uleb128()

  if not events[id] then
    events[id] = new_event(loc)
  end
  local e = events[id]
  e.num = e.num + 1
  e.free = e.free + osize
  e.alloc = e.alloc + nsize

  link_to_previous(heap[oaddr], e)

  heap[oaddr] = nil
  heap[naddr] = {nsize, id, loc}
end

local function parse_free(reader, asource, events, heap)
  local id, loc = parse_location(reader, asource)

  local oaddr = reader:read_uleb128()
  local osize = reader:read_uleb128()

  if not events[id] then
    events[id] = new_event(loc)
  end
  local e = events[id]
  e.num = e.num + 1
  e.free = e.free + osize

  link_to_previous(heap[oaddr], e)

  heap[oaddr] = nil
end

local parsers = {
  [AEVENT_ALLOC] = {evname = "alloc", parse = parse_alloc},
  [AEVENT_FREE] = {evname = "free", parse = parse_free},
  [AEVENT_REALLOC] = {evname = "realloc", parse = parse_realloc},
}

local function ev_header_is_valid(evh)
  return evh <= 0x0f or evh == LJM_EPILOGUE_HEADER
end

-- Splits event header into event type (aka aevent = allocation
-- event) and event source (aka asource = allocation source).
local function ev_header_split(evh)
  return band(evh, AEVENT_MASK), band(evh, ASOURCE_MASK)
end

local function parse_event(reader, events)
  local ev_header = reader:read_octet()

  assert(ev_header_is_valid(ev_header), "Bad ev_header "..ev_header)

  if ev_header == LJM_EPILOGUE_HEADER then
    return false
  end

  local aevent, asource = ev_header_split(ev_header)
  local parser = parsers[aevent]

  assert(parser, "Bad aevent "..aevent)

  parser.parse(reader, asource, events[parser.evname], events.heap)

  return true
end

function M.parse(reader)
  local events = {
    alloc = {},
    realloc = {},
    free = {},
    heap = {},
  }

  local magic = reader:read_octets(3)
  local version = reader:read_octets(1)
  -- Dummy-consume reserved bytes.
  local _ = reader:read_octets(3)

  if magic ~= LJM_MAGIC then
    error("Bad LJM format prologue: "..magic)
  end

  if string.byte(version) ~= LJM_CURRENT_VERSION then
    error(string_format(
      "LJM format version mismatch: the tool expects %d, but your data is %d",
      LJM_CURRENT_VERSION,
      string.byte(version)
    ))
  end

  while parse_event(reader, events) do
    -- Empty body.
  end

  return events
end

return M
