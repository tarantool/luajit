/*
** Precise trace debug information.
** Copyright (C) 2005-2017 Mike Pall. See Copyright Notice in luajit.h
*/

#ifndef _LJ_PIDBG_H
#define _LJ_PIDBG_H

#include "lj_obj.h"
#include "lj_jit.h"

/*
** The feature is compiled in only with the LUAJIT_USE_PIDEBUG option.
** Otherwise all the hooks are no-ops, so the normal build is not
** affected in any way.
*/
#if LJ_HASJIT && defined(LUAJIT_USE_PIDEBUG)

LUALIB_API int luaopen_jit_pidbg(lua_State *L);

/* Remember the origin of the snapshot that is being recorded now. */
LJ_FUNC void lj_pidbg_record(jit_State *J, GCproto *pt, const BCIns *pc);

/* Resolve the recorded checkpoints of the trace and register it. */
LJ_FUNC void lj_pidbg_addtrace(jit_State *J, GCtrace *T);

/* Forget the debug info of the trace. */
LJ_FUNC void lj_pidbg_deltrace(jit_State *J, GCtrace *T);

#else

#define lj_pidbg_record(J, pt, pc)	UNUSED(pt)
#define lj_pidbg_addtrace(J, T)		UNUSED(T)
#define lj_pidbg_deltrace(J, T)		UNUSED(T)

#endif

#endif
