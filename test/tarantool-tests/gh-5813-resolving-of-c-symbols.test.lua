-- Memprof is implemented for x86 and x64 architectures only.
require("utils").skipcond(
  jit.arch ~= "x86" and jit.arch ~= "x64" or jit.os ~= "Linux",
  jit.arch.." architecture or "..jit.os..
  " OS is NIY for memprof c symbols resolving"
)

local tap = require("tap")
local test = tap.test("gh-5813-resolving-of-c-symbols")
test:plan(5)

jit.off()
jit.flush()

local bufread = require "utils.bufread"
local symtab = require "utils.symtab"
local testboth = require "resboth"
local testhash = require "reshash"
local testgnuhash = require "resgnuhash"

local TMP_BINFILE = arg[0]:gsub(".+/([^/]+)%.test%.lua$", "%.%1.memprofdata.tmp.bin")

local function tree_contains(node, name)
  if node == nil then
    return false
  else
    for i = 1, #node.value do
      if node.value[i].name == name then
        return true
      end
    end
    return tree_contains(node.left, name) or tree_contains(node.right, name)
  end
end

local function generate_output(filename, payload)
  local res, err = misc.memprof.start(filename)
  -- Should start successfully.
  assert(res, err)

  for _ = 1, 100 do
    payload()
  end

  res, err = misc.memprof.stop()
  -- Should stop successfully.
  assert(res, err)
end

local function generate_parsed_symtab(payload)
  local res, err = pcall(generate_output, TMP_BINFILE, payload)

  -- Want to cleanup carefully if something went wrong.
  if not res then
    os.remove(TMP_BINFILE)
    error(err)
  end

  local reader = bufread.new(TMP_BINFILE)
  local symbols = symtab.parse(reader)

  -- We don't need it any more.
  os.remove(TMP_BINFILE)

  return symbols
end

local symbols = generate_parsed_symtab(function()
  -- That Lua module is required here to trigger the `luaopen_os`,
  -- which is not stripped.
  require("resstripped").allocate_string()
end)

-- Static symbols resolution.
test:ok(tree_contains(symbols.cfunc, "luaopen_os"))

-- Dynamic symbol resolution. Newly loaded symbol resolution.
test:ok(tree_contains(symbols.cfunc, "allocate_string"))

-- .hash style symbol table.
symbols = generate_parsed_symtab(testhash.allocate_string)
test:ok(tree_contains(symbols.cfunc, "allocate_string"))

-- .gnu.hash style symbol table.
symbols = generate_parsed_symtab(testgnuhash.allocate_string)
test:ok(tree_contains(symbols.cfunc, "allocate_string"))

-- Both symbol tables.
symbols = generate_parsed_symtab(testboth.allocate_string)
test:ok(tree_contains(symbols.cfunc, "allocate_string"))

-- FIXME: There is one case that is not tested -- shared objects, which
-- have neither .symtab section nor .dynsym segment. It is unclear how to
-- perform a test in that case, since it is impossible to load Lua module
-- written in C if it doesn't have a .dynsym segment.

os.exit(test:check() and 0 or 1)
