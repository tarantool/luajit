/*
** Miscellaneous Lua extensions library.
**
** Major portions taken verbatim or adapted from the LuaVela interpreter.
** Copyright (C) 2015-2019 IPONWEB Ltd.
*/

#define lib_misc_c
#define LUA_LIB

#include "lua.h"
#include "lmisclib.h"
#include "lauxlib.h"
#include <errno.h>
#include <ctype.h>

#include "lj_obj.h"
#include "lj_str.h"
#include "lj_tab.h"
#include "lj_lib.h"
#include "lj_err.h"
#include "lj_ctype.h"
#include "lj_cdata.h"
#include "lj_state.h"

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

LJLIB_CF(misc_tonumber64)
{
  TValue *o = L->base;
  if (o >= L->top)
    lj_err_arg(L, 1, LJ_ERR_NOVAL);
  int base = luaL_optint(L, 2, -1);
  luaL_argcheck(L, (2 <= base && base <= 36) || base == -1, 2,
                "base out of range");
  uint32_t ctypeid = 0;
  GCcdata *cd;
  CTSize size;
  CTState *cts;
  double val_d;
  switch (lua_type(L, 1)) {
  case LUA_TNUMBER:
    base = (base == -1 ? 10 : base);
    if (base != 10)
      return luaL_argerror(L, 1, "string expected");
    val_d = numV(L->base);
    if (val_d < (double)INT64_MIN || val_d >= (double)UINT64_MAX)
      return luaL_argerror(L, 1, "cannot convert to 64-bit integer");
    cts = ctype_cts(L);
    if (val_d < 0.0)
      ctypeid = CTID_INT64;
    else
      ctypeid = CTID_UINT64;
    lj_ctype_info(cts, ctypeid, &size);
    assert(size != CTSIZE_INVALID);
    cd = lj_cdata_new(cts, ctypeid, size);
    o = L->top;
    setcdataV(L, o, cd);
    incr_top(L);
    if (val_d < 0.0)
      *(int64_t *) cdataptr(cd) = (int64_t)val_d;
    else
      *(uint64_t *) cdataptr(cd) = (uint64_t)val_d;
    return 1;
  case LUA_TSTRING: {
    GCstr *s = strV(o);
    const char *arg = strdata(s);
    size_t argl = s->len;
    while (argl > 0 && isspace(arg[argl - 1]))
      argl--;
    while (isspace(*arg)) {
      arg++;
      argl--;
    }

    /*
     * Check if we're parsing custom format:
     * 1) '0x' or '0X' trim in case of base == 16 or base == -1
     * 2) '0b' or '0B' trim in case of base == 2  or base == -1
     * 3) '-' for negative numbers
     * 4) LL, ULL, LLU - trim, but only for base == 2 or
     *    base == 16 or base == -1. For consistency do not bother
     *    with any non-common bases, since user may have specified
     *    base >= 22, in which case 'L' will be a digit.
     */
    char negative = 0;
    if (arg[0] == '-') {
      arg++;
      argl--;
      negative = 1;
    }
    if (argl > 2 && arg[0] == '0') {
      if ((arg[1] == 'x' || arg[1] == 'X') &&
          (base == 16 || base == -1)) {
        base = 16; arg += 2; argl -= 2;
      } else if ((arg[1] == 'b' || arg[1] == 'B') &&
                 (base == 2 || base == -1)) {
        base = 2;  arg += 2; argl -= 2;
      }
    }
    int ull = 0;
    if (argl > 2 && (base == 2 || base == 16 || base == -1)) {
      if (arg[argl - 1] == 'u' || arg[argl - 1] == 'U') {
        ull = 1;
        --argl;
      }
      if ((arg[argl - 1] == 'l' || arg[argl - 1] == 'L') &&
          (arg[argl - 2] == 'l' || arg[argl - 2] == 'L')) {
        argl -= 2;
        if (ull == 0 && (arg[argl - 1] == 'u' || arg[argl - 1] == 'U')) {
          ull = 1;
          --argl;
        }
      } else {
        ull = 0;
      }
    }
    base = (base == -1 ? 10 : base);
    errno = 0;
    char *arge;
    unsigned long long result = strtoull(arg, &arge, base);
    if (errno == 0 && arge == arg + argl) {
      if (argl == 0) {
        lua_pushnil(L);
      } else if (negative) {
        if (ull == 0 && result != 0 && result - 1 > INT64_MAX) {
          lua_pushnil(L);
          return 1;
        }
        cts = ctype_cts(L);
        /*
         * To test overflow, consider
         *  result > -INT64_MIN;
         *  result - 1 > -INT64_MIN - 1;
         * Assumption:
         *  INT64_MAX == -(INT64_MIN + 1);
         * Finally,
         *  result - 1 > INT64_MAX;
         */
        int64_t val_i;
        uint64_t val_u;
        if (ull != 0) {
          val_u = (UINT64_MAX - result) + 1;
          ctypeid = CTID_UINT64;
        } else {
          val_i = -result;
          ctypeid = CTID_INT64;
        }

        lj_ctype_info(cts, ctypeid, &size);
        assert(size != CTSIZE_INVALID);

        cd = lj_cdata_new(cts, ctypeid, size);
        TValue *o = L->top;
        setcdataV(L, o, cd);
        incr_top(L);
        if (ull != 0)
          *(uint64_t *) cdataptr(cd) = val_u;
        else
          *(int64_t *) cdataptr(cd) = val_i;
      } else {
        cts = ctype_cts(L);
        uint64_t val_u = result;
        ctypeid = CTID_UINT64;
        lj_ctype_info(cts, ctypeid, &size);
        assert(size != CTSIZE_INVALID);

        cd = lj_cdata_new(cts, ctypeid, size);
        TValue *o = L->top;
        setcdataV(L, o, cd);
        incr_top(L);
        *(uint64_t *) cdataptr(cd) = val_u;
      }
      return 1;
    }
    break;
  }
  case LUA_TCDATA:
    base = (base == -1 ? 10 : base);
    if (base != 10)
      return luaL_argerror(L, 1, "string expected");
    cd = cdataV(L->base);
    ctypeid = cd->ctypeid;
    if (ctypeid >= CTID_INT8 && ctypeid <= CTID_DOUBLE) {
      lua_pushvalue(L, 1);
      return 1;
    }
    break;
  }
  lua_pushnil(L);
  return 1;
}

/* ------------------------------------------------------------------------ */

#include "lj_libdef.h"

LUALIB_API int luaopen_misc(struct lua_State *L)
{
  LJ_LIB_REG(L, LUAM_MISCLIBNAME, misc);
  return 1;
}
