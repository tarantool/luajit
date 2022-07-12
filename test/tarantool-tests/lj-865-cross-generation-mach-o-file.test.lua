local tap = require('tap')
local test = tap.test('lj-865-cross-generation-mach-o-file')
local utils = require('utils')
local ffi = require('ffi')

test:plan(2)

-- The test creates an object file in Mach-O format with LuaJIT
-- bytecode and checks the validity of the object file fields.
--
-- The original problem is reproduced with LuaJIT, which is built
-- with enabled AVX512F instructions. The support for AVX512F
-- could be checked in `/proc/cpuinfo` on Linux and
-- `sysctl hw.optional.avx512f` on Mac. AVX512F must be
-- implicitly enabled in a C compiler by passing a CPU codename.
-- Please take a look at the GCC Online Documentation [1] for
-- available CPU codenames. Also, see the Wikipedia for CPUs with
-- AVX-512 support [2].
-- Execute command below to detect the CPU codename:
-- `gcc -march=native -Q --help=target | grep march`.
--
-- 1. https://gcc.gnu.org/onlinedocs/gcc/x86-Options.html
-- 2. https://en.wikipedia.org/wiki/AVX-512#CPUs_with_AVX-512
--
-- Manual steps for reproducing are the following:
--
-- $ CC=gcc TARGET_CFLAGS='skylake-avx512' cmake -S . -B build
-- $ cmake --build build --parallel
-- $ echo > test.lua
-- $ LUA_PATH="src/?.lua;;" luajit -b -o osx -a arm test.lua test.o
-- $ file test.o
-- empty.o: DOS executable (block device driver)

