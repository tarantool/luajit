/*
** Implementation of memory profiler.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#define lj_memprof_c
#define LUA_CORE

#define _GNU_SOURCE

#include <errno.h>

#include "lj_arch.h"
#include "lj_jit.h"
#include "lj_memprof.h"

#if LJ_HASMEMPROF

#include "lj_obj.h"
#include "lj_frame.h"
#include "lj_debug.h"

#if LJ_HASRESOLVER
#include <elf.h>
#include <link.h>
#include <stdio.h>
#include <sys/auxv.h>
#include "lj_gc.h"
#endif

#if LJ_HASJIT
#include "lj_dispatch.h"
#endif

/* --------------------------------- Symtab --------------------------------- */

static const unsigned char ljs_header[] = {'l', 'j', 's', LJS_CURRENT_VERSION,
					   0x0, 0x0, 0x0};

#if LJ_HASJIT

static void dump_symtab_trace(struct lj_wbuf *out, const GCtrace *trace)
{
  GCproto *pt = &gcref(trace->startpt)->pt;
  BCLine lineno = 0;

  const BCIns *startpc = mref(trace->startpc, const BCIns);
  lua_assert(startpc >= proto_bc(pt) &&
             startpc < proto_bc(pt) + pt->sizebc);

  lineno = lj_debug_line(pt, proto_bcpos(pt, startpc));

  lj_wbuf_addu64(out, (uint64_t)trace->traceno);
  /*
  ** The information about the prototype, associated with the
  ** trace's start has already been dumped, as it is anchored
  ** via the trace and is not collected while the trace is alive.
  ** For this reason, we do not need to repeat dumping the chunk
  ** name for the prototype.
  */
  lj_wbuf_addu64(out, (uintptr_t)pt);
  lj_wbuf_addu64(out, (uint64_t)lineno);
}

#else

static void dump_symtab_trace(struct lj_wbuf *out, const GCtrace *trace)
{
  UNUSED(out);
  UNUSED(trace);
  lua_assert(0);
}

#endif

static void dump_symtab_proto(struct lj_wbuf *out, const GCproto *pt)
{
  lj_wbuf_addu64(out, (uintptr_t)pt);
  lj_wbuf_addstring(out, proto_chunknamestr(pt));
  lj_wbuf_addu64(out, (uint64_t)pt->firstline);
}

#if LJ_HASRESOLVER

struct ghashtab_header {
  uint32_t nbuckets;
  uint32_t symoffset;
  uint32_t bloom_size;
  uint32_t bloom_shift;
};

static uint32_t ghashtab_size(ElfW(Addr) ghashtab)
{
  /*
  ** There is no easy way to get count of symbols in GNU hashtable, so the
  ** only way to do this is to take highest possible non-empty bucket and
  ** iterate through its symbols until the last chain is over.
  */
  uint32_t last_entry = 0;

  const uint32_t *chain = NULL;
  struct ghashtab_header *header = (struct ghashtab_header *)ghashtab;
  /*
  ** sizeof(size_t) returns 8, if compiled with 64-bit compiler, and 4 if
  ** compiled with 32-bit compiler. It is the best option to determine which
  ** kind of CPU we are running on.
  */
  const char *buckets = (char *)ghashtab + sizeof(struct ghashtab_header) +
                        sizeof(size_t) * header->bloom_size;

  uint32_t *cur_bucket = (uint32_t *)buckets;
  uint32_t i;
  for (i = 0; i < header->nbuckets; ++i) {
    if (last_entry < *cur_bucket)
      last_entry = *cur_bucket;
    cur_bucket++;
  }

  if (last_entry < header->symoffset)
    return header->symoffset;

  chain = (uint32_t *)(buckets + sizeof(uint32_t) * header->nbuckets);
  /* The chain ends with the lowest bit set to 1. */
  while (!(chain[last_entry - header->symoffset] & 1))
    last_entry++;

  return ++last_entry;
}

