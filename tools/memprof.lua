-- A tool for parsing and visualisation of LuaJIT's memory
-- profiler output.
--
-- TODO:
-- * Think about callgraph memory profiling for complex
--   table reallocations
-- * Nicer output, probably an HTML view
-- * Demangling of C symbols
--
-- Major portions taken verbatim or adapted from the LuaVela.
-- Copyright (C) 2015-2019 IPONWEB Ltd.

local bufread = require "utils.bufread"
local memprof = require "memprof.parse"
local symtab = require "utils.symtab"
local view = require "memprof.humanize"

local stdout, stderr = io.stdout, io.stderr
local match, gmatch = string.match, string.gmatch

-- Program options.
local opt_map = {}

function opt_map.help()
  stdout:write [[
luajit-parse-memprof - parser of the memory usage profile collected
                       with LuaJIT's memprof.

SYNOPSIS

luajit-parse-memprof [options] memprof.bin

Supported options are:

  --help                            Show this help and exit
]]
  os.exit(0)
end

-- Print error and exit with error status.
local function opterror(...)
  stderr:write("luajit-parse-memprof.lua: ERROR: ", ...)
  stderr:write("\n")
  os.exit(1)
end

-- Parse single option.
local function parseopt(opt, args)
  local opt_current = #opt == 1 and "-"..opt or "--"..opt
  local f = opt_map[opt]
  if not f then
    opterror("unrecognized option `", opt_current, "'. Try `--help'.\n")
  end
  f(args)
end

-- Parse arguments.
local function parseargs(args)
  -- Process all option arguments.
  args.argn = 1
  repeat
    local a = args[args.argn]
    if not a then
      break
    end
    local lopt, opt = match(a, "^%-(%-?)(.+)")
    if not opt then
      break
    end
    args.argn = args.argn + 1
    if lopt == "" then
      -- Loop through short options.
      for o in gmatch(opt, ".") do
        parseopt(o, args)
      end
    else
      -- Long option.
      parseopt(opt, args)
    end
  until false

  -- Check for proper number of arguments.
  local nargs = #args - args.argn + 1
  if nargs ~= 1 then
    opt_map.help()
  end

  -- Translate a single input file.
  -- TODO: Handle multiple files?
  return args[args.argn]
end

local function dump(inputfile)
  local reader = bufread.new(inputfile)
  local symbols = symtab.parse(reader)
  local events = memprof.parse(reader, symbols)

  stdout:write("ALLOCATIONS", "\n")
  view.render(events.alloc, symbols)
  stdout:write("\n")

  stdout:write("REALLOCATIONS", "\n")
  view.render(events.realloc, symbols)
  stdout:write("\n")

  stdout:write("DEALLOCATIONS", "\n")
  view.render(events.free, symbols)
  stdout:write("\n")

  os.exit(0)
end

-- FIXME: this script should be application-independent.
local args = {...}
if #args == 1 and args[1] == "memprof" then
  return dump
else
  dump(parseargs(args))
end