-- LuaJIT can generate so called Universal Binary with Lua
-- bytecode. The Universal Binary format is a format for
-- executable files that run natively on hardware platforms with
-- different hardware architectures. This concept is more
-- generally known as a fat binary.
--
-- The format of the Mach-O is described in the document
-- "OS X ABI Mach-O File Format Reference", published by Apple
-- company. The copy of the (now removed) official documentation
-- can be found here [1]. Yet another source of truth is
-- XNU headers, see the definition of C-structures in:
-- [2] (`nlist_64`), [3] (`fat_arch` and `fat_header`).
--
-- There is a good visual representation of Universal Binary
-- in "Mac OS X Internals" book (pages 67-68) [5] and in the [6].
-- Below is the schematic structure of Universal Binary, which
-- includes two executables for PowerPC and Intel i386 (omitted):
--
--   0x0000000 ---------------------------------------
--             |
-- struct      | 0xcafebabe  FAT_MAGIC                 magic
-- fat_header  | -------------------------------------
--             | 0x00000003                            nfat_arch
--             ---------------------------------------
--             | 0x00000012  CPU_TYPE_POWERPC          cputype
--             | -------------------------------------
--             | 0x00000000  CPU_SUBTYPE_POWERPC_ALL   cpusubtype
-- struct      | -------------------------------------
-- fat_arch    | 0x00001000  4096 bytes                offset
--             | -------------------------------------
--             | 0x00004224  16932 bytes               size
--             | -------------------------------------
--             | 0x0000000c  2^12 = 4096 bytes         align
--             ---------------------------------------
--             ---------------------------------------
--             | 0x00000007  CPU_TYPE_I386             cputype
--             | -------------------------------------
--             | 0x00000003  CPU_SUBTYPE_I386_ALL      cpusubtype
-- struct      | -------------------------------------
-- fat_arch    | 0x00006000  24576 bytes               offset
--             | -------------------------------------
--             | 0x0000292c  10540 bytes               size
--             | -------------------------------------
--             | 0x0000000c  2^12 = 4096 bytes         align
--             ---------------------------------------
--               Unused
-- 0x00001000  ---------------------------------------
--             | 0xfeedface  MH_MAGIC                  magic
--             | ------------------------------------
--             | 0x00000012  CPU_TYPE_POWERPC          cputype
--             | ------------------------------------
-- struct      | 0x00000000  CPU_SUBTYPE_POWERPC_ALL   cpusubtype
-- mach_header | ------------------------------------
--             | 0x00000002  MH_EXECUTE                filetype
--             | ------------------------------------
--             | 0x0000000b  10 load commands          ncmds
--             | ------------------------------------
--             | 0x00000574  1396 bytes                sizeofcmds
--             | ------------------------------------
--             | 0x00000085  DYLDLINK TWOLEVEL         flags
--             --------------------------------------
--               Load commands
--             ---------------------------------------
--               Data
--             ---------------------------------------
--
--               < x86 executable >
--
-- 1. https://github.com/aidansteele/osx-abi-macho-file-format-reference
-- 2. https://github.com/apple-oss-distributions/xnu/blob/xnu-10002.1.13/EXTERNAL_HEADERS/mach-o/nlist.h
-- 3. https://github.com/apple-oss-distributions/xnu/blob/xnu-10002.1.13/EXTERNAL_HEADERS/mach-o/fat.h
-- 4. https://developer.apple.com/documentation/apple-silicon/addressing-architectural-differences-in-your-macos-code
-- 5. https://reverseengineering.stackexchange.com/a/6357/46029
-- 6. http://formats.kaitai.io/mach_o/index.html
--
-- Using the same declarations as defined in <src/jit/bcsave.lua>.
ffi.cdef[[
typedef struct
{
  uint32_t magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags;
} mach_header;

typedef struct
{
  mach_header; uint32_t reserved;
} mach_header_64;

typedef struct {
  uint32_t cmd, cmdsize;
  char segname[16];
  uint32_t vmaddr, vmsize, fileoff, filesize;
  uint32_t maxprot, initprot, nsects, flags;
} mach_segment_command;

typedef struct {
  uint32_t cmd, cmdsize;
  char segname[16];
  uint64_t vmaddr, vmsize, fileoff, filesize;
  uint32_t maxprot, initprot, nsects, flags;
} mach_segment_command_64;

typedef struct {
  char sectname[16], segname[16];
  uint32_t addr, size;
  uint32_t offset, align, reloff, nreloc, flags;
  uint32_t reserved1, reserved2;
} mach_section;

typedef struct {
  char sectname[16], segname[16];
  uint64_t addr, size;
  uint32_t offset, align, reloff, nreloc, flags;
  uint32_t reserved1, reserved2, reserved3;
} mach_section_64;

typedef struct {
  uint32_t cmd, cmdsize, symoff, nsyms, stroff, strsize;
} mach_symtab_command;

typedef struct {
  int32_t strx;
  uint8_t type, sect;
  int16_t desc;
  uint32_t value;
} mach_nlist;

typedef struct {
  int32_t strx;
  uint8_t type, sect;
  uint16_t desc;
  uint64_t value;
} mach_nlist_64;

typedef struct
{
  int32_t magic, nfat_arch;
} mach_fat_header;

typedef struct
{
  int32_t cputype, cpusubtype, offset, size, align;
} mach_fat_arch;

typedef struct {
  mach_fat_header fat;
  mach_fat_arch fat_arch[2];
  struct {
    mach_header hdr;
    mach_segment_command seg;
    mach_section sec;
    mach_symtab_command sym;
  } arch[2];
  mach_nlist sym_entry;
  uint8_t space[4096];
} mach_fat_obj;

typedef struct {
  mach_fat_header fat;
  mach_fat_arch fat_arch[2];
  struct {
    mach_header_64 hdr;
    mach_segment_command_64 seg;
    mach_section_64 sec;
    mach_symtab_command sym;
  } arch[2];
  mach_nlist_64 sym_entry;
  uint8_t space[4096];
} mach_fat_obj_64;
]]

local function create_obj_file(name, arch)
  local mach_o_path = os.tmpname() .. '.o'
  local lua_path = os.getenv('LUA_PATH')
  local lua_bin = utils.exec.luacmd(arg):match('%S+')
  local cmd = ('LUA_PATH="%s" %s -b -n "%s" -o osx -a %s -e "print()" %s'):
              format(lua_path, lua_bin, name, arch, mach_o_path)
  local ret = os.execute(cmd)
  assert(ret == 0, 'cannot create an object file')
  return mach_o_path
end

-- Parses a buffer in the Mach-O format and returns the FAT magic
-- number and `nfat_arch`.
local function read_mach_o(buf, hw_arch)
  local res = {
    header = {
      magic = 0,
      nfat_arch = 0,
    },
    fat_arch = {},
  }

  local is64 = hw_arch == 'arm64'

  -- Mach-O FAT object.
  local mach_fat_obj_type = ffi.typeof(is64 and
                                       'mach_fat_obj_64 *' or
                                       'mach_fat_obj *')
  local obj = ffi.cast(mach_fat_obj_type, buf)

  -- Mach-O FAT object header.
  local mach_fat_header = obj.fat
  -- Mach-O FAT is BE, target arch is LE.
  local be32 = bit.bswap
  res.header.magic = be32(mach_fat_header.magic)
  res.header.nfat_arch = be32(mach_fat_header.nfat_arch)

  -- Mach-O FAT object arches.
  for i = 0, res.header.nfat_arch - 1 do
    local fat_arch = obj.fat_arch[i]
    local arch = {
      cputype = be32(fat_arch.cputype),
      cpusubtype = be32(fat_arch.cpusubtype),
    }
    table.insert(res.fat_arch, arch)
  end

  return res
