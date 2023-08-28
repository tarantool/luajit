#include "lua.h"
#include "lauxlib.h"

#include "test.h"
#include "utils.h"

/*
 * The test file to demonstrate inconsistent LuaJIT's behaviour
 * for wrapped C functions, after `LUAJIT_MODE_WRAPCFUNC` changed.
 * The error should be raised before call to the C function, since
 * the minimum available space for the Lua stack should be checked
 * by the VM.
 * See also: https://github.com/LuaJIT/LuaJIT/issues/1047.
 */

/* Simple proxy. */
static int ct_wrap(lua_State *L, lua_CFunction f)
{
	return f(L);
}

static int is_called = 0;

static int push_minstack(lua_State *L)
{
	is_called = 1;
	for (int i = 0; i < LUA_MINSTACK; i++)
		lua_pushinteger(L, i);
	return LUA_MINSTACK;
}

static int fill_stack(lua_State *L, int limit)
{
	while(lua_gettop(L) < limit)
		lua_pushinteger(L, 42);
	return 0;
}

static int test_wrapon(void *test_state)
{
	/* Setup. */
	lua_State *mainL = test_state;
	lua_State *L = lua_newthread(mainL);
	is_called = 0;

	lua_pushlightuserdata(L, (void *)ct_wrap);
	luaJIT_setmode(L, -1, LUAJIT_MODE_WRAPCFUNC|LUAJIT_MODE_ON);
	lua_pop(L, 1);

	/* 2 per frame in GC64 mode including the dummy frame. */
	fill_stack(L, LUAI_MAXSTACK - 2 - 2);

	lua_pushcfunction(L, push_minstack);
	int status = lua_pcall(L, 0, 0, 0);
	assert_true(status == LUA_ERRRUN);
	assert_str_equal(lua_tostring(L, -1), "stack overflow");
	assert_true(is_called == 0);

	/* Tear down. */
	luaJIT_setmode(L, 0, LUAJIT_MODE_WRAPCFUNC|LUAJIT_MODE_OFF);
	lua_settop(mainL, 0);
	return TEST_EXIT_SUCCESS;
}

static int test_wrapoff(void *test_state)
{
	/* Setup. */
	lua_State *mainL = test_state;
	lua_State *L = lua_newthread(mainL);
	is_called = 0;

	/*
	 * Turn on and turn off should result with the correct
	 * default behaviour.
	 */
	lua_pushlightuserdata(L, (void *)ct_wrap);
	luaJIT_setmode(L, -1, LUAJIT_MODE_WRAPCFUNC|LUAJIT_MODE_ON);
	lua_pop(L, 1);
	luaJIT_setmode(L, 0, LUAJIT_MODE_WRAPCFUNC|LUAJIT_MODE_OFF);

	/* 2 per frame in GC64 mode including the dummy frame. */
	fill_stack(L, LUAI_MAXSTACK - 2 - 2);

	lua_pushcfunction(L, push_minstack);
	int status = lua_pcall(L, 0, 0, 0);
	assert_true(status == LUA_ERRRUN);
	assert_str_equal(lua_tostring(L, -1), "stack overflow");
	assert_true(is_called == 0);

	/* Tear down. */
	lua_settop(mainL, 0);
	return TEST_EXIT_SUCCESS;
}

int main(void)
{
	lua_State *L = utils_lua_init();
	const struct test_unit tgroup[] = {
		test_unit_def(test_wrapon),
		test_unit_def(test_wrapoff)
	};
	const int test_result = test_run_group(tgroup, L);
	utils_lua_close(L);
	return test_result;
}
