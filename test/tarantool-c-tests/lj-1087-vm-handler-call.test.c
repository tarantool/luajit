#include "lua.h"
#include "lauxlib.h"

#include "test.h"
#include "utils.h"

/*
 * Test file to demonstrate a segmentation fault under
 * AddressSanitizer, when C function is used as a VM handler
 * in LuaJIT:
 *
 * Program received signal SIGSEGV, Segmentation fault.
 * 0x000055555557e77d in trace_abort (J=0x7ffff7f9b6b8) at lj_trace.c:615
 * 615         lj_vmevent_send(L, TRACE,
 * (gdb) bt
 *
 * See details in https://github.com/LuaJIT/LuaJIT/issues/1087.
 */

int is_cb_called = 0;

static void jit_attach(lua_State *L, void *cb, const char *event)
{
	lua_getglobal(L, "jit");
	lua_getfield(L, -1, "attach");
	lua_pushcfunction(L, (lua_CFunction)cb);
	if (event != NULL) {
		lua_pushstring(L, event);
	} else {
		lua_pushnil(L);
	}
	lua_pcall(L, 2, 0, 0);
}

static int trace_cb(lua_State *L) {
	(void)L;
	is_cb_called = 1;
	return 0;
}

static int handle_luafunc_frame(void *test_state)
{
	/* Setup. */
	lua_State *L = test_state;
	jit_attach(L, (void *)trace_cb, "trace");

	/* Loading and executing of a broken Lua code. */
	luaL_dostring(L, "repeat until nil > 1");

	/* Generates a Lua frame. */
	luaL_dostring(L, "return function() end");

	/* Teardown. */
	lua_settop(L, 0);

	return TEST_EXIT_SUCCESS;
}

#define TYPE_NAME "int"
#define TEST_VALUE 100
#define TOSTR(s) #s

static int __call(lua_State *L)
{
	int *n = (int *)luaL_checkudata(L, 1, TYPE_NAME);
	lua_pushfstring(L, "%d", *n);
	return 1;
}

static const luaL_Reg mt[] = {
	{ "__call", __call},
	{ NULL, NULL}
};

static int bbb(lua_State *L) {
	/* luaL_dostring(L, "local function varg_func(...) end return function() return varg_func() end"); */
	luaL_dostring(L, "repeat until nil > 1");
	return 0;
}

static int aaa(lua_State *L) {
	(void)L;
	luaL_dostring(L, "local function varg_func(...) end return function() return varg_func() end");
	lua_pushcfunction(L, (lua_CFunction)bbb);
	lua_call(L, 0, 0);
	luaL_dostring(L, "local function varg_func(...) end return function() return varg_func() end");
	return 1;
}

static int handle_c_frame(void *test_state)
{
	/* Setup. */
	lua_State *L = test_state;
	jit_attach(L, (void *)trace_cb, "trace");

	/* Frame with a broken Lua code. */
	luaL_dostring(L, "repeat until nil > 1");
	/* luaL_dostring(L, "local function varg_func(...) end return function() return varg_func() end"); */

	/* Frame with C function. */
	/* lua_getfield(L, LUA_GLOBALSINDEX, "print"); */
	/* lua_pcall(L, 0, 0, 0); */

	/* lua_pushcfunction(L, (lua_CFunction)aaa); */
	/* lua_pcall(L, 0, 0, 0); */

	lua_pushcfunction(L, (lua_CFunction)bbb);
	lua_pushcfunction(L, (lua_CFunction)aaa);
	lua_pcall(L, 0, 0, -2);

	/* Teardown. */
	lua_settop(L, 0);

	return TEST_EXIT_SUCCESS;
}

static int handle_cont_frame(void *test_state)
{
	/* Setup. */
	lua_State *L = test_state;
	jit_attach(L, (void *)trace_cb, "trace");

	/* Frame with a broken Lua code. */
	luaL_dostring(L, "repeat until nil > 1");

	/* Frame with C function. */
	luaL_newmetatable(L, TYPE_NAME);
	luaL_register(L, 0, mt);
	lua_pop(L, 1);
	int *n = (int *)lua_newuserdata(L, sizeof(*n));
	*n = TEST_VALUE;
	luaL_getmetatable(L, TYPE_NAME);
	lua_setmetatable(L, -2);
	lua_pcall(L, 0, 1, 0);

	const char *res = lua_tostring(L, -1);
	assert_str_equal(res, TOSTR(TEST_VALUE));

	/* Teardown. */
	lua_settop(L, 0);

	return TEST_EXIT_SUCCESS;
}

static int handle_bottom_frame(void *test_state)
{
	lua_State *L = test_state;

	/* Attach VM call handler. */
	jit_attach(L, (void *)trace_cb, "trace");

	/* Load a Lua code that generate a trace abort. */
	luaL_dostring(L, "repeat until nil > 1");

	/* Triggers segmentation fault. */
	jit_attach(L, (void *)trace_cb, NULL);

	/* Clear Lua stack. */
	lua_settop(L, 0);

	return TEST_EXIT_SUCCESS;
}

int main(void)
{
	lua_State *L = utils_lua_init();
	const struct test_unit tgroup[] = {
#ifdef LJ_HASJIT
		/* test_unit_def(handle_luafunc_frame), */
		/* test_unit_def(handle_bottom_frame), */
		/* test_unit_def(handle_cont_frame), */
		test_unit_def(handle_c_frame),
#endif /* LJ_HASJIT */
	};
	luaL_openlibs(L);
	int res = luaL_dostring(L, "jit.opt.start('hotloop=1')");
	assert(res == 0);
	const int test_result = test_run_group(tgroup, L);
	utils_lua_close(L);
	return test_result;
}
