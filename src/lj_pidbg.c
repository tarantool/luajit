/*
** Precise trace debug information.
** Copyright (C) 2005-2017 Mike Pall. See Copyright Notice in luajit.h
*/

#define lj_pidbg_c
#define LUA_CORE

#include "lj_obj.h"

#if LJ_HASJIT && defined(LUAJIT_USE_PIDEBUG)

#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include "lauxlib.h"
#include "lj_gc.h"
#include "lj_debug.h"
#include "lj_frame.h"
#include "lj_ir.h"
#include "lj_trace.h"
#include "lj_pidbg.h"

/*
** The debug information is generated in two steps.
**
** First, while a trace is recorded, the origin of every snapshot is
** remembered. In the line mode a snapshot is taken whenever the source
** line changes, in the bytecode mode - at every bytecode boundary. The
** snapshots themselves are taken by the line profiler machinery, see
** rec_profile_ins() in lj_record.c.
**
** Second, when the trace is saved, the recorded checkpoints are joined
** with the machine code offsets of the snapshots (SnapShot.mcofs) and
** resolved to source lines. The result is kept per trace until the trace
** is flushed.
**
** The checkpoint buffer is transient: it is overwritten by every new
** trace and is not a part of the trace itself. It is thread-local, since
** Tarantool may run several LuaJIT VMs in different threads.
*/

/* Checkpoint: origin of a single snapshot. */
typedef struct PIDbgCkpt {
  GCproto *pt;		/* Prototype active at the snapshot, NULL if unknown. */
  BCPos pos;		/* Bytecode position within the prototype. */
} PIDbgCkpt;

/* A resolved debug entry of a trace. */
typedef struct PIDbgSpan {
  uint32_t mcoff;	/* Offset into the machine code. */
  uint32_t bcpos;	/* Bytecode position within the prototype. */
  uint32_t line;	/* Source line. */
  uint32_t fileidx;	/* Index into the file name table. */
} PIDbgSpan;

/* Resolved debug information of a single trace. */
typedef struct PIDbgTrace {
  MSize nspan;		/* Number of debug entries. */
  MSize nfile;		/* Number of distinct chunk names. */
  PIDbgSpan *span;	/* Array of debug entries, sorted by offset. */
  char **file;		/* Array of distinct chunk names. */
  void *entry;		/* Registered GDB JIT entry, if any. */
} PIDbgTrace;

/* Maximum number of distinct chunk names tracked for a single trace. */
#define PIDBG_MAXFILE		16

static void pidbg_register(lua_State *L, PIDbgTrace *pt, GCtrace *T);
static void pidbg_unregister(global_State *g, PIDbgTrace *pt);

/* Per-thread checkpoint buffer. */
static __thread PIDbgCkpt *pidbg_ckpt;
static __thread MSize pidbg_ckptcap;
static __thread MSize pidbg_ckptn;
static __thread TraceNo pidbg_ckpt_traceno;

/* Shared state, protected by <pidbg_lock>. */
static int pidbg_lock;
static int pidbg_enabled;
static PIDbgTrace **pidbg_traces;
static MSize pidbg_tracescap;
static FILE *pidbg_sidecar;	/* Optional sidecar output. */
static FILE *pidbg_jitdump;	/* Optional jitdump output. */
static uint64_t pidbg_code_index;

static void pidbg_lock_acquire(void)
{
  while (__sync_lock_test_and_set(&pidbg_lock, 1)) {
    /* Just spin; this is a debug facility, not a hot path. */
  }
}

static void pidbg_lock_release(void)
{
  __sync_lock_release(&pidbg_lock);
}

/* Return the chunk name suitable for the debugger, without a prefix. */
static const char *pidbg_chunkname(GCproto *pt)
{
  const char *name = proto_chunknamestr(pt);
  if (*name == '@' || *name == '=')
    return name + 1;
  return "(string)";
}

/* Drop the checkpoint buffer of the current thread. */
static void pidbg_ckpt_reset(void)
{
  if (pidbg_ckpt != NULL)
    memset(pidbg_ckpt, 0, pidbg_ckptcap*sizeof(PIDbgCkpt));
  pidbg_ckptn = 0;
}

/* Ensure the checkpoint buffer can hold at least <n> entries. */
static void pidbg_ckpt_ensure(jit_State *J, MSize n)
{
  if (n > pidbg_ckptcap) {
    MSize cap = pidbg_ckptcap ? pidbg_ckptcap : 64;
    while (cap < n) cap *= 2;
    pidbg_ckpt = (PIDbgCkpt *)lj_mem_realloc(J->L, pidbg_ckpt,
		pidbg_ckptcap*sizeof(PIDbgCkpt), cap*sizeof(PIDbgCkpt));
    memset(pidbg_ckpt + pidbg_ckptcap, 0,
	   (cap - pidbg_ckptcap)*sizeof(PIDbgCkpt));
    pidbg_ckptcap = cap;
  }
}

/* Ensure the per-trace table can be indexed by <need> - 1. */
static void pidbg_traces_ensure(jit_State *J, MSize need)
{
  PIDbgTrace **old;
  MSize oldcap, cap;
  PIDbgTrace **na;
  if (need <= pidbg_tracescap)
    return;
  cap = pidbg_tracescap ? pidbg_tracescap : 64;
  while (cap < need) cap *= 2;
  na = (PIDbgTrace **)lj_mem_newvec(J->L, cap, PIDbgTrace *);
  memset(na, 0, cap*sizeof(PIDbgTrace *));
  pidbg_lock_acquire();
  old = pidbg_traces;
  oldcap = pidbg_tracescap;
  if (oldcap)
    memcpy(na, old, oldcap*sizeof(PIDbgTrace *));
  pidbg_traces = na;
  pidbg_tracescap = cap;
  pidbg_lock_release();
  if (old != NULL)
    lj_mem_freevec(J2G(J), old, oldcap, PIDbgTrace *);
}

/* Remember the origin of the snapshot that has just been added. */
void lj_pidbg_record(jit_State *J, GCproto *pt, const BCIns *pc)
{
  MSize idx;
  if (pidbg_ckptcap == 0 || J->cur.traceno != pidbg_ckpt_traceno) {
    pidbg_ckpt_reset();
    pidbg_ckpt_traceno = J->cur.traceno;
  }
  idx = (MSize)J->cur.nsnap - 1;
  pidbg_ckpt_ensure(J, idx + 1);
  pidbg_ckpt[idx].pt = pt;
  pidbg_ckpt[idx].pos = proto_bcpos(pt, pc);
  if (idx + 1 > pidbg_ckptn)
    pidbg_ckptn = idx + 1;
}

