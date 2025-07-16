#include "lua.h"
#include "lauxlib.h"
#include "lmisclib.h"

#undef NDEBUG
#include <assert.h>

#include "test.h"
#include "utils.h"

#include <signal.h>
#include <unistd.h>

static int resize_stack(lua_State *L)
{
	/* Resize Lua stack. */
	assert(lua_checkstack(L, LUAI_MAXCSTACK - 1000) == 1);
	kill(getpid(), SIGPROF);
	return 0;
}

static int sysprof_resizestack(void *test_state)
{
	lua_State *L = test_state;

	/* Start profiler. */
	(void)luaL_dostring(L,
		"misc.sysprof.start({mode = 'C', path = '/dev/null'})");

	lua_State *L2 = lua_newthread(L);
	lua_pushcfunction(L2, resize_stack);
	lua_resume(L2, 0);

	/* Terminate profiler. */
	(void)luaL_dostring(L, "misc.sysprof.stop()");

	return TEST_EXIT_SUCCESS;
}

int main(void)
{
	lua_State *L = utils_lua_init();
	const struct test_unit tgroup[] = {
		test_unit_def(sysprof_resizestack),
	};
	const int test_result = test_run_group(tgroup, L);
	utils_lua_close(L);
	return test_result;
}
