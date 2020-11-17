#include <lua.h>
#include <luajit.h>
#include <lauxlib.h>

#include <lmisclib.h>

#undef NDEBUG
#include <assert.h>

static int base(lua_State *L)
{
	struct luam_Metrics metrics;
	luaM_metrics(L, &metrics);

	/* Just check structure format, not values that fields contain. */
	(void)metrics.strhash_hit;
	(void)metrics.strhash_miss;

	(void)metrics.gc_strnum;
	(void)metrics.gc_tabnum;
	(void)metrics.gc_udatanum;
	(void)metrics.gc_cdatanum;

	(void)metrics.gc_total;
	(void)metrics.gc_freed;
	(void)metrics.gc_allocated;

	(void)metrics.gc_steps_pause;
	(void)metrics.gc_steps_propagate;
	(void)metrics.gc_steps_atomic;
	(void)metrics.gc_steps_sweepstring;
	(void)metrics.gc_steps_sweep;
	(void)metrics.gc_steps_finalize;

	(void)metrics.jit_snap_restore;
	(void)metrics.jit_trace_abort;
	(void)metrics.jit_mcode_size;
	(void)metrics.jit_trace_num;

	lua_pushboolean(L, 1);
	return 1;
}

static int gc_allocated_freed(lua_State *L)
{
	struct luam_Metrics oldm, newm;
	/* Force up garbage collect all dead objects. */
	lua_gc(L, LUA_GCCOLLECT, 0);

	luaM_metrics(L, &oldm);
	/* Simple garbage generation. */
	if (luaL_dostring(L, "local i = 0 for j = 1, 10 do i = i + j end"))
		luaL_error(L, "failed to translate Lua code snippet");
	lua_gc(L, LUA_GCCOLLECT, 0);
	luaM_metrics(L, &newm);
	assert(newm.gc_allocated - oldm.gc_allocated > 0);
	assert(newm.gc_freed - oldm.gc_freed > 0);

	lua_pushboolean(L, 1);
	return 1;
}

static int gc_steps(lua_State *L)
{
	struct luam_Metrics oldm, newm;
	/*
	 * Some garbage has already happened before the next line,
	 * i.e. during frontend processing Lua test chunk.
	 * Let's put a full garbage collection cycle on top
	 * of that, and confirm that non-null values are reported
	 * (we are not yet interested in actual numbers):
	 */
	lua_gc(L, LUA_GCCOLLECT, 0);

	luaM_metrics(L, &oldm);
	assert(oldm.gc_steps_pause > 0);
	assert(oldm.gc_steps_propagate > 0);
	assert(oldm.gc_steps_atomic > 0);
	assert(oldm.gc_steps_sweepstring > 0);
	assert(oldm.gc_steps_sweep > 0);
	/* Nothing to finalize, skipped. */
	assert(oldm.gc_steps_finalize == 0);

	/*
	 * As long as we don't create new Lua objects
	 * consequent call should return the same values:
	 */
	luaM_metrics(L, &newm);
	assert(newm.gc_steps_pause - oldm.gc_steps_pause == 0);
	assert(newm.gc_steps_propagate - oldm.gc_steps_propagate == 0);
	assert(newm.gc_steps_atomic - oldm.gc_steps_atomic == 0);
	assert(newm.gc_steps_sweepstring - oldm.gc_steps_sweepstring == 0);
	assert(newm.gc_steps_sweep - oldm.gc_steps_sweep == 0);
	/* Nothing to finalize, skipped. */
	assert(newm.gc_steps_finalize == 0);
	oldm = newm;

	/*
	 * Now the last phase: run full GC once and make sure that
	 * everything is being reported as expected:
	 */
	lua_gc(L, LUA_GCCOLLECT, 0);
	luaM_metrics(L, &newm);
	assert(newm.gc_steps_pause - oldm.gc_steps_pause == 1);
	assert(newm.gc_steps_propagate - oldm.gc_steps_propagate >= 1);
	assert(newm.gc_steps_atomic - oldm.gc_steps_atomic == 1);
	assert(newm.gc_steps_sweepstring - oldm.gc_steps_sweepstring >= 1);
	assert(newm.gc_steps_sweep - oldm.gc_steps_sweep >= 1);
	/* Nothing to finalize, skipped. */
	assert(newm.gc_steps_finalize == 0);
	oldm = newm;

	/*
	 * Now let's run three GC cycles to ensure that
	 * increment was not a lucky coincidence.
	 */
	lua_gc(L, LUA_GCCOLLECT, 0);
	lua_gc(L, LUA_GCCOLLECT, 0);
	lua_gc(L, LUA_GCCOLLECT, 0);
	luaM_metrics(L, &newm);
	assert(newm.gc_steps_pause - oldm.gc_steps_pause == 3);
	assert(newm.gc_steps_propagate - oldm.gc_steps_propagate >= 3);
	assert(newm.gc_steps_atomic - oldm.gc_steps_atomic == 3);
	assert(newm.gc_steps_sweepstring - oldm.gc_steps_sweepstring >= 3);
	assert(newm.gc_steps_sweep - oldm.gc_steps_sweep >= 3);
	/* Nothing to finalize, skipped. */
	assert(newm.gc_steps_finalize == 0);

	lua_pushboolean(L, 1);
	return 1;
}