/* Free debug information of a single trace. */
void lj_pidbg_deltrace(jit_State *J, GCtrace *T)
{
  TraceNo tr = T->traceno;
  PIDbgTrace *pt;
  if (!pidbg_enabled || tr == 0 || tr >= pidbg_tracescap)
    return;
  pidbg_lock_acquire();
  pt = pidbg_traces[tr];
  pidbg_traces[tr] = NULL;
  pidbg_lock_release();
  if (pt != NULL) {
    MSize i;
    pidbg_unregister(J2G(J), pt);
    for (i = 0; i < pt->nfile; i++)
      lj_mem_free(J2G(J), pt->file[i], strlen(pt->file[i]) + 1);
    lj_mem_freevec(J2G(J), pt->file, PIDBG_MAXFILE, char *);
    lj_mem_freevec(J2G(J), pt->span, pt->nspan, PIDbgSpan);
    lj_mem_freet(J2G(J), pt);
  }
}

/* Find or add a chunk name to the file table of the trace. */
static uint32_t pidbg_fileidx(jit_State *J, PIDbgTrace *pt, const char *name)
{
  MSize i;
  size_t len;
  char *copy;
  for (i = 0; i < pt->nfile; i++) {
    if (strcmp(pt->file[i], name) == 0)
      return (uint32_t)i;
  }
  if (pt->nfile >= PIDBG_MAXFILE)
    return 0;
  len = strlen(name) + 1;
  copy = (char *)lj_mem_new(J->L, len);
  memcpy(copy, name, len);
  pt->file[pt->nfile] = copy;
  return (uint32_t)pt->nfile++;
}

/* -- In-memory ELF object for the GDB JIT API ---------------------------- */

#if defined(LUAJIT_USE_GDBJIT)
#error "LUAJIT_USE_PIDEBUG and LUAJIT_USE_GDBJIT are mutually exclusive"
#endif

/* GDB JIT actions. */
enum {
  GDBJIT_NOACTION = 0,
  GDBJIT_REGISTER,
  GDBJIT_UNREGISTER
};

/* GDB JIT entry. */
typedef struct PIDbgJitEntry {
  struct PIDbgJitEntry *next_entry;
  struct PIDbgJitEntry *prev_entry;
  const char *symfile_addr;
  uint64_t symfile_size;
} PIDbgJitEntry;

/* GDB JIT descriptor. */
typedef struct PIDbgJitDesc {
  uint32_t version;
  uint32_t action_flag;
  PIDbgJitEntry *relevant_entry;
  PIDbgJitEntry *first_entry;
} PIDbgJitDesc;

PIDbgJitDesc __jit_debug_descriptor = {
  1, GDBJIT_NOACTION, NULL, NULL
};

/* GDB sets a breakpoint at this function. */
void LJ_NOINLINE __jit_debug_register_code(void)
{
  __asm__ __volatile__("");
}

/* ELF definitions. */
typedef struct PIDbgELFheader {
  uint8_t emagic[4];
  uint8_t eclass;
  uint8_t eendian;
  uint8_t eversion;
  uint8_t eosabi;
  uint8_t eabiversion;
  uint8_t epad[7];
  uint16_t type;
  uint16_t machine;
  uint32_t version;
  uintptr_t entry;
  uintptr_t phofs;
  uintptr_t shofs;
  uint32_t flags;
  uint16_t ehsize;
  uint16_t phentsize;
  uint16_t phnum;
  uint16_t shentsize;
  uint16_t shnum;
  uint16_t shstridx;
} PIDbgELFheader;

typedef struct PIDbgELFsectheader {
  uint32_t name;
  uint32_t type;
  uintptr_t flags;
  uintptr_t addr;
  uintptr_t ofs;
  uintptr_t size;
  uint32_t link;
  uint32_t info;
  uintptr_t align;
  uintptr_t entsize;
} PIDbgELFsectheader;

#define PIDBG_ELFSECT_IDX_ABS		0xfff1

enum {
  PIDBG_ELFSECT_TYPE_PROGBITS = 1,
  PIDBG_ELFSECT_TYPE_SYMTAB = 2,
  PIDBG_ELFSECT_TYPE_STRTAB = 3,
  PIDBG_ELFSECT_TYPE_NOBITS = 8
};

#define PIDBG_ELFSECT_FLAGS_WRITE	1
#define PIDBG_ELFSECT_FLAGS_ALLOC	2
#define PIDBG_ELFSECT_FLAGS_EXEC	4

typedef struct PIDbgELFsymbol {
#if LJ_64
  uint32_t name;
  uint8_t info;
  uint8_t other;
  uint16_t sectidx;
  uintptr_t value;
  uint64_t size;
#else
  uint32_t name;
  uintptr_t value;
  uint32_t size;
  uint8_t info;
  uint8_t other;
  uint16_t sectidx;
#endif
} PIDbgELFsymbol;

enum {
  PIDBG_ELFSYM_TYPE_FUNC = 2,
  PIDBG_ELFSYM_TYPE_FILE = 4,
  PIDBG_ELFSYM_BIND_LOCAL = 0 << 4,
  PIDBG_ELFSYM_BIND_GLOBAL = 1 << 4
};

/* DWARF definitions. */
#define PIDBG_DW_CIE_VERSION	1

enum {
  DW_CFA_nop = 0x0,
  DW_CFA_offset_extended = 0x5,
  DW_CFA_def_cfa = 0xc,
  DW_CFA_def_cfa_offset = 0xe,
  DW_CFA_offset_extended_sf = 0x11,
  DW_CFA_advance_loc = 0x40,
  DW_CFA_offset = 0x80
};

enum {
  DW_EH_PE_udata4 = 3,
  DW_EH_PE_textrel = 0x20
};

enum {
  DW_TAG_compile_unit = 0x11
};

enum {
  DW_children_no = 0,
  DW_children_yes = 1
};

enum {
  DW_AT_name = 0x03,
  DW_AT_stmt_list = 0x10,
  DW_AT_low_pc = 0x11,
  DW_AT_high_pc = 0x12
};

enum {
  DW_FORM_addr = 0x01,
  DW_FORM_data4 = 0x06,
  DW_FORM_string = 0x08
};

enum {
  DW_LNS_extended_op = 0,
  DW_LNS_copy = 1,
  DW_LNS_advance_pc = 2,
  DW_LNS_advance_line = 3,
  DW_LNS_set_file = 4
};

enum {
  DW_LNE_end_sequence = 1,
  DW_LNE_set_address = 2
};

