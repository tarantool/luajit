local bufread = require "utils.bufread"
local sysprof = require "sysprof.parse"
local symtab = require "utils.symtab"
local misc = require "sysprof.collapse"

local stdout, stderr = io.stdout, io.stderr
local match, gmatch = string.match, string.gmatch

local split_by_vmstate = false

-- Program options.
local opt_map = {}

function opt_map.help()
  stdout:write [[
luajit-parse-sysprof - parser of the profile collected
                       with LuaJIT's sysprof.

SYNOPSIS

luajit-parse-sysprof [options] sysprof.bin

Supported options are:

  --help                            Show this help and exit
  --split                           Split callchains by vmstate
]]
  os.exit(0)
end

function opt_map.split()
  split_by_vmstate = true
end

-- Print error and exit with error status.
local function opterror(...)
  stderr:write("luajit-parse-sysprof.lua: ERROR: ", ...)
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

local function traverse_calltree(node, prefix)
  if node.is_leaf then
    print(prefix..' '..node.count)
  end

  local sep_prefix = #prefix == 0 and prefix or prefix..';'

  for name,child in pairs(node.children) do
    traverse_calltree(child, sep_prefix..name)
  end
end

local function dump(inputfile)
  local reader = bufread.new(inputfile)

  local symbols = symtab.parse(reader)

  local events = sysprof.parse(reader, symbols)
  local calltree = misc.collapse(events, symbols, split_by_vmstate)

  traverse_calltree(calltree, '')

  os.exit(0)
end

-- FIXME: this script should be application-independent.
local args = {...}
if #args == 1 and args[1] == "sysprof" then
  return dump
else
  dump(parseargs(args))
end
