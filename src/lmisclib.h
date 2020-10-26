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

/* Profiler public API. */
#define LUAM_PROFILE_SUCCESS 0
#define LUAM_PROFILE_ERR     1
#define LUAM_PROFILE_ERRMEM  2
#define LUAM_PROFILE_ERRIO   3

/* Profiler options. */
struct luam_Prof_options {
  /* Options for the profile writer and final callback. */
  void *ctx;
  /* Custom buffer to write data. */
  uint8_t *buf;
  /* The buffer's size. */
  size_t len;
  /*
  ** Writer function for profile events.
  ** Should return amount of written bytes on success or zero in case of error.
  */
  size_t (*writer)(const void **data, size_t len, void *ctx);
  /*
  ** Callback on profiler stopping. Required for correctly cleaning
  ** at vm shoutdown when profiler still running.
  ** Returns zero on success.
  */
  int (*on_stop)(void *ctx, uint8_t *buf);
};

/*
** Starts profiling. Returns LUAM_PROFILE_SUCCESS on success and one of
** LUAM_PROFILE_ERR* codes otherwise. Destroyer is not called in case of
** LUAM_PROFILE_ERR*.
*/
LUAMISC_API int luaM_memprof_start(lua_State *L,
				   const struct luam_Prof_options *opt);

/*
** Stops profiling. Returns LUAM_PROFILE_SUCCESS on success and one of
** LUAM_PROFILE_ERR* codes otherwise. If writer() function returns zero
** on call at buffer flush, or on_stop() callback returns non-zero
** value, returns LUAM_PROFILE_ERRIO.
*/
LUAMISC_API int luaM_memprof_stop(const lua_State *L);

/* Check that profiler is running. */
LUAMISC_API int luaM_memprof_isrunning(void);

#define LUAM_MISCLIBNAME "misc"
LUALIB_API int luaopen_misc(lua_State *L);

#endif /* _LMISCLIB_H */