enum {
#if LJ_TARGET_X86
  DW_REG_AX, DW_REG_CX, DW_REG_DX, DW_REG_BX,
  DW_REG_SP, DW_REG_BP, DW_REG_SI, DW_REG_DI,
  DW_REG_RA,
#elif LJ_TARGET_X64
  /* Yes, the order is strange, but correct. */
  DW_REG_AX, DW_REG_DX, DW_REG_CX, DW_REG_BX,
  DW_REG_SI, DW_REG_DI, DW_REG_BP, DW_REG_SP,
  DW_REG_8, DW_REG_9, DW_REG_10, DW_REG_11,
  DW_REG_12, DW_REG_13, DW_REG_14, DW_REG_15,
  DW_REG_RA,
#elif LJ_TARGET_ARM
  DW_REG_SP = 13,
  DW_REG_RA = 14,
#elif LJ_TARGET_ARM64
  DW_REG_SP = 31,
  DW_REG_RA = 30,
#elif LJ_TARGET_PPC
  DW_REG_SP = 1,
  DW_REG_RA = 65,
  DW_REG_CR = 70,
#elif LJ_TARGET_MIPS
  DW_REG_SP = 29,
  DW_REG_RA = 31,
#else
#error "Unsupported target architecture"
#endif
};

/* Minimal list of sections for the in-memory ELF object. */
enum {
  PIDBG_SECT_NULL,
  PIDBG_SECT_text,
  PIDBG_SECT_eh_frame,
  PIDBG_SECT_shstrtab,
  PIDBG_SECT_strtab,
  PIDBG_SECT_symtab,
  PIDBG_SECT_debug_info,
  PIDBG_SECT_debug_abbrev,
  PIDBG_SECT_debug_line,
  PIDBG_SECT__MAX
};

enum {
  PIDBG_SYM_UNDEF,
  PIDBG_SYM_FILE,
  PIDBG_SYM_FUNC,
  PIDBG_SYM__MAX
};

/* Template for in-memory ELF header. */
static const PIDbgELFheader pidbg_elfhdr_template = {
  .emagic = { 0x7f, 'E', 'L', 'F' },
  .eclass = LJ_64 ? 2 : 1,
  .eendian = LJ_ENDIAN_SELECT(1, 2),
  .eversion = 1,
#if LJ_TARGET_LINUX
  .eosabi = 0,
#elif defined(__FreeBSD__)
  .eosabi = 9,
#elif defined(__NetBSD__)
  .eosabi = 2,
#elif defined(__OpenBSD__)
  .eosabi = 12,
#elif defined(__DragonFly__)
  .eosabi = 0,
#elif (defined(__sun__) && defined(__svr4__))
  .eosabi = 6,
#else
  .eosabi = 0,
#endif
  .eabiversion = 0,
  .epad = { 0, 0, 0, 0, 0, 0, 0 },
  .type = 1,
#if LJ_TARGET_X86
  .machine = 3,
#elif LJ_TARGET_X64
  .machine = 62,
#elif LJ_TARGET_ARM
  .machine = 40,
#elif LJ_TARGET_ARM64
  .machine = 183,
#elif LJ_TARGET_PPC
  .machine = 20,
#elif LJ_TARGET_MIPS
  .machine = 8,
#else
#error "Unsupported target architecture"
#endif
  .version = 1,
  .entry = 0,
  .phofs = 0,
  .shofs = sizeof(PIDbgELFheader),
  .flags = 0,
  .ehsize = sizeof(PIDbgELFheader),
  .phentsize = 0,
  .phnum = 0,
  .shentsize = sizeof(PIDbgELFsectheader),
  .shnum = PIDBG_SECT__MAX,
  .shstridx = PIDBG_SECT_shstrtab
};

/* Growable byte buffer for building the ELF object. */
typedef struct PIDbgBuf {
  lua_State *L;
  uint8_t *p;
  size_t len;
  size_t cap;
} PIDbgBuf;

static void pb_need(PIDbgBuf *b, size_t n)
{
  if (b->len + n > b->cap) {
    size_t cap = b->cap ? b->cap : 256;
    while (cap < b->len + n) cap *= 2;
    b->p = (uint8_t *)lj_mem_realloc(b->L, b->p, b->cap, cap);
    b->cap = cap;
  }
}

static void pb_mem(PIDbgBuf *b, const void *p, size_t n)
{
  pb_need(b, n);
  memcpy(b->p + b->len, p, n);
  b->len += n;
}

static void pb_u8(PIDbgBuf *b, uint8_t v)
{
  pb_need(b, 1);
  b->p[b->len++] = v;
}

static void pb_u16(PIDbgBuf *b, uint16_t v)
{
  pb_mem(b, &v, sizeof(v));
}

static void pb_u32(PIDbgBuf *b, uint32_t v)
{
  pb_mem(b, &v, sizeof(v));
}

static void pb_addr(PIDbgBuf *b, uintptr_t v)
{
  pb_mem(b, &v, sizeof(v));
}

static void pb_uleb(PIDbgBuf *b, uint64_t v)
{
  do {
    uint8_t x = (uint8_t)(v & 0x7f);
    v >>= 7;
    if (v) x |= 0x80;
    pb_u8(b, x);
  } while (v);
}

static void pb_sleb(PIDbgBuf *b, int64_t v)
{
  for (;;) {
    uint8_t x = (uint8_t)(v & 0x7f);
    int64_t s = v >> 7;
    v = s;
    if ((s == 0 && !(x & 0x40)) || (s == -1 && (x & 0x40))) {
      pb_u8(b, x);
      break;
    }
    pb_u8(b, x | 0x80);
  }
}

static void pb_strz(PIDbgBuf *b, const char *s)
{
  pb_mem(b, s, strlen(s) + 1);
}

static void pb_pad(PIDbgBuf *b, size_t a)
{
  while (b->len & (a - 1))
    pb_u8(b, 0);
}

/* Emit a length-prefixed DWARF sub-section and return its length position. */
static size_t pb_begin(PIDbgBuf *b)
{
  size_t pos = b->len;
  pb_u32(b, 0);
  return pos;
}

static void pb_end(PIDbgBuf *b, size_t pos)
{
  uint32_t len = (uint32_t)(b->len - pos - 4);
  memcpy(b->p + pos, &len, sizeof(len));
}