static void write_c_symtab(ElfW(Sym *) sym, char *strtab, ElfW(Addr) so_addr,
			   size_t sym_cnt, const uint8_t header,
			   struct lj_wbuf *buf)
{
  /*
  ** Index 0 in ELF symtab is used to represent undefined symbols. Hence, we
  ** can just start with index 1.
  **
  ** For more information, see:
  ** https://docs.oracle.com/cd/E23824_01/html/819-0690/chapter6-79797.html
  */

  ElfW(Word) sym_index;
  for (sym_index = 1; sym_index < sym_cnt; sym_index++) {
    /*
    ** ELF32_ST_TYPE and ELF64_ST_TYPE are the same, so we can use
    ** ELF32_ST_TYPE for both 64-bit and 32-bit ELFs.
    **
    ** For more, see https://github.com/torvalds/linux/blob/9137eda53752ef73148e42b0d7640a00f1bc96b1/include/uapi/linux/elf.h#L135
    */
    if (ELF32_ST_TYPE(sym[sym_index].st_info) == STT_FUNC &&
        sym[sym_index].st_name != 0) {
      char *sym_name = &strtab[sym[sym_index].st_name];
      lj_wbuf_addbyte(buf, header);
      lj_wbuf_addu64(buf, sym[sym_index].st_value + so_addr);
      lj_wbuf_addstring(buf, sym_name);
    }
  }
}

static int dump_sht_symtab(const char *elf_name, struct lj_wbuf *buf,
			   lua_State *L, const uint8_t header,
			   const ElfW(Addr) so_addr)
{
  int status = 0;

  char *strtab = NULL;
  ElfW(Shdr *) section_headers = NULL;
  ElfW(Sym *) sym = NULL;
  ElfW(Ehdr) elf_header = {};

  ElfW(Off) sym_off = 0;
  ElfW(Off) strtab_off = 0;

  size_t sym_cnt = 0;
  size_t strtab_size = 0;
  size_t header_index = 0;

  size_t shoff = 0; /* Section headers offset. */
  size_t shnum = 0; /* Section headers number. */
  size_t shentsize = 0; /* Section header entry size. */

  FILE *elf_file = fopen(elf_name, "rb");

  if (elf_file == NULL)
    return -1;

  if (fread(&elf_header, sizeof(elf_header), 1, elf_file) != sizeof(elf_header)
      && ferror(elf_file) != 0)
    goto error;
  if (memcmp(elf_header.e_ident, ELFMAG, SELFMAG) != 0)
    /* Not a valid ELF file. */
    goto error;

  shoff = elf_header.e_shoff;
  shnum = elf_header.e_shnum;
  shentsize = elf_header.e_shentsize;

  if (shoff == 0 || shnum == 0 || shentsize == 0)
    /* No sections in ELF. */
    goto error;

  /*
  ** Memory occupied by section headers is unlikely to be more than 160B, but
  ** 32-bit and 64-bit ELF files may have sections of different sizes and some
  ** of the sections may duiplicate, so we need to take that into account.
  */
  section_headers = lj_mem_new(L, shnum * shentsize);
  if (section_headers == NULL)
    goto error;

  if (fseek(elf_file, shoff, SEEK_SET) != 0)
    goto error;

  if (fread(section_headers, shentsize, shnum, elf_file) != shentsize * shnum
      && ferror(elf_file) != 0)
    goto error;

  for (header_index = 0; header_index < shnum; ++header_index) {
    if (section_headers[header_index].sh_type == SHT_SYMTAB) {
      ElfW(Shdr) sym_hdr = section_headers[header_index];
      ElfW(Shdr) strtab_hdr = section_headers[sym_hdr.sh_link];
      size_t symtab_size = sym_hdr.sh_size;

      sym_off = sym_hdr.sh_offset;
      sym_cnt = symtab_size / sym_hdr.sh_entsize;

      strtab_off = strtab_hdr.sh_offset;
      strtab_size = strtab_hdr.sh_size;
      break;
    }
  }

  if (sym_off == 0 || strtab_off == 0 || sym_cnt == 0)
    goto error;

  /* Load symtab into memory. */
  sym = lj_mem_new(L, sym_cnt * sizeof(ElfW(Sym)));
  if (sym == NULL)
    goto error;
  if (fseek(elf_file, sym_off, SEEK_SET) != 0)
    goto error;
  if (fread(sym, sizeof(ElfW(Sym)), sym_cnt, elf_file) !=
      sizeof(ElfW(Sym)) * sym_cnt && ferror(elf_file) != 0)
    goto error;


  /* Load strtab into memory. */
  strtab = lj_mem_new(L, strtab_size * sizeof(char));
  if (strtab == NULL)
    goto error;
  if (fseek(elf_file, strtab_off, SEEK_SET) != 0)
    goto error;
  if (fread(strtab, sizeof(char), strtab_size, elf_file) !=
      sizeof(char) * strtab_size && ferror(elf_file) != 0)
    goto error;

  write_c_symtab(sym, strtab, so_addr, sym_cnt, header, buf);

  goto end;

error:
  status = -1;

end:
  if (sym != NULL)
    lj_mem_free(G(L), sym, sym_cnt * sizeof(ElfW(Sym)));
  if(strtab != NULL)
    lj_mem_free(G(L), strtab, strtab_size * sizeof(char));
  if(section_headers != NULL)
    lj_mem_free(G(L), section_headers, shnum * shentsize);

  fclose(elf_file);

  return status;
}

