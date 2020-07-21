/*
** Miscellaneous public C API extensions.
**
** Major portions taken verbatim or adapted from the LuaVela.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#ifndef _LMISCLIB_H
#define _LMISCLIB_H

#include "lua.h"

/* API for obtaining various platform metrics. */

struct luam_Metrics {
  /*
  ** Number of strings being interned (i.e. the string with the
  ** same payload is found, so a new one is not created/allocated).
  */
  size_t strhash_hit;
  /* Total number of strings allocations during the platform lifetime. */
  size_t strhash_miss;

  /* Amount of allocated string objects. */
  size_t gc_strnum;
  /* Amount of allocated table objects. */
  size_t gc_tabnum;
  /* Amount of allocated udata objects. */
  size_t gc_udatanum;
  /* Amount of allocated cdata objects. */
  size_t gc_cdatanum;

  /* Memory currently allocated. */
  size_t gc_total;
  /* Total amount of freed memory. */
  size_t gc_freed;
  /* Total amount of allocated memory. */
  size_t gc_allocated;

  /* Count of incremental GC steps per state. */
  size_t gc_steps_pause;
  size_t gc_steps_propagate;
  size_t gc_steps_atomic;
  size_t gc_steps_sweepstring;
  size_t gc_steps_sweep;
  size_t gc_steps_finalize;

  /*
  ** Overall number of snap restores (amount of guard assertions
  ** leading to stopping trace executions).
  */
  size_t jit_snap_restore;
  /* Overall number of abort traces. */
  size_t jit_trace_abort;
  /* Total size of all allocated machine code areas. */
  size_t jit_mcode_size;
  /* Amount of JIT traces. */
  unsigned int jit_trace_num;
};

LUAMISC_API void luaM_metrics(lua_State *L, struct luam_Metrics *metrics);

#define LUAM_MISCLIBNAME "misc"
LUALIB_API int luaopen_misc(lua_State *L);

#endif /* _LMISCLIB_H */