/* Emit the DWARF line number program for the trace. */
static void pidbg_emit_lineprog(PIDbgBuf *b, PIDbgTrace *pt,
				uintptr_t mcaddr, MSize szmcode)
{
  uintptr_t cur_addr = 0;
  BCLine cur_line = 1;
  uint32_t cur_file = 1;
  int seq_open = 0;
  MSize i;

  for (i = 0; i < pt->nspan; i++) {
    uintptr_t addr = mcaddr + pt->span[i].mcoff;
    uint32_t fidx = pt->span[i].fileidx + 1;
    BCLine line = (BCLine)pt->span[i].line;
    if (!seq_open || addr < cur_addr) {
      if (seq_open) {
	pb_u8(b, DW_LNS_extended_op);
	pb_uleb(b, 1);
	pb_u8(b, DW_LNE_end_sequence);
      }
      pb_u8(b, DW_LNS_extended_op);
      pb_uleb(b, 1 + sizeof(uintptr_t));
      pb_u8(b, DW_LNE_set_address);
      pb_addr(b, addr);
      cur_addr = addr;
      cur_line = 1;
      cur_file = 1;
      seq_open = 1;
    }
    if (fidx != cur_file) {
      pb_u8(b, DW_LNS_set_file);
      pb_uleb(b, fidx);
      cur_file = fidx;
    }
    if (line != cur_line) {
      pb_u8(b, DW_LNS_advance_line);
      pb_sleb(b, (int64_t)line - (int64_t)cur_line);
      cur_line = line;
    }
    if (addr != cur_addr) {
      pb_u8(b, DW_LNS_advance_pc);
      pb_uleb(b, addr - cur_addr);
      cur_addr = addr;
    }
    pb_u8(b, DW_LNS_copy);
  }

  if (seq_open) {
    uintptr_t end = mcaddr + szmcode;
    if (end > cur_addr) {
      pb_u8(b, DW_LNS_advance_pc);
      pb_uleb(b, end - cur_addr);
      cur_addr = end;
    }
    pb_u8(b, DW_LNS_extended_op);
    pb_uleb(b, 1);
    pb_u8(b, DW_LNE_end_sequence);
  }
}