static int dump_dyn_symtab(struct dl_phdr_info *info, const uint8_t header,
			   struct lj_wbuf *buf)
{
  size_t header_index;
  for (header_index = 0; header_index < info->dlpi_phnum; ++header_index) {
    if (info->dlpi_phdr[header_index].p_type == PT_DYNAMIC) {
      ElfW(Dyn *) dyn =
	(ElfW(Dyn) *)(info->dlpi_addr + info->dlpi_phdr[header_index].p_vaddr);
      ElfW(Sym *) sym = NULL;
      ElfW(Word *) hashtab = NULL;
      ElfW(Addr) ghashtab = 0;
      ElfW(Word) sym_cnt = 0;

      char *strtab = 0;

      for(; dyn->d_tag != DT_NULL; dyn++) {
        switch(dyn->d_tag) {
        case DT_HASH:
          hashtab = (ElfW(Word *))dyn->d_un.d_ptr;
          break;
        case DT_GNU_HASH:
          ghashtab = dyn->d_un.d_ptr;
          break;
        case DT_STRTAB:
          strtab = (char *)dyn->d_un.d_ptr;
          break;
        case DT_SYMTAB:
          sym = (ElfW(Sym *))dyn->d_un.d_ptr;
          break;
        default:
          break;
        }
      }

      if ((hashtab == NULL && ghashtab == 0) || strtab == NULL || sym == NULL)
        /* Not enough data to resolve symbols. */
        return 1;

      /*
      ** A hash table consists of Elf32_Word or Elf64_Word objects that provide
      ** for symbol table access. Hash table has the following organization:
      ** +-------------------+
      ** |      nbucket      |
      ** +-------------------+
      ** |      nchain       |
      ** +-------------------+
      ** |     bucket[0]     |
      ** |       ...         |
      ** | bucket[nbucket-1] |
      ** +-------------------+
      ** |     chain[0]      |
      ** |       ...         |
      ** |  chain[nchain-1]  |
      ** +-------------------+
      ** Chain table entries parallel the symbol table. The number of symbol
      ** table entries should equal nchain, so symbol table indexes also select
      ** chain table entries. Since the chain array values are indexes for not
      ** only the chain array itself, but also for the symbol table, the chain
      ** array must be the same size as the symbol table. This makes nchain
      ** equal to the length of the symbol table.
      **
      ** For more, see https://docs.oracle.com/cd/E23824_01/html/819-0690/chapter6-48031.html
      */
      sym_cnt = ghashtab == 0 ? hashtab[1] : ghashtab_size(ghashtab);
      write_c_symtab(sym, strtab, info->dlpi_addr, sym_cnt, header, buf);
      return 0;
    }
  }