end

-- Universal Binary can contain executables for more than one
-- CPU architecture. For simplicity, the test compares the *sum*
-- of CPU types and CPU subtypes.
--
-- <src/jit/bcsave.lua:bcsave_machobj> has the definitions of the
-- numbers below. The original XNU source code may be found in
-- <osfmk/mach/machine.h> [1].
--
-- 1. https://opensource.apple.com/source/xnu/xnu-4570.41.2/osfmk/mach/machine.h.auto.html
--
local SUM_CPUTYPE = {
  -- x86 + arm.
  arm = 7 + 12,
  -- x64 + arm64.
  arm64 = 0x01000007 + 0x0100000c,
}
local SUM_CPUSUBTYPE = {
  -- x86 + arm.
  arm = 3 + 9,
  -- x64 + arm64.
  arm64 = 3 + 0,
}

-- The function builds Mach-O FAT object file and retrieves
-- its header fields (magic and nfat_arch) and fields of each arch
-- (cputype, cpusubtype).
--
-- The Mach-O FAT object header can be retrieved with `otool` on
-- macOS:
--
-- $ otool -f empty.o
-- Fat headers
-- fat_magic 0xcafebabe
-- nfat_arch 2
-- <snipped>
--
-- CPU type and subtype can be retrieved with `lipo` on macOS:
--
-- $ luajit -b -o osx -a arm empty.lua empty.o
-- $ lipo -archs empty.o
-- i386 armv7
-- $ luajit -b -o osx -a arm64 empty.lua empty.o
-- $ lipo -archs empty.o
-- x86_64 arm64
local function build_and_check_mach_o(subtest)
  local hw_arch = subtest.name
  assert(hw_arch == 'arm' or hw_arch == 'arm64')

  subtest:plan(4)
  -- FAT_MAGIC is an integer containing the value 0xCAFEBABE in
  -- big-endian byte order format. On a big-endian host CPU,
  -- this can be validated using the constant FAT_MAGIC;
  -- on a little-endian host CPU, it can be validated using
  -- the constant FAT_CIGAM.
  --
  -- FAT_NARCH is an integer specifying the number of fat_arch
  -- data structures that follow. This is the number of
  -- architectures contained in this binary.
  --
  -- See the aforementioned "OS X ABI Mach-O File Format
  -- Reference".
  local FAT_MAGIC = '0xffffffffcafebabe'
  local FAT_NARCH = 2

  local MODULE_NAME = 'lango_team'

  local mach_o_obj_path = create_obj_file(MODULE_NAME, hw_arch)
  local mach_o_buf = utils.tools.read_file(mach_o_obj_path)
  assert(mach_o_buf ~= nil and #mach_o_buf ~= 0, 'cannot read an object file')

  local mach_o = read_mach_o(mach_o_buf, hw_arch)

  -- Teardown.
  assert(os.remove(mach_o_obj_path), 'remove an object file')

  local magic_str = string.format('%#x', mach_o.header.magic)
  subtest:is(magic_str, FAT_MAGIC,
             'fat_magic is correct in Mach-O')
  subtest:is(mach_o.header.nfat_arch, FAT_NARCH,
             'nfat_arch is correct in Mach-O')

  local total_cputype = 0
  local total_cpusubtype = 0
  for i = 1, FAT_NARCH do
    total_cputype = total_cputype + mach_o.fat_arch[i].cputype
    total_cpusubtype = total_cpusubtype + mach_o.fat_arch[i].cpusubtype
  end
  subtest:is(total_cputype, SUM_CPUTYPE[hw_arch],
             'cputype is correct in Mach-O')
  subtest:is(total_cpusubtype, SUM_CPUSUBTYPE[hw_arch],
             'cpusubtype is correct in Mach-O')
end

test:test('arm', build_and_check_mach_o)
test:test('arm64', build_and_check_mach_o)

test:done(true)