/* Build the in-memory ELF object for a single trace. */
static void pidbg_build_obj(jit_State *J, PIDbgTrace *pt, GCtrace *T,
			    PIDbgBuf *b, size_t *eh_ofs, size_t *eh_sz)
{
  PIDbgELFsectheader sec[PIDBG_SECT__MAX];
  uint32_t nameofs[PIDBG_SECT__MAX];
  uint32_t symname[PIDBG_SYM__MAX];
  PIDbgELFsymbol sym[PIDBG_SYM__MAX];
  size_t sectab = sizeof(PIDbgELFheader);
  const char *cufile;
  GCproto *startpt = &gcref(T->startpt)->pt;
  TraceNo parent = T->ir[REF_BASE].op1;
  MSize spadjp = CFRAME_SIZE_JIT +
		 (MSize)(parent ? traceref(J, parent)->spadjust : 0);
  MSize spadj = CFRAME_SIZE_JIT + T->spadjust;
  MSize i;

  b->L = J->L;
  b->p = NULL;
  b->len = 0;
  b->cap = 0;
  cufile = pidbg_chunkname(startpt);
  memset(sec, 0, sizeof(sec));
  memset(sym, 0, sizeof(sym));

  /* Reserve the ELF header and the section header table. */
  pb_need(b, sectab + PIDBG_SECT__MAX*sizeof(PIDbgELFsectheader));
  memset(b->p, 0, sectab + PIDBG_SECT__MAX*sizeof(PIDbgELFsectheader));
  b->len = sectab + PIDBG_SECT__MAX*sizeof(PIDbgELFsectheader);

  /* Section name string table. */
  sec[PIDBG_SECT_shstrtab].ofs = b->len;
  pb_u8(b, '\0');
  {
    static const char *const names[PIDBG_SECT__MAX] = {
      NULL, ".text", ".eh_frame", ".shstrtab", ".strtab", ".symtab",
      ".debug_info", ".debug_abbrev", ".debug_line"
    };
    for (i = 1; i < PIDBG_SECT__MAX; i++) {
      nameofs[i] = (uint32_t)(b->len - sec[PIDBG_SECT_shstrtab].ofs);
      pb_strz(b, names[i]);
    }
  }
  sec[PIDBG_SECT_shstrtab].size = b->len - sec[PIDBG_SECT_shstrtab].ofs;

  /* Symbol name string table. */
  sec[PIDBG_SECT_strtab].ofs = b->len;
  pb_u8(b, '\0');
  symname[PIDBG_SYM_FILE] = (uint32_t)(b->len - sec[PIDBG_SECT_strtab].ofs);
  pb_strz(b, "JIT mcode");
  symname[PIDBG_SYM_FUNC] = (uint32_t)(b->len - sec[PIDBG_SECT_strtab].ofs);
  pb_strz(b, "TRACE_");
  b->len--;  /* Overwrite the terminator with the trace number. */
  {
    char num[16];
    int n = 0;
    TraceNo tr = T->traceno;
    do { num[n++] = (char)('0' + tr % 10); tr /= 10; } while (tr);
    while (n > 0) pb_u8(b, (uint8_t)num[--n]);
    pb_u8(b, '\0');
  }
  sec[PIDBG_SECT_strtab].size = b->len - sec[PIDBG_SECT_strtab].ofs;

  /* Symbol table. */
  sec[PIDBG_SECT_symtab].ofs = b->len;
  sym[PIDBG_SYM_FILE].name = symname[PIDBG_SYM_FILE];
  sym[PIDBG_SYM_FILE].sectidx = PIDBG_ELFSECT_IDX_ABS;
  sym[PIDBG_SYM_FILE].info = PIDBG_ELFSYM_TYPE_FILE|PIDBG_ELFSYM_BIND_LOCAL;
  sym[PIDBG_SYM_FUNC].name = symname[PIDBG_SYM_FUNC];
  sym[PIDBG_SYM_FUNC].sectidx = PIDBG_SECT_text;
  sym[PIDBG_SYM_FUNC].value = 0;
  sym[PIDBG_SYM_FUNC].size = T->szmcode;
  sym[PIDBG_SYM_FUNC].info = PIDBG_ELFSYM_TYPE_FUNC|PIDBG_ELFSYM_BIND_GLOBAL;
  pb_mem(b, sym, sizeof(sym));
  sec[PIDBG_SECT_symtab].size = sizeof(sym);
  sec[PIDBG_SECT_symtab].link = PIDBG_SECT_strtab;
  sec[PIDBG_SECT_symtab].info = PIDBG_SYM_FUNC;
  sec[PIDBG_SECT_symtab].entsize = sizeof(PIDbgELFsymbol);

  /* .debug_info. */
  sec[PIDBG_SECT_debug_info].ofs = b->len;
  {
    size_t unit = pb_begin(b);
    pb_u16(b, 2);			/* DWARF version. */
    pb_u32(b, 0);			/* Abbrev offset. */
    pb_u8(b, (uint8_t)sizeof(uintptr_t));  /* Pointer size. */
    pb_uleb(b, 1);		/* Abbrev #1: DW_TAG_compile_unit. */
    pb_strz(b, cufile);		/* DW_AT_name. */
    pb_addr(b, (uintptr_t)T->mcode);			/* DW_AT_low_pc. */
    pb_addr(b, (uintptr_t)T->mcode + T->szmcode);	/* DW_AT_high_pc. */
    pb_u32(b, 0);		/* DW_AT_stmt_list. */
    pb_end(b, unit);
  }
  sec[PIDBG_SECT_debug_info].size = b->len - sec[PIDBG_SECT_debug_info].ofs;

  /* .debug_abbrev. */
  sec[PIDBG_SECT_debug_abbrev].ofs = b->len;
  pb_uleb(b, 1); pb_uleb(b, DW_TAG_compile_unit);
  pb_u8(b, DW_children_no);
  pb_uleb(b, DW_AT_name);	pb_uleb(b, DW_FORM_string);
  pb_uleb(b, DW_AT_low_pc);	pb_uleb(b, DW_FORM_addr);
  pb_uleb(b, DW_AT_high_pc);	pb_uleb(b, DW_FORM_addr);
  pb_uleb(b, DW_AT_stmt_list);	pb_uleb(b, DW_FORM_data4);
  pb_u8(b, 0); pb_u8(b, 0);
  sec[PIDBG_SECT_debug_abbrev].size =
    b->len - sec[PIDBG_SECT_debug_abbrev].ofs;

  /* .debug_line. */
  sec[PIDBG_SECT_debug_line].ofs = b->len;
  {
    size_t unit, hdr;
    unit = pb_begin(b);
    pb_u16(b, 2);		/* DWARF version. */
    hdr = pb_begin(b);
    pb_u8(b, 1);		/* Minimum instruction length. */
    pb_u8(b, 1);		/* is_stmt. */
    pb_u8(b, 0);		/* Line base. */
    pb_u8(b, 2);		/* Line range. */
    pb_u8(b, 5);		/* Opcode base. */
    pb_u8(b, 0); pb_u8(b, 1); pb_u8(b, 1); pb_u8(b, 1);  /* Std op lengths. */
    pb_u8(b, 0);		/* Empty directory table. */
    for (i = 0; i < pt->nfile; i++) {  /* File name table. */
      pb_strz(b, pt->file[i]);
      pb_uleb(b, 0); pb_uleb(b, 0); pb_uleb(b, 0);
    }
    pb_u8(b, 0);		/* End of file name table. */
    pb_end(b, hdr);
    pidbg_emit_lineprog(b, pt, (uintptr_t)T->mcode, T->szmcode);
    pb_end(b, unit);
  }
  sec[PIDBG_SECT_debug_line].size = b->len - sec[PIDBG_SECT_debug_line].ofs;

  /* .eh_frame. */
  pb_pad(b, sizeof(uintptr_t));
  sec[PIDBG_SECT_eh_frame].ofs = b->len;
  {
    size_t cie, fde, framep = b->len;
    cie = pb_begin(b);
    pb_u32(b, 0);		/* Offset to CIE itself. */
    pb_u8(b, PIDBG_DW_CIE_VERSION);
    pb_strz(b, "zR");		/* Augmentation. */
    pb_uleb(b, 1);		/* Code alignment factor. */
    pb_sleb(b, -(int64_t)sizeof(uintptr_t));  /* Data alignment factor. */
    pb_u8(b, DW_REG_RA);	/* Return address register. */
    pb_u8(b, 1); pb_u8(b, DW_EH_PE_textrel|DW_EH_PE_udata4);
    pb_u8(b, DW_CFA_def_cfa); pb_uleb(b, DW_REG_SP);
    pb_uleb(b, sizeof(uintptr_t));
#if LJ_TARGET_PPC
    pb_u8(b, DW_CFA_offset_extended_sf); pb_u8(b, DW_REG_RA); pb_sleb(b, -1);
#else
    pb_u8(b, DW_CFA_offset|DW_REG_RA); pb_uleb(b, 1);
#endif
    pb_pad(b, sizeof(uintptr_t));
    pb_end(b, cie);

    fde = pb_begin(b);
    pb_u32(b, (uint32_t)(fde + 4 - framep));  /* Offset to CIE. */
    pb_u32(b, 0);			/* Machine code offset relative to text. */
    pb_u32(b, T->szmcode);		/* Machine code length. */
    pb_u8(b, 0);			/* Augmentation data. */
#if LJ_TARGET_X86
    pb_u8(b, DW_CFA_offset|DW_REG_BP); pb_uleb(b, 2);
    pb_u8(b, DW_CFA_offset|DW_REG_DI); pb_uleb(b, 3);
    pb_u8(b, DW_CFA_offset|DW_REG_SI); pb_uleb(b, 4);
    pb_u8(b, DW_CFA_offset|DW_REG_BX); pb_uleb(b, 5);
#elif LJ_TARGET_X64
    pb_u8(b, DW_CFA_offset|DW_REG_BP); pb_uleb(b, 2);
    pb_u8(b, DW_CFA_offset|DW_REG_BX); pb_uleb(b, 3);
    pb_u8(b, DW_CFA_offset|DW_REG_15); pb_uleb(b, 4);
    pb_u8(b, DW_CFA_offset|DW_REG_14); pb_uleb(b, 5);
    pb_u8(b, DW_CFA_offset|DW_REG_13); pb_uleb(b, LJ_GC64 ? 10 : 9);
    pb_u8(b, DW_CFA_offset|DW_REG_12); pb_uleb(b, LJ_GC64 ? 11 : 10);
#elif LJ_TARGET_ARM
    { int r; for (r = 11; r >= 4; r--) { pb_u8(b, DW_CFA_offset|r); pb_uleb(b, 2+(11-r)); } }
#elif LJ_TARGET_ARM64
    {
      int r;
      pb_u8(b, DW_CFA_offset|31); pb_uleb(b, 2);
      for (r = 28; r >= 19; r--) { pb_u8(b, DW_CFA_offset|r); pb_uleb(b, 3+(28-r)); }
      for (r = 15; r >= 8; r--) { pb_u8(b, DW_CFA_offset|32|r); pb_uleb(b, 28-r); }
    }
#elif LJ_TARGET_PPC
    {
      int r;
      pb_u8(b, DW_CFA_offset_extended); pb_u8(b, DW_REG_CR); pb_uleb(b, 55);
      for (r = 14; r <= 31; r++) {
	pb_u8(b, DW_CFA_offset|r); pb_uleb(b, 37+(31-r));
	pb_u8(b, DW_CFA_offset|32|r); pb_uleb(b, 2+2*(31-r));
      }
    }
#elif LJ_TARGET_MIPS
    {
      int r;
      pb_u8(b, DW_CFA_offset|30); pb_uleb(b, 2);
      for (r = 23; r >= 16; r--) { pb_u8(b, DW_CFA_offset|r); pb_uleb(b, 26-r); }
      for (r = 30; r >= 20; r -= 2) { pb_u8(b, DW_CFA_offset|32|r); pb_uleb(b, 42-r); }
    }
#else
#error "Unsupported target architecture"
#endif
    if (spadjp != spadj) {
      pb_u8(b, DW_CFA_def_cfa_offset); pb_uleb(b, spadjp);
      pb_u8(b, DW_CFA_advance_loc|1);  /* Only an approximation. */
    }
    pb_u8(b, DW_CFA_def_cfa_offset); pb_uleb(b, spadj);
    pb_pad(b, sizeof(uintptr_t));
    pb_end(b, fde);

    sec[PIDBG_SECT_eh_frame].size = b->len - sec[PIDBG_SECT_eh_frame].ofs;
  }

  /* .text is a NOBITS shadow of the machine code. */
  sec[PIDBG_SECT_text].type = PIDBG_ELFSECT_TYPE_NOBITS;
  sec[PIDBG_SECT_text].flags = PIDBG_ELFSECT_FLAGS_ALLOC|PIDBG_ELFSECT_FLAGS_EXEC;
  sec[PIDBG_SECT_text].addr = (uintptr_t)T->mcode;
  sec[PIDBG_SECT_text].ofs = 0;
  sec[PIDBG_SECT_text].size = T->szmcode;

  {
    static const struct {
      uint32_t type;
      uintptr_t flags;
      uintptr_t align;
    } info[PIDBG_SECT__MAX] = {
      { 0, 0, 0 },
      { PIDBG_ELFSECT_TYPE_NOBITS, PIDBG_ELFSECT_FLAGS_ALLOC|PIDBG_ELFSECT_FLAGS_EXEC, 16 },
      { PIDBG_ELFSECT_TYPE_PROGBITS, PIDBG_ELFSECT_FLAGS_ALLOC, sizeof(uintptr_t) },
      { PIDBG_ELFSECT_TYPE_STRTAB, 0, 1 },
      { PIDBG_ELFSECT_TYPE_STRTAB, 0, 1 },
      { PIDBG_ELFSECT_TYPE_SYMTAB, 0, sizeof(uintptr_t) },
      { PIDBG_ELFSECT_TYPE_PROGBITS, 0, 1 },
      { PIDBG_ELFSECT_TYPE_PROGBITS, 0, 1 },
      { PIDBG_ELFSECT_TYPE_PROGBITS, 0, 1 }
    };
    for (i = 1; i < PIDBG_SECT__MAX; i++) {
      sec[i].name = nameofs[i];
      sec[i].type = info[i].type;
      sec[i].flags = info[i].flags;
      sec[i].align = info[i].align;
    }
  }

  /* Write the section header table. */
  memcpy(b->p + sectab, sec, sizeof(sec));

  /* Write the ELF header. */
  {
    PIDbgELFheader hdr = pidbg_elfhdr_template;
    memcpy(b->p, &hdr, sizeof(hdr));
  }

  *eh_ofs = sec[PIDBG_SECT_eh_frame].ofs;
  *eh_sz = sec[PIDBG_SECT_eh_frame].size;
}