  return 1;
}

struct symbol_resolver_conf {
  struct lj_wbuf *buf; /* Output buffer. */
  lua_State *L; /* Current Lua state. */
  const uint8_t header; /* Header for symbol entries to write. */

  uint32_t cur_lib; /* Index of the lib currently dumped. */
  uint32_t to_dump_cnt; /* Amount of libs to dump. */
  uint32_t *lib_adds; /* Memprof's counter of libs. */
};

static int resolve_symbolnames(struct dl_phdr_info *info, size_t info_size,
			       void *data)
{
  struct symbol_resolver_conf *conf = data;
  struct lj_wbuf *buf = conf->buf;
  lua_State *L = conf->L;
  const uint8_t header = conf->header;

  uint32_t lib_cnt = 0;

  /*
  ** Check that dlpi_adds and dlpi_subs fields are available.
  ** Assertion was taken from the GLIBC tests:
  ** https://code.woboq.org/userspace/glibc/elf/tst-dlmodcount.c.html#37
  */
  lua_assert(info_size > offsetof(struct dl_phdr_info, dlpi_subs)
      + sizeof(info->dlpi_subs));

  lib_cnt = info->dlpi_adds - *conf->lib_adds;

  /* Skip vDSO library. */
  if (info->dlpi_addr == getauxval(AT_SYSINFO_EHDR))
    return 0;

  if ((conf->to_dump_cnt = info->dlpi_adds - *conf->lib_adds) == 0)
    /* No new libraries, stop resolver. */
    return 1;

  if (conf->cur_lib < lib_cnt - conf->to_dump_cnt) {
    /* That lib is already dumped, skip it. */
    ++conf->cur_lib;
    return 0;
  }

  if (conf->cur_lib == lib_cnt - conf->to_dump_cnt - 1)
    /* Last library, update memrpof's lib counter. */
    *conf->lib_adds = info->dlpi_adds;

  /*
  ** Main way: try to open ELF and read SHT_SYMTAB, SHT_STRTAB and SHT_HASH
  ** sections from it.
  */
  if (dump_sht_symtab(info->dlpi_name, buf, L, header, info->dlpi_addr) == 0) {
    ++conf->cur_lib;
  }
  /* First fallback: dump functions only from PT_DYNAMIC segment. */
  else if(dump_dyn_symtab(info, header, buf) == 0) {
    ++conf->cur_lib;
  }
  /*
  ** Last resort: dump ELF size and address to show .so name for its functions
  ** in memprof output.
  */
  else {
    lj_wbuf_addbyte(buf, SYMTAB_CFUNC);
    lj_wbuf_addu64(buf, info->dlpi_addr);
    lj_wbuf_addstring(buf, info->dlpi_name);
    ++conf->cur_lib;
  }

  return 0;
}

#endif /* LJ_HASRESOLVER */

