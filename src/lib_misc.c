/*
** Miscellaneous Lua extensions library.
**
** Major portions taken verbatim or adapted from the LuaVela interpreter.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#define lib_misc_c
#define LUA_LIB

#include <stdio.h>
#include <errno.h>

#include "lua.h"
#include "lmisclib.h"
#include "lauxlib.h"

#include "lj_obj.h"
#include "lj_str.h"
#include "lj_tab.h"
#include "lj_lib.h"
#include "lj_gc.h"
#include "lj_err.h"

#include "profile/ljp_memprof.h"

/* ------------------------------------------------------------------------ */

static LJ_AINLINE void setnumfield(struct lua_State *L, GCtab *t,
				   const char *name, int64_t val)
{
  setnumV(lj_tab_setstr(L, t, lj_str_newz(L, name)), (double)val);
}

#define LJLIB_MODULE_misc

LJLIB_CF(misc_getmetrics)
{
  struct luam_Metrics metrics;
  GCtab *m;

  lua_createtable(L, 0, 19);
  m = tabV(L->top - 1);

  luaM_metrics(L, &metrics);

  setnumfield(L, m, "strhash_hit", metrics.strhash_hit);
  setnumfield(L, m, "strhash_miss", metrics.strhash_miss);

  setnumfield(L, m, "gc_strnum", metrics.gc_strnum);
  setnumfield(L, m, "gc_tabnum", metrics.gc_tabnum);
  setnumfield(L, m, "gc_udatanum", metrics.gc_udatanum);
  setnumfield(L, m, "gc_cdatanum", metrics.gc_cdatanum);

  setnumfield(L, m, "gc_total", metrics.gc_total);
  setnumfield(L, m, "gc_freed", metrics.gc_freed);
  setnumfield(L, m, "gc_allocated", metrics.gc_allocated);

  setnumfield(L, m, "gc_steps_pause", metrics.gc_steps_pause);
  setnumfield(L, m, "gc_steps_propagate", metrics.gc_steps_propagate);
  setnumfield(L, m, "gc_steps_atomic", metrics.gc_steps_atomic);
  setnumfield(L, m, "gc_steps_sweepstring", metrics.gc_steps_sweepstring);
  setnumfield(L, m, "gc_steps_sweep", metrics.gc_steps_sweep);
  setnumfield(L, m, "gc_steps_finalize", metrics.gc_steps_finalize);

  setnumfield(L, m, "jit_snap_restore", metrics.jit_snap_restore);
  setnumfield(L, m, "jit_trace_abort", metrics.jit_trace_abort);
  setnumfield(L, m, "jit_mcode_size", metrics.jit_mcode_size);
  setnumfield(L, m, "jit_trace_num", metrics.jit_trace_num);

  return 1;
}

/* ------------------------------------------------------------------------ */

#include "lj_libdef.h"

/* ----- misc.memprof module ---------------------------------------------- */

#define LJLIB_MODULE_misc_memprof

/*
** Yep, 8Mb. Tuned in order not to bother the platform with too often flushes.
*/
#define STREAM_BUFFER_SIZE (8 * 1024 * 1024)

/* Structure given as ctx to memprof writer and on_stop callback. */
struct memprof_ctx {
  /* Output file stream for data. */
  FILE *stream;
  /* Profiled global_State for lj_mem_free at on_stop callback. */
  global_State *g;
};

static LJ_AINLINE void memprof_ctx_free(struct memprof_ctx *ctx, uint8_t *buf)
{
  lj_mem_free(ctx->g, buf, STREAM_BUFFER_SIZE);
  lj_mem_free(ctx->g, ctx, sizeof(*ctx));
}

