local tap = require('tap')
local test = tap.test('lj-pidbg-jitdump'):skipcond({
  ['Test requires JIT enabled'] = not jit.status(),
  ['Test requires LUAJIT_USE_PIDEBUG'] = not pcall(require, 'jit.pidbg'),
})

local pidbg = require('jit.pidbg')

-- Helpers to split and read files with plain Lua facilities.

local function split_tab(line)
  local fields = {}
  local pos = 1
  while true do
    local s, e = string.find(line, '\t', pos, true)
    if s == nil then
      fields[#fields + 1] = string.sub(line, pos)
      return fields
    end
    fields[#fields + 1] = string.sub(line, pos, s - 1)
    pos = e + 1
  end
end

local function read_file(path)
  local f = io.open(path, 'rb')
  if f == nil then
    return nil
  end
  local data = f:read('*a')
  f:close()
  return data
end

local function count_keys(t)
  local n = 0
  for _ in pairs(t) do
    n = n + 1
  end
  return n
end

-- Little-endian decoding of the jitdump binary format.

local function u32(data, pos)
  local a, b, c, d = string.byte(data, pos, pos + 3)
  if a == nil then
    return nil
  end
  return a + b * 256 + c * 65536 + d * 16777216
end

local function u64(data, pos)
  local lo = u32(data, pos)
  local hi = u32(data, pos + 4)
  if lo == nil or hi == nil then
    return nil
  end
  return lo + hi * 4294967296
end

-- Scan a NUL-terminated name, returning the position after it.
local function scan_name(data, pos, limit)
  local q = pos
  while q < limit and string.byte(data, q) ~= 0 do
    q = q + 1
  end
  if q >= limit then
    return nil
  end
  return q + 1
end

-- Read our own source to know the script line range.
local src = debug.getinfo(1, 'S').source
if string.sub(src, 1, 1) == '@' then
  src = string.sub(src, 2)
end
local script_lines = 0
local src_data = read_file(src)
if src_data ~= nil then
  script_lines = 1
  for _ in string.gmatch(src_data, '\n') do
    script_lines = script_lines + 1
  end
end

-- JIT_CODE_* record identifiers of the jitdump format.
local JIT_CODE_LOAD = 0
local JIT_CODE_DEBUG_INFO = 2
local JIT_CODE_UNWINDING_INFO = 4

local JITDUMP_MAGIC = 0x4a695444
local JITDUMP_VERSION = 1
local JITDUMP_HDR_SIZE = 40
local REC_HDR_SIZE = 16
-- ELF machine types accepted in the jitdump header.
local ELF_MACHINES = {
  [3] = true,   -- EM_386
  [62] = true,  -- EM_X86_64
  [40] = true,  -- EM_ARM
  [183] = true, -- EM_AARCH64
  [20] = true,  -- EM_PPC
  [8] = true,   -- EM_MIPS
}

-- 3 lifecycle + 6 in-memory + 6 sidecar + 5 jitdump checks.
test:plan(20)

test:ok(pidbg.active() == false, 'pidbg is inactive before start')

-- Force predictable compilation.
jit.opt.start('hotloop=1')
jit.flush()

local sidecar = os.tmpname()
local jitdump = os.tmpname()
local started = pidbg.start('b', sidecar, jitdump)
test:ok(started == true and pidbg.active() == true,
        'start returns true and activates pidbg')

-- A body spanning several distinct source lines inside a loop, so
-- that the compiled trace covers more than one line.
local function work(n)
  local s = 0
  for i = 1, n do
    s = s + i
    s = s - 1
    s = s + 1
  end
  return s
end

local acc = 0
for i = 1, 200 do
  acc = acc + work(i)
end
assert(acc ~= 0)

-- Trace numbering is not predictable, so scan a wide range
-- instead of relying on a specific number.
local n_traces = 0
local n_nonempty = 0
local sorted_ok = true
local first_zero_ok = true
local mem_lines_in_range = true
local mem_lines = {}
for tr = 1, 64 do
  local t = pidbg.trace(tr)
  if t ~= nil then
    n_traces = n_traces + 1
    if #t > 0 then
      n_nonempty = n_nonempty + 1
      if t[1].mcoff ~= 0 then
        first_zero_ok = false
      end
    end
    for i = 1, #t do
      local e = t[i]
      if i > 1 and e.mcoff < t[i - 1].mcoff then
        sorted_ok = false
      end
      if e.line < 1 or e.line > script_lines then
        mem_lines_in_range = false
      end
      mem_lines[e.line] = true
    end
  end
end

test:ok(n_traces > 0, 'at least one trace has debug info')
test:ok(n_nonempty > 0, 'at least one trace has checkpoints')
test:ok(sorted_ok, 'in-memory spans are sorted by mcoff')
test:ok(first_zero_ok, 'first in-memory mcoff is zero')
test:ok(mem_lines_in_range, 'in-memory lines are inside the script')
test:ok(count_keys(mem_lines) >= 2,
        'in-memory view has at least two distinct lines')

-- Stop before reading the emitted files: they are closed on stop.
local stopped = pidbg.stop()
test:ok(stopped == true and pidbg.active() == false,
        'stop returns true and deactivates pidbg')

-- Parse the sidecar text format.
local sc_data = read_file(sidecar) or ''
local sc_ok = true
local sc_known_ref = true
local sc_offsets_ok = true
local sc_nonzero_bcpos = false
local sc_lines = {}
local sc_traces = {}
local sc_ended = {}
local sc_lastoff = {}
local n_sc_trace = 0
local n_sc_span = 0
local n_sc_end = 0
for line in string.gmatch(sc_data, '[^\n]+') do
  local f = split_tab(line)
  local kind = f[1]
  if kind == 'trace' then
    n_sc_trace = n_sc_trace + 1
    if #f ~= 4 then
      sc_ok = false
    end
    local tr = tonumber(f[2])
    if tr == nil or tonumber(f[3]) == nil or tonumber(f[4]) == nil then
      sc_ok = false
    end
    if tr ~= nil then
      sc_traces[tr] = true
      sc_lastoff[tr] = -1
    end
  elseif kind == 'span' then
    n_sc_span = n_sc_span + 1
    if #f ~= 6 then
      sc_ok = false
    end
    local tr = tonumber(f[2])
    local mcoff = tonumber(f[3])
    local bcpos = tonumber(f[4])
    local scline = tonumber(f[5])
    if tr == nil or mcoff == nil or bcpos == nil or scline == nil then
      sc_ok = false
    else
      if sc_traces[tr] ~= true then
        sc_known_ref = false
      end
      if sc_lastoff[tr] == nil or mcoff < sc_lastoff[tr] then
        sc_offsets_ok = false
      end
      sc_lastoff[tr] = mcoff
      if bcpos ~= 0 then
        sc_nonzero_bcpos = true
      end
      sc_lines[scline] = true
    end
  elseif kind == 'end' then
    n_sc_end = n_sc_end + 1
    if #f ~= 2 then
      sc_ok = false
    end
    local tr = tonumber(f[2])
    if tr == nil or sc_traces[tr] ~= true or sc_ended[tr] then
      sc_ok = false
    else
      sc_ended[tr] = true
    end
  else
    sc_ok = false
  end
end
if n_sc_trace ~= n_sc_end or n_sc_trace < 1 or n_sc_span < 1 then
  sc_ok = false
end

test:ok(#sc_data > 0, 'sidecar file is not empty')
test:ok(sc_ok, 'sidecar records are well-formed')
test:ok(sc_known_ref, 'sidecar spans reference known traces')
test:ok(sc_offsets_ok, 'sidecar offsets are non-decreasing')
test:ok(sc_nonzero_bcpos, 'bytecode mode records a non-zero bcpos')
test:ok(count_keys(sc_lines) >= 2,
        'sidecar has at least two distinct lines')

-- Parse the jitdump binary format.
local jd = read_file(jitdump) or ''
local hdr_ok = false
if #jd >= JITDUMP_HDR_SIZE then
  local magic = u32(jd, 1)
  local version = u32(jd, 5)
  local total_size = u32(jd, 9)
  local elf_mach = u32(jd, 13)
  hdr_ok = magic == JITDUMP_MAGIC and version == JITDUMP_VERSION and
           total_size == JITDUMP_HDR_SIZE and
           ELF_MACHINES[elf_mach] == true
end

local recs = {}
local framing_ok = true
local off = JITDUMP_HDR_SIZE + 1
while off <= #jd do
  local id = u32(jd, off)
  local size = u32(jd, off + 4)
  if id == nil or size == nil or size < REC_HDR_SIZE or
     off + size > #jd + 1 then
    framing_ok = false
    break
  end
  recs[#recs + 1] = {id = id, size = size, pos = off}
  off = off + size
end
if off ~= #jd + 1 then
  framing_ok = false
end

local n_debug = 0
local n_load = 0
local n_unwind = 0
local dbg_ok = true
local dbg_has_entry = false
local jd_lines = {}
for i = 1, #recs do
  local r = recs[i]
  if r.id == JIT_CODE_DEBUG_INFO then
    n_debug = n_debug + 1
    local p = r.pos + REC_HDR_SIZE
    local limit = r.pos + r.size
    local ca = u64(jd, p)
    local nr = u64(jd, p + 8)
    if ca == nil or nr == nil then
      dbg_ok = false
    else
      -- The matching JIT_CODE_LOAD must follow immediately.
      local lrec = recs[i + 1]
      local lca, lsize
      if lrec ~= nil and lrec.id == JIT_CODE_LOAD then
        local lp = lrec.pos + REC_HDR_SIZE
        lca = u64(jd, lp + 16)
        lsize = u64(jd, lp + 24)
      end
      if nr >= 1 then
        dbg_has_entry = true
      end
      if lca == nil or lsize == nil or lca ~= ca then
        dbg_ok = false
      end
      local q = p + 16
      for _ = 1, nr do
        local ea = u64(jd, q)
        local line = u32(jd, q + 8)
        if ea == nil or line == nil then
          dbg_ok = false
          break
        end
        if lca ~= nil and lsize ~= nil and
           (ea < lca or ea >= lca + lsize) then
          dbg_ok = false
        end
        jd_lines[line] = true
        q = scan_name(jd, q + 16, limit)
        if q == nil then
          dbg_ok = false
          break
        end
      end
    end
  elseif r.id == JIT_CODE_LOAD then
    n_load = n_load + 1
  elseif r.id == JIT_CODE_UNWINDING_INFO then
    n_unwind = n_unwind + 1
  end
end

test:ok(hdr_ok, 'jitdump header is valid')
test:ok(framing_ok, 'jitdump records are framed consistently')
test:ok(n_debug >= 1 and n_load >= 1 and n_unwind >= 1,
        'jitdump contains debug, load and unwinding records')
test:ok(dbg_ok and dbg_has_entry,
        'debug info entries are inside the matching load')
test:ok(count_keys(jd_lines) >= 2,
        'jitdump has at least two distinct lines')

os.remove(sidecar)
os.remove(jitdump)

test:done(true)