static void dump_symtab(struct lj_wbuf *out, const struct global_State *g,
			uint32_t *lib_adds)
{
  const GCRef *iter = &g->gc.root;
  const GCobj *o;
  const size_t ljs_header_len = sizeof(ljs_header) / sizeof(ljs_header[0]);

#if LJ_HASRESOLVER
  struct symbol_resolver_conf conf = {
    .buf = out,
    .L = gco2th(gcref(g->cur_L)),
    .header = SYMTAB_CFUNC,
    .cur_lib = 0,
    .to_dump_cnt = 0,
    .lib_adds = lib_adds
  };
#else
  UNUSED(lib_adds);
#endif

  /* Write prologue. */
  lj_wbuf_addn(out, ljs_header, ljs_header_len);

  while ((o = gcref(*iter)) != NULL) {
    switch (o->gch.gct) {
    case (~LJ_TPROTO): {
      const GCproto *pt = gco2pt(o);
      lj_wbuf_addbyte(out, SYMTAB_LFUNC);
      dump_symtab_proto(out, pt);
      break;
    }
    case (~LJ_TTRACE): {
      lj_wbuf_addbyte(out, SYMTAB_TRACE);
      dump_symtab_trace(out, gco2trace(o));
      break;
    }
    default:
      break;
    }
    iter = &o->gch.nextgc;
  }

#if LJ_HASRESOLVER
  /* Write C symbols. */
  dl_iterate_phdr(resolve_symbolnames, &conf);
#endif
  lj_wbuf_addbyte(out, SYMTAB_FINAL);
}

/* ---------------------------- Memory profiler ----------------------------- */

enum memprof_state {
  /* Memory profiler is not running. */
  MPS_IDLE,
  /* Memory profiler is running. */
  MPS_PROFILE,
  /*
  ** Stopped in case of stopped stream.
  ** Saved errno is returned to user at lj_memprof_stop.
  */
  MPS_HALT
};

struct alloc {
  lua_Alloc allocf; /* Allocating function. */
  void *state; /* Opaque allocator's state. */
};

struct memprof {
  global_State *g; /* Profiled VM. */
  enum memprof_state state; /* Internal state. */
  struct lj_wbuf out; /* Output accumulator. */
  struct alloc orig_alloc; /* Original allocator. */
  struct lj_memprof_options opt; /* Profiling options. */
  int saved_errno; /* Saved errno when profiler deinstrumented. */
  uint32_t lib_adds; /* Number of libs loaded. Monotonic. */
};

static struct memprof memprof = {0};

const unsigned char ljm_header[] = {'l', 'j', 'm', LJM_CURRENT_FORMAT_VERSION,
				    0x0, 0x0, 0x0};

static void memprof_write_lfunc(struct lj_wbuf *out, uint8_t aevent,
				GCfunc *fn, struct lua_State *L,
				cTValue *nextframe)
{
  /*
  ** Line equals to zero when LuaJIT is built with the
  ** -DLUAJIT_DISABLE_DEBUGINFO flag.
  */
  const BCLine line = lj_debug_frameline(L, fn, nextframe);

  if (line < 0) {
    /*
    ** Line is >= 0 if we are inside a Lua function.
    ** There are cases when the memory profiler attempts
    ** to attribute allocations triggered by JIT engine recording
    ** phase with a Lua function to be recorded. It this case,
    ** lj_debug_frameline() may return BC_NOPOS (i.e. a negative value).
    ** We report such allocations as internal in order not to confuse users.
    */
    lj_wbuf_addbyte(out, aevent | ASOURCE_INT);
  } else {
    /*
    ** As a prototype is a source of an allocation, it has
    ** already been inserted into the symtab: on the start
    ** of the profiling or right after its creation.
    */
    lj_wbuf_addbyte(out, aevent | ASOURCE_LFUNC);
    lj_wbuf_addu64(out, (uintptr_t)funcproto(fn));
    lj_wbuf_addu64(out, (uint64_t)line);
  }
}

static void memprof_write_cfunc(struct lj_wbuf *out, uint8_t aevent,
				const GCfunc *fn, lua_State *L,
				uint32_t *lib_adds)
{
#if LJ_HASRESOLVER
  /* Check if there are any new libs. */
  struct symbol_resolver_conf conf = {
    .buf = out,
    .L = L,
    .header = AEVENT_SYMTAB | ASOURCE_CFUNC,
    .cur_lib = 0,
    .to_dump_cnt = 0,
    .lib_adds = lib_adds
  };

  /*
  ** XXX: Leaving the `vmstate` unchanged leads to an infinite
  ** recursion, because allocations inside ELF parser are treated
  ** as C-side allocations by memrpof. Setting the `vmstate` to
  ** LJ_VMST_INTERP solves the issue.
  */
  global_State *g = G(L);
  const uint32_t ostate = g->vmstate;
  g->vmstate = ~LJ_VMST_INTERP;

  dl_iterate_phdr(resolve_symbolnames, &conf);

  /* Restore vmstate. */
  g->vmstate = ostate;
#else
  UNUSED(lib_adds);
#endif

  lj_wbuf_addbyte(out, aevent | ASOURCE_CFUNC);
  lj_wbuf_addu64(out, (uintptr_t)fn->c.f);
}

