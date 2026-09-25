/*
** Precise trace debug information.
** Copyright (C) 2005-2017 Mike Pall. See Copyright Notice in luajit.h
*/

#define lj_pidbg_c
#define LUA_CORE

#include "lj_obj.h"

#if LJ_HASJIT && defined(LUAJIT_USE_PIDEBUG)

#include <string.h>
#include "lauxlib.h"
#include "lj_gc.h"
#include "lj_debug.h"
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
  uint32_t line;	/* Source line. */
  uint32_t fileidx;	/* Index into the file name table. */
} PIDbgSpan;

/* Resolved debug information of a single trace. */
typedef struct PIDbgTrace {
  MSize nspan;		/* Number of debug entries. */
  MSize nfile;		/* Number of distinct chunk names. */
  PIDbgSpan *span;	/* Array of debug entries, sorted by offset. */
  char **file;		/* Array of distinct chunk names. */
} PIDbgTrace;

/* Maximum number of distinct chunk names tracked for a single trace. */
#define PIDBG_MAXFILE		16

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
    if (known) {
      GCproto *cpt = pidbg_ckpt[i].pt;
      curline = lj_debug_line(cpt, pidbg_ckpt[i].pos);
      curfile = pidbg_chunkname(cpt);
    }
    /* Snapshots sharing a machine code offset describe the same point. */
    if (n > 0 && pt->span[n-1].mcoff == mcoff)
      continue;
    pt->span[n].mcoff = mcoff;
    pt->span[n].line = (uint32_t)curline;
    pt->span[n].fileidx = pidbg_fileidx(J, pt, curfile);
    n++;
  }
  pt->nspan = n;
  pidbg_ckpt_reset();

  pidbg_traces_ensure(J, (MSize)T->traceno + 1);
  pidbg_lock_acquire();
  pidbg_traces[T->traceno] = pt;
  pidbg_lock_release();
}

/* -- Lua interface ------------------------------------------------------- */

/* jit.pidbg.start([mode]) */
static int pidbg_start(lua_State *L)
{
  jit_State *J = L2J(L);
  const char *mode = luaL_optstring(L, 1, "l");
  pidbg_ckpt_reset();
  pidbg_ckpt_traceno = 0;
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
        for (k = 0; k < pt->nfile; k++)
          lj_mem_free(J2G(J), pt->file[k], strlen(pt->file[k]) + 1);
        lj_mem_freevec(J2G(J), pt->file, PIDBG_MAXFILE, char *);
        lj_mem_freevec(J2G(J), pt->span, pt->nspan, PIDbgSpan);
        lj_mem_freet(J2G(J), pt);
      }
    }
    lj_mem_freevec(J2G(J), traces, cap, PIDbgTrace *);
  }
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