/* Default buffer writer function. Just call fwrite to corresponding FILE. */
static size_t buffer_writer_default(const void **buf_addr, size_t len,
				    void *opt)
{
  FILE *stream = ((struct memprof_ctx *)opt)->stream;
  const void * const buf_start = *buf_addr;
  const void *data = *buf_addr;
  size_t write_total = 0;

  lua_assert(len <= STREAM_BUFFER_SIZE);

  for (;;) {
    const size_t written = fwrite(data, 1, len, stream);

    if (LJ_UNLIKELY(written == 0)) {
      /* Re-tries write in case of EINTR. */
      if (errno == EINTR) {
	errno = 0;
	continue;
      }
      break;
    }

    write_total += written;

    if (write_total == len)
      break;

    data = (uint8_t *)data + (ptrdiff_t)written;
  }
  lua_assert(write_total <= len);

  *buf_addr = buf_start;
  return write_total;
}

/* Default on stop callback. Just close corresponding stream. */
static int on_stop_cb_default(void *opt, uint8_t *buf)
{
  struct memprof_ctx *ctx = opt;
  FILE *stream = ctx->stream;
  memprof_ctx_free(ctx, buf);
  return fclose(stream);
}

/* local started, err, errno = ujit.memprof.start(fname) */
LJLIB_CF(misc_memprof_start)
{
  struct luam_Prof_options opt = {0};
  struct memprof_ctx *ctx;
  const char *fname;
  int memprof_status;
  int started;

  fname = strdata(lj_lib_checkstr(L, 1));

  ctx = lj_mem_new(L, sizeof(*ctx));
  if (ctx == NULL)
    goto errmem;

  opt.ctx = ctx;
  opt.writer = buffer_writer_default;
  opt.on_stop = on_stop_cb_default;
  opt.len = STREAM_BUFFER_SIZE;
  opt.buf = (uint8_t *)lj_mem_new(L, STREAM_BUFFER_SIZE);
  if (NULL == opt.buf) {
    lj_mem_free(G(L), ctx, sizeof(*ctx));
    goto errmem;
  }

  ctx->g = G(L);
  ctx->stream = fopen(fname, "wb");

  if (ctx->stream == NULL) {
    memprof_ctx_free(ctx, opt.buf);
    return luaL_fileresult(L, 0, fname);
  }

  memprof_status = ljp_memprof_start(L, &opt);
  started = memprof_status == LUAM_PROFILE_SUCCESS;

  if (LJ_UNLIKELY(!started)) {
    fclose(ctx->stream);
    remove(fname);
    memprof_ctx_free(ctx, opt.buf);
    switch (memprof_status) {
    case LUAM_PROFILE_ERR:
      lua_pushnil(L);
      setstrV(L, L->top++, lj_err_str(L, LJ_ERR_PROF_ISRUNNING));
      return 2;
    case LUAM_PROFILE_ERRMEM:
      /* Unreachable for now. */
      goto errmem;
    case LUAM_PROFILE_ERRIO:
      return luaL_fileresult(L, 0, fname);
    default:
      lua_assert(0);
    }
  }
  lua_pushboolean(L, started);

  return 1;
errmem:
  lua_pushnil(L);
  setstrV(L, L->top++, lj_err_str(L, LJ_ERR_ERRMEM));
  return 2;
}

/* local stopped, err = misc.memprof.stop() */
LJLIB_CF(misc_memprof_stop)
{
  int status = ljp_memprof_stop();
  int stopped_successfully = status == LUAM_PROFILE_SUCCESS;
  if (!stopped_successfully) {
    switch (status) {
    case LUAM_PROFILE_ERR:
      lua_pushnil(L);
      setstrV(L, L->top++, lj_err_str(L, LJ_ERR_PROF_NOTRUNNING));
      return 2;
    case LUAM_PROFILE_ERRIO:
      return luaL_fileresult(L, 0, NULL);
    default:
      lua_assert(0);
    }
  }
  lua_pushboolean(L, stopped_successfully);
  return 1;
}

/* local running = misc.memprof.is_running() */
LJLIB_CF(misc_memprof_is_running)
{
  lua_pushboolean(L, ljp_memprof_is_running());
  return 1;
}

#include "lj_libdef.h"

/* ------------------------------------------------------------------------ */

LUALIB_API int luaopen_misc(struct lua_State *L)
{
  LJ_LIB_REG(L, LUAM_MISCLIBNAME, misc);
  LJ_LIB_REG(L, LUAM_MISCLIBNAME ".memprof", misc_memprof);
  return 1;
}