/* -- File outputs -------------------------------------------------------- */

/* Write the per-trace debug entries to the optional sidecar file. */
static void pidbg_write_sidecar(PIDbgTrace *pt, GCtrace *T)
{
  MSize i;
  if (pidbg_sidecar == NULL)
    return;
  pidbg_lock_acquire();
  fprintf(pidbg_sidecar, "trace\t%d\t%llu\t%u\n", (int)T->traceno,
	  (unsigned long long)(uintptr_t)T->mcode, (unsigned)T->szmcode);
  for (i = 0; i < pt->nspan; i++) {
    PIDbgSpan *s = &pt->span[i];
    fprintf(pidbg_sidecar, "span\t%d\t%u\t%u\t%u\t%s\n", (int)T->traceno,
	    (unsigned)s->mcoff, (unsigned)s->bcpos, (unsigned)s->line,
	    pt->file[s->fileidx]);
  }
  fprintf(pidbg_sidecar, "end\t%d\n", (int)T->traceno);
  fflush(pidbg_sidecar);
  pidbg_lock_release();
}

/* ELF machine type, matching the in-memory ELF object. */
static uint32_t pidbg_elf_mach(void)
{
#if LJ_TARGET_X86
  return 3;
#elif LJ_TARGET_X64
  return 62;
#elif LJ_TARGET_ARM
  return 40;
#elif LJ_TARGET_ARM64
  return 183;
#elif LJ_TARGET_PPC
  return 20;
#elif LJ_TARGET_MIPS
  return 8;
#else
  return 0;
#endif
}

static void jd_u32(FILE *f, uint32_t v)
{
  fwrite(&v, sizeof(v), 1, f);
}

static void jd_u64(FILE *f, uint64_t v)
{
  fwrite(&v, sizeof(v), 1, f);
}

static void jd_rec(FILE *f, uint32_t id, uint64_t size)
{
  jd_u32(f, id);
  jd_u32(f, (uint32_t)size);
  jd_u64(f, 0);  /* Timestamp: unused. */
}

/* Write the jitdump file header. */
static void pidbg_jitdump_header(FILE *f)
{
  jd_u32(f, 0x4a695444);	/* "JiTD". */
  jd_u32(f, 1);			/* Version. */
  jd_u32(f, 40);		/* Header size. */
  jd_u32(f, pidbg_elf_mach());
  jd_u32(f, 0);			/* Reserved. */
  jd_u32(f, (uint32_t)getpid());
  jd_u64(f, 0);			/* Timestamp. */
  jd_u64(f, 0);			/* Flags. */
}