static void memprof_write_ffunc(struct lj_wbuf *out, uint8_t aevent,
				GCfunc *fn, struct lua_State *L,
				cTValue *frame, uint32_t *lib_adds)
{
  cTValue *pframe = frame_prev(frame);
  GCfunc *pfn = frame_func(pframe);

  /*
  ** XXX: If a fast function is called by a Lua function, report the
  ** Lua function for more meaningful output. Otherwise report the fast
  ** function as a C function.
  */
  if (pfn != NULL && isluafunc(pfn))
    memprof_write_lfunc(out, aevent, pfn, L, frame);
  else
    memprof_write_cfunc(out, aevent, fn, L, lib_adds);
}

static void memprof_write_func(struct memprof *mp, uint8_t aevent)
{
  struct lj_wbuf *out = &mp->out;
  lua_State *L = gco2th(gcref(mp->g->mem_L));
  cTValue *frame = L->base - 1;
  GCfunc *fn = frame_func(frame);

  if (isluafunc(fn))
    memprof_write_lfunc(out, aevent, fn, L, NULL);
  else if (isffunc(fn))
    memprof_write_ffunc(out, aevent, fn, L, frame, &mp->lib_adds);
  else if (iscfunc(fn))
    memprof_write_cfunc(out, aevent, fn, L, &mp->lib_adds);
  else
    lua_assert(0);
}

#if LJ_HASJIT

static void memprof_write_trace(struct memprof *mp, uint8_t aevent)
{
  struct lj_wbuf *out = &mp->out;
  const global_State *g = mp->g;
  const TraceNo traceno = g->vmstate;
  lj_wbuf_addbyte(out, aevent | ASOURCE_TRACE);
  lj_wbuf_addu64(out, (uint64_t)traceno);
}

#else

static void memprof_write_trace(struct memprof *mp, uint8_t aevent)
{
  UNUSED(mp);
  UNUSED(aevent);
  lua_assert(0);
}

#endif

static void memprof_write_hvmstate(struct memprof *mp, uint8_t aevent)
{
  lj_wbuf_addbyte(&mp->out, aevent | ASOURCE_INT);
}

typedef void (*memprof_writer)(struct memprof *mp, uint8_t aevent);

static const memprof_writer memprof_writers[] = {
  memprof_write_hvmstate, /* LJ_VMST_INTERP */
  memprof_write_func, /* LJ_VMST_LFUNC */
  memprof_write_func, /* LJ_VMST_FFUNC */
  memprof_write_func, /* LJ_VMST_CFUNC */
  memprof_write_hvmstate, /* LJ_VMST_GC */
  memprof_write_hvmstate, /* LJ_VMST_EXIT */
  memprof_write_hvmstate, /* LJ_VMST_RECORD */
  memprof_write_hvmstate, /* LJ_VMST_OPT */
  memprof_write_hvmstate, /* LJ_VMST_ASM */
  /*
  ** XXX: In ideal world, we should report allocations from traces as well.
  ** But since traces must follow the semantics of the original code,
  ** behaviour of Lua and JITted code must match 1:1 in terms of allocations,
  ** which makes using memprof with enabled JIT virtually redundant.
  ** But if one wants to investigate allocations with JIT enabled,
  ** memprof_write_trace() dumps trace number and mcode starting address
  ** to the binary output. It can be useful to compare with with jit.v or
  ** jit.dump outputs.
  */
  memprof_write_trace /* LJ_VMST_TRACE */
};