static int objcount(lua_State *L)
{
	struct luam_Metrics oldm, newm;
	int n = lua_gettop(L);
	if (n != 1 || !lua_isfunction(L, 1))
		luaL_error(L, "incorrect argument: 1 function is required");

	/* Force up garbage collect all dead objects. */
	lua_gc(L, LUA_GCCOLLECT, 0);

	luaM_metrics(L, &oldm);
	/* Generate garbage. Argument is iterations amount. */
	lua_pushnumber(L, 1000);
	lua_call(L, 1, 0);
	lua_gc(L, LUA_GCCOLLECT, 0);
	luaM_metrics(L, &newm);
	assert(newm.gc_strnum - oldm.gc_strnum == 0);
	assert(newm.gc_tabnum - oldm.gc_tabnum == 0);
	assert(newm.gc_udatanum - oldm.gc_udatanum == 0);
	assert(newm.gc_cdatanum - oldm.gc_cdatanum == 0);

	lua_pushboolean(L, 1);
	return 1;
}

static int snap_restores(lua_State *L)
{
	struct luam_Metrics oldm, newm;
	int n = lua_gettop(L);
	if (n != 1 || !lua_isfunction(L, 1))
		luaL_error(L, "incorrect arguments: 1 function is required");

	luaM_metrics(L, &oldm);
	/* Generate snapshots. */
	lua_call(L, 0, 1);
	n = lua_gettop(L);
	if (n != 1 || !lua_isnumber(L, 1))
		luaL_error(L, "incorrect return value: 1 number is required");
	size_t snap_restores = lua_tonumber(L, 1);
	luaM_metrics(L, &newm);
	assert(newm.jit_snap_restore - oldm.jit_snap_restore == snap_restores);

	lua_pushboolean(L, 1);
	return 1;
}

static int strhash(lua_State *L)
{
	struct luam_Metrics oldm, newm;
	lua_pushstring(L, "strhash_hit");
	luaM_metrics(L, &oldm);
	lua_pushstring(L, "strhash_hit");
	lua_pushstring(L, "new_str");
	luaM_metrics(L, &newm);
	assert(newm.strhash_hit - oldm.strhash_hit == 1);
	assert(newm.strhash_miss - oldm.strhash_miss == 1);
	lua_pop(L, 3);
	lua_pushboolean(L, 1);
	return 1;
}

static int tracenum_base(lua_State *L)
{
	struct luam_Metrics metrics;
	int n = lua_gettop(L);
	if (n != 1 || !lua_isfunction(L, 1))
		luaL_error(L, "incorrect arguments: 1 function is required");

	luaJIT_setmode(L, 0, LUAJIT_MODE_FLUSH);
	/* Force up garbage collect all dead objects. */
	lua_gc(L, LUA_GCCOLLECT, 0);

	luaM_metrics(L, &metrics);
	assert(metrics.jit_trace_num == 0);

	/* Generate traces. */
	lua_call(L, 0, 1);
	n = lua_gettop(L);
	if (n != 1 || !lua_isnumber(L, 1))
		luaL_error(L, "incorrect return value: 1 number is required");
	size_t jit_trace_num = lua_tonumber(L, 1);
	luaM_metrics(L, &metrics);
	assert(metrics.jit_trace_num == jit_trace_num);

	luaJIT_setmode(L, 0, LUAJIT_MODE_FLUSH);
	/* Force up garbage collect all dead objects. */
	lua_gc(L, LUA_GCCOLLECT, 0);
	luaM_metrics(L, &metrics);
	assert(metrics.jit_trace_num == 0);

	lua_pushboolean(L, 1);
	return 1;
}

static const struct luaL_Reg testgetmetrics[] = {
	{"base", base},
	{"gc_allocated_freed", gc_allocated_freed},
	{"gc_steps", gc_steps},
	{"objcount", objcount},
	{"snap_restores", snap_restores},
	{"strhash", strhash},
	{"tracenum_base", tracenum_base},
	{NULL, NULL}
};

LUA_API int luaopen_testgetmetrics(lua_State *L)
{
	luaL_register(L, "testgetmetrics", testgetmetrics);
	return 1;
}