/* Write the jitdump records of a single trace. */
static void pidbg_write_jitdump(PIDbgTrace *pt, GCtrace *T, PIDbgBuf *b,
				size_t eh_ofs, size_t eh_sz)
{
  static const uint8_t eh_hdr[4] = { 1, 0xff, 0xff, 0xff };
  uint64_t code_addr = (uintptr_t)T->mcode;
  uint64_t code_size = T->szmcode;
  uint64_t code_index;
  uint32_t pid = (uint32_t)getpid();
  char name[32];
  int nlen;
  size_t size;
  MSize i;
  if (pidbg_jitdump == NULL)
    return;
  nlen = snprintf(name, sizeof(name), "TRACE_%d", (int)T->traceno);

  pidbg_lock_acquire();
  code_index = ++pidbg_code_index;

  /* JIT_CODE_DEBUG_INFO: must precede the matching JIT_CODE_LOAD. */
  size = 16 + 8 + 8;
  for (i = 0; i < pt->nspan; i++)
    size += 8 + 4 + 4 + strlen(pt->file[pt->span[i].fileidx]) + 1;
  jd_rec(pidbg_jitdump, 2, size);
  jd_u64(pidbg_jitdump, code_addr);
  jd_u64(pidbg_jitdump, pt->nspan);
  for (i = 0; i < pt->nspan; i++) {
    const char *file = pt->file[pt->span[i].fileidx];
    jd_u64(pidbg_jitdump, code_addr + pt->span[i].mcoff);
    jd_u32(pidbg_jitdump, pt->span[i].line);
    jd_u32(pidbg_jitdump, 0);
    fwrite(file, 1, strlen(file) + 1, pidbg_jitdump);
  }

  /* JIT_CODE_LOAD. */
  size = 16 + 4 + 4 + 8 + 8 + 8 + 8 + (size_t)nlen + 1 + code_size;
  jd_rec(pidbg_jitdump, 0, size);
  jd_u32(pidbg_jitdump, pid);
  jd_u32(pidbg_jitdump, pid);	/* Thread id: approximate. */
  jd_u64(pidbg_jitdump, code_addr);	/* vma. */
  jd_u64(pidbg_jitdump, code_addr);	/* code_addr. */
  jd_u64(pidbg_jitdump, code_size);
  jd_u64(pidbg_jitdump, code_index);
  fwrite(name, 1, (size_t)nlen + 1, pidbg_jitdump);
  fwrite((const void *)T->mcode, 1, (size_t)code_size, pidbg_jitdump);

  /* JIT_CODE_UNWINDING_INFO. */
  size = 16 + 8 + 8 + 8 + sizeof(eh_hdr) + eh_sz;
  jd_rec(pidbg_jitdump, 4, size);
  jd_u64(pidbg_jitdump, sizeof(eh_hdr) + eh_sz);	/* Unwind data size. */
  jd_u64(pidbg_jitdump, sizeof(eh_hdr));		/* EH frame hdr size. */
  jd_u64(pidbg_jitdump, 0);				/* Mapped size. */
  fwrite(eh_hdr, 1, sizeof(eh_hdr), pidbg_jitdump);
  fwrite(b->p + eh_ofs, 1, eh_sz, pidbg_jitdump);

  fflush(pidbg_jitdump);
  pidbg_lock_release();
}

/* Combined allocation for a GDB JIT entry and its ELF object. */
typedef struct PIDbgEntryObj {
  PIDbgJitEntry entry;
  size_t sz;
} PIDbgEntryObj;

/* Register the trace with the GDB JIT API. */
static void pidbg_register(lua_State *L, PIDbgTrace *pt, GCtrace *T)
{
  PIDbgBuf b;
  PIDbgEntryObj *eo;
  void *obj;
  size_t objsize;
  size_t eh_ofs, eh_sz;

  pidbg_build_obj(L2J(L), pt, T, &b, &eh_ofs, &eh_sz);
  objsize = b.len;
  eo = (PIDbgEntryObj *)lj_mem_newt(L,
	  sizeof(PIDbgEntryObj) + objsize, PIDbgEntryObj);
  obj = (char *)eo + sizeof(PIDbgEntryObj);
  memcpy(obj, b.p, objsize);
  pidbg_write_jitdump(pt, T, &b, eh_ofs, eh_sz);
  lj_mem_free(G(L), b.p, b.cap);
  eo->sz = sizeof(PIDbgEntryObj) + objsize;
  eo->entry.symfile_addr = (const char *)obj;
  eo->entry.symfile_size = objsize;
  eo->entry.next_entry = NULL;
  eo->entry.prev_entry = NULL;
  pt->entry = eo;

  pidbg_lock_acquire();
  eo->entry.next_entry = __jit_debug_descriptor.first_entry;
  if (eo->entry.next_entry)
    eo->entry.next_entry->prev_entry = &eo->entry;
  __jit_debug_descriptor.first_entry = &eo->entry;
  __jit_debug_descriptor.relevant_entry = &eo->entry;
  __jit_debug_descriptor.action_flag = GDBJIT_REGISTER;
  __jit_debug_register_code();
  pidbg_lock_release();
}

/* Unregister the trace from the GDB JIT API. */
static void pidbg_unregister(global_State *g, PIDbgTrace *pt)
{
  PIDbgEntryObj *eo = (PIDbgEntryObj *)pt->entry;
  if (eo == NULL)
    return;
  pt->entry = NULL;
  pidbg_lock_acquire();
  if (eo->entry.prev_entry)
    eo->entry.prev_entry->next_entry = eo->entry.next_entry;
  else
    __jit_debug_descriptor.first_entry = eo->entry.next_entry;
  if (eo->entry.next_entry)
    eo->entry.next_entry->prev_entry = eo->entry.prev_entry;
  __jit_debug_descriptor.relevant_entry = &eo->entry;
  __jit_debug_descriptor.action_flag = GDBJIT_UNREGISTER;
  __jit_debug_register_code();
  pidbg_lock_release();
  lj_mem_free(g, eo, eo->sz);
}