static void memprof_write_caller(struct memprof *mp, uint8_t aevent)
{
  const global_State *g = mp->g;
  const uint32_t _vmstate = (uint32_t)~g->vmstate;
  const uint32_t vmstate = _vmstate < LJ_VMST_TRACE ? _vmstate : LJ_VMST_TRACE;

  memprof_writers[vmstate](mp, aevent);
}

static void *memprof_allocf(void *ud, void *ptr, size_t osize, size_t nsize)
{
  struct memprof *mp = &memprof;
  const struct alloc *oalloc = &mp->orig_alloc;
  struct lj_wbuf *out = &mp->out;
  void *nptr;

  lua_assert(MPS_PROFILE == mp->state);
  lua_assert(oalloc->allocf != memprof_allocf);
  lua_assert(oalloc->allocf != NULL);
  lua_assert(ud == oalloc->state);

  nptr = oalloc->allocf(ud, ptr, osize, nsize);

  if (nsize == 0) {
    memprof_write_caller(mp, AEVENT_FREE);
    lj_wbuf_addu64(out, (uintptr_t)ptr);
    lj_wbuf_addu64(out, (uint64_t)osize);
  } else if (ptr == NULL) {
    memprof_write_caller(mp, AEVENT_ALLOC);
    lj_wbuf_addu64(out, (uintptr_t)nptr);
    lj_wbuf_addu64(out, (uint64_t)nsize);
  } else {
    memprof_write_caller(mp, AEVENT_REALLOC);
    lj_wbuf_addu64(out, (uintptr_t)ptr);
    lj_wbuf_addu64(out, (uint64_t)osize);
    lj_wbuf_addu64(out, (uintptr_t)nptr);
    lj_wbuf_addu64(out, (uint64_t)nsize);
  }

  /* Deinstrument memprof if required. */
  if (LJ_UNLIKELY(lj_wbuf_test_flag(out, STREAM_STOP)))
    lj_memprof_stop(mainthread(mp->g));

  return nptr;
}

int lj_memprof_start(struct lua_State *L, const struct lj_memprof_options *opt)
{
  struct memprof *mp = &memprof;
  struct lj_memprof_options *mp_opt = &mp->opt;
  struct alloc *oalloc = &mp->orig_alloc;
  const size_t ljm_header_len = sizeof(ljm_header) / sizeof(ljm_header[0]);

  lua_assert(opt->writer != NULL);
  lua_assert(opt->on_stop != NULL);
  lua_assert(opt->buf != NULL);
  lua_assert(opt->len != 0);

  if (mp->state != MPS_IDLE) {
    /* Clean up resourses. Ignore possible errors. */
    opt->on_stop(opt->ctx, opt->buf);
    return PROFILE_ERRRUN;
  }

  /* Discard possible old errno. */
  mp->saved_errno = 0;

  /* Init options. */
  memcpy(mp_opt, opt, sizeof(*opt));

  /* Init general fields. */
  mp->g = G(L);
  mp->state = MPS_PROFILE;

  /* Init output. */
  lj_wbuf_init(&mp->out, mp_opt->writer, mp_opt->ctx, mp_opt->buf, mp_opt->len);
  dump_symtab(&mp->out, mp->g, &mp->lib_adds);

  /* Write prologue. */
  lj_wbuf_addn(&mp->out, ljm_header, ljm_header_len);

  if (LJ_UNLIKELY(lj_wbuf_test_flag(&mp->out, STREAM_ERRIO|STREAM_STOP))) {
    /* on_stop call may change errno value. */
    int saved_errno = lj_wbuf_errno(&mp->out);
    /* Ignore possible errors. mp->out.buf may be NULL here. */
    mp_opt->on_stop(mp_opt->ctx, mp->out.buf);
    lj_wbuf_terminate(&mp->out);
    mp->state = MPS_IDLE;
    errno = saved_errno;
    return PROFILE_ERRIO;
  }

  /* Override allocating function. */
  oalloc->allocf = lua_getallocf(L, &oalloc->state);
  lua_assert(oalloc->allocf != NULL);
  lua_assert(oalloc->allocf != memprof_allocf);
  lua_assert(oalloc->state != NULL);
  lua_setallocf(L, memprof_allocf, oalloc->state);

  return PROFILE_SUCCESS;
}

