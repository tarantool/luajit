/*
** Miscellaneous public C API extensions.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#define lj_mapi_c
#define LUA_CORE

#include "lua.h"
#include "lmisclib.h"

#include "lj_obj.h"
#include "lj_dispatch.h"

#if LJ_HASJIT
#include "lj_jit.h"
#endif

LUAMISC_API void luaM_metrics(lua_State *L, struct luam_Metrics *metrics)
{
  global_State *g = G(L);
  GCState *gc = &g->gc;
#if LJ_HASJIT
  jit_State *J = G2J(g);
#endif

  lua_assert(metrics != NULL);

  metrics->strhash_hit = g->strhash_hit;
  metrics->strhash_miss = g->strhash_miss;

  metrics->gc_strnum = g->strnum;
  metrics->gc_tabnum = gc->tabnum;
  metrics->gc_udatanum = gc->udatanum;
#if LJ_HASFFI
  metrics->gc_cdatanum = gc->cdatanum;
#else
  metrics->gc_cdatanum = 0;
#endif

  metrics->gc_total = gc->total;
  metrics->gc_freed = gc->freed;
  metrics->gc_allocated = gc->allocated;

  metrics->gc_steps_pause = gc->state_count[GCSpause];
  metrics->gc_steps_propagate = gc->state_count[GCSpropagate];
  metrics->gc_steps_atomic = gc->state_count[GCSatomic];
  metrics->gc_steps_sweepstring = gc->state_count[GCSsweepstring];
  metrics->gc_steps_sweep = gc->state_count[GCSsweep];
  metrics->gc_steps_finalize = gc->state_count[GCSfinalize];

#if LJ_HASJIT
  metrics->jit_snap_restore = J->nsnaprestore;
  metrics->jit_trace_abort = J->ntraceabort;
  metrics->jit_mcode_size = J->szallmcarea;
  metrics->jit_trace_num = J->tracenum;
  metrics->jit_trace_enter = J->ntraceenter;
#else
  metrics->jit_snap_restore = 0;
  metrics->jit_trace_abort = 0;
  metrics->jit_mcode_size = 0;
  metrics->jit_trace_num = 0;
  metrics->jit_trace_enter = NULL;
#endif
}