/*
** Resolve the checkpoints into a sorted table of (offset, line, file)
** entries and remember it for the trace.
*/
void lj_pidbg_addtrace(jit_State *J, GCtrace *T)
{
  PIDbgTrace *pt;
  const BCIns *startpc = mref(T->startpc, const BCIns);
  GCproto *startpt = &gcref(T->startpt)->pt;
  const char *curfile = pidbg_chunkname(startpt);
  BCLine curline = lj_debug_line(startpt, proto_bcpos(startpt, startpc));
  MSize i, n = 0;

  if (!pidbg_enabled)
    return;

  pt = (PIDbgTrace *)lj_mem_newt(J->L, sizeof(PIDbgTrace), PIDbgTrace);
  memset(pt, 0, sizeof(PIDbgTrace));
  pt->file = (char **)lj_mem_newvec(J->L, PIDBG_MAXFILE, char *);
  memset(pt->file, 0, PIDBG_MAXFILE*sizeof(char *));
  pt->span = (PIDbgSpan *)lj_mem_newvec(J->L, T->nsnap, PIDbgSpan);

  for (i = 0; i < T->nsnap; i++) {
    int known = (i < pidbg_ckptn && pidbg_ckpt[i].pt != NULL);
    uint32_t mcoff = (uint32_t)T->snap[i].mcofs;
    uint32_t bcpos = 0;
    if (known) {
      GCproto *cpt = pidbg_ckpt[i].pt;
      curline = lj_debug_line(cpt, pidbg_ckpt[i].pos);
      curfile = pidbg_chunkname(cpt);
      bcpos = (uint32_t)pidbg_ckpt[i].pos;
    }
    /* Snapshots sharing a machine code offset describe the same point. */
    if (n > 0 && pt->span[n-1].mcoff == mcoff)
      continue;
    pt->span[n].mcoff = mcoff;
    pt->span[n].bcpos = bcpos;
    pt->span[n].line = (uint32_t)curline;
    pt->span[n].fileidx = pidbg_fileidx(J, pt, curfile);
    n++;
  }
  pt->nspan = n;
  pidbg_ckpt_reset();

  pidbg_write_sidecar(pt, T);
  pidbg_register(J->L, pt, T);

  pidbg_traces_ensure(J, (MSize)T->traceno + 1);
  pidbg_lock_acquire();
  pidbg_traces[T->traceno] = pt;
  pidbg_lock_release();
}

/* -- Lua interface ------------------------------------------------------- */

/* jit.pidbg.start([mode [, sidecar [, jitdump]]]) */
static int pidbg_start(lua_State *L)
{
  jit_State *J = L2J(L);
  const char *mode = luaL_optstring(L, 1, "l");
  const char *sidecar = luaL_optstring(L, 2, NULL);
  const char *jitdump = luaL_optstring(L, 3, NULL);
  pidbg_ckpt_reset();
  pidbg_ckpt_traceno = 0;
  if (pidbg_sidecar != NULL) { fclose(pidbg_sidecar); pidbg_sidecar = NULL; }
  if (pidbg_jitdump != NULL) { fclose(pidbg_jitdump); pidbg_jitdump = NULL; }
  if (sidecar != NULL)
    pidbg_sidecar = fopen(sidecar, "wb");
  if (jitdump != NULL) {
    pidbg_jitdump = fopen(jitdump, "wb");
    if (pidbg_jitdump != NULL)
      pidbg_jitdump_header(pidbg_jitdump);
  }
  pidbg_code_index = 0;
  pidbg_lock_acquire();
  pidbg_enabled = 1;
  pidbg_lock_release();
  J->prof_mode = (int)(unsigned char)mode[0];
  lj_trace_flushall(L);
  lua_pushboolean(L, 1);
  return 1;
}

/* jit.pidbg.stop() */
static int pidbg_stop(lua_State *L)
{
  jit_State *J = L2J(L);
  PIDbgTrace **traces;
  MSize cap;
  MSize i;
  J->prof_mode = 0;
  lj_trace_flushall(L);
  pidbg_lock_acquire();
  traces = pidbg_traces;
  cap = pidbg_tracescap;
  pidbg_traces = NULL;
  pidbg_tracescap = 0;
  pidbg_enabled = 0;
  pidbg_lock_release();
  /* Free debug info of any traces that were not flushed above. */
  if (traces != NULL) {
    for (i = 0; i < cap; i++) {
      PIDbgTrace *pt = traces[i];
      if (pt != NULL) {
        MSize k;
        pidbg_unregister(J2G(J), pt);
        for (k = 0; k < pt->nfile; k++)
          lj_mem_free(J2G(J), pt->file[k], strlen(pt->file[k]) + 1);
        lj_mem_freevec(J2G(J), pt->file, PIDBG_MAXFILE, char *);
        lj_mem_freevec(J2G(J), pt->span, pt->nspan, PIDbgSpan);
        lj_mem_freet(J2G(J), pt);
      }
    }
    lj_mem_freevec(J2G(J), traces, cap, PIDbgTrace *);
  }
  if (pidbg_sidecar != NULL) { fclose(pidbg_sidecar); pidbg_sidecar = NULL; }
  if (pidbg_jitdump != NULL) { fclose(pidbg_jitdump); pidbg_jitdump = NULL; }
  pidbg_ckpt_reset();
  pidbg_ckpt_traceno = 0;
  lua_pushboolean(L, 1);
  return 1;
}

/* jit.pidbg.active() */
static int pidbg_active(lua_State *L)
{
  lua_pushboolean(L, pidbg_enabled);
  return 1;
}

/* jit.pidbg.trace(tr) */
static int pidbg_trace(lua_State *L)
{
  TraceNo tr = (TraceNo)luaL_checkinteger(L, 1);
  PIDbgTrace *pt;
  MSize i;
  pidbg_lock_acquire();
  pt = (pidbg_enabled && tr > 0 && tr < pidbg_tracescap) ?
       pidbg_traces[tr] : NULL;
  pidbg_lock_release();
  if (pt == NULL) {
    lua_pushnil(L);
    return 1;
  }
  lua_createtable(L, (int)pt->nspan, 0);
  for (i = 0; i < pt->nspan; i++) {
    lua_createtable(L, 0, 3);
    lua_pushinteger(L, (lua_Integer)pt->span[i].mcoff);
    lua_setfield(L, -2, "mcoff");
    lua_pushinteger(L, (lua_Integer)pt->span[i].line);
    lua_setfield(L, -2, "line");
    lua_pushstring(L, pt->file[pt->span[i].fileidx]);
    lua_setfield(L, -2, "file");
    lua_rawseti(L, -2, (int)(i + 1));
  }
  return 1;
}

LUALIB_API int luaopen_jit_pidbg(lua_State *L)
{
  lua_newtable(L);
  lua_pushcfunction(L, pidbg_start);	 lua_setfield(L, -2, "start");
  lua_pushcfunction(L, pidbg_stop);	 lua_setfield(L, -2, "stop");
  lua_pushcfunction(L, pidbg_active);	 lua_setfield(L, -2, "active");
  lua_pushcfunction(L, pidbg_trace);	 lua_setfield(L, -2, "trace");
  return 1;
}

#endif