int lj_memprof_stop(struct lua_State *L)
{
  struct memprof *mp = &memprof;
  struct lj_memprof_options *mp_opt = &mp->opt;
  struct alloc *oalloc = &mp->orig_alloc;
  struct lj_wbuf *out = &mp->out;
  int cb_status;

  if (mp->state == MPS_HALT) {
    errno = mp->saved_errno;
    mp->state = MPS_IDLE;
    /* wbuf was terminated before. */
    return PROFILE_ERRIO;
  }

  if (mp->state != MPS_PROFILE)
    return PROFILE_ERRRUN;

  if (mp->g != G(L))
    return PROFILE_ERRUSE;

  mp->state = MPS_IDLE;

  lua_assert(mp->g != NULL);

  lua_assert(memprof_allocf == lua_getallocf(L, NULL));
  lua_assert(oalloc->allocf != NULL);
  lua_assert(oalloc->state != NULL);
  lua_setallocf(L, oalloc->allocf, oalloc->state);

  if (LJ_UNLIKELY(lj_wbuf_test_flag(out, STREAM_STOP))) {
    /* on_stop call may change errno value. */
    int saved_errno = lj_wbuf_errno(out);
    /* Ignore possible errors. out->buf may be NULL here. */
    mp_opt->on_stop(mp_opt->ctx, out->buf);
    errno = saved_errno;
    goto errio;
  }

  lj_wbuf_addbyte(out, LJM_EPILOGUE_HEADER);

  lj_wbuf_flush(out);

  cb_status = mp_opt->on_stop(mp_opt->ctx, out->buf);
  if (LJ_UNLIKELY(lj_wbuf_test_flag(out, STREAM_ERRIO|STREAM_STOP) ||
		  cb_status != 0)) {
    errno = lj_wbuf_errno(out);
    goto errio;
  }

  lj_wbuf_terminate(out);
  return PROFILE_SUCCESS;
errio:
  lj_wbuf_terminate(out);
  return PROFILE_ERRIO;
}

void lj_memprof_add_proto(const struct GCproto *pt)
{
  struct memprof *mp = &memprof;

  if (mp->state != MPS_PROFILE)
    return;

  lj_wbuf_addbyte(&mp->out, AEVENT_SYMTAB | ASOURCE_LFUNC);
  dump_symtab_proto(&mp->out, pt);
}

void lj_memprof_add_trace(const struct GCtrace *tr)
{
  struct memprof *mp = &memprof;

  if (mp->state != MPS_PROFILE)
    return;

  lj_wbuf_addbyte(&mp->out, AEVENT_SYMTAB | ASOURCE_TRACE);
  dump_symtab_trace(&mp->out, tr);
}

#else /* LJ_HASMEMPROF */

int lj_memprof_start(struct lua_State *L, const struct lj_memprof_options *opt)
{
  UNUSED(L);
  /* Clean up resourses. Ignore possible errors. */
  opt->on_stop(opt->ctx, opt->buf);
  return PROFILE_ERRUSE;
}

int lj_memprof_stop(struct lua_State *L)
{
  UNUSED(L);
  return PROFILE_ERRUSE;
}

void lj_memprof_add_proto(const struct GCproto *pt)
{
  UNUSED(pt);
}

void lj_memprof_add_trace(const struct GCtrace *tr)
{
  UNUSED(tr);
}

#endif /* LJ_HASMEMPROF */
