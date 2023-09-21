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

static int call_vm_handler(void *test_state)
{
	lua_State *L = test_state;
	if (!L)
		return TEST_EXIT_FAILURE;
	luaL_openlibs(L);

	/* Attach VM call handler. */
	jit_attach(L, (void *)trace_cb, "trace");

	luaL_dostring(L, "jit.opt.start('hotloop=1')");

	/* Load a Lua code that generate a trace abort. */
	luaL_dostring(L, "repeat until a >= 'b' > 'b'");

	/* Triggers segmentation fault. */
	jit_attach(L, (void *)trace_cb, NULL);

	/* Make sure VM handler call was actually called. */
	assert_true(is_cb_called == 1);

	/* Clear Lua stack. */
	lua_pop(L, 0);

	return TEST_EXIT_SUCCESS;
}

int main(void)
{
	lua_State *L = utils_lua_init();
	const struct test_unit tgroup[] = {
#ifdef LJ_HASJIT
		test_unit_def(call_vm_handler)
#endif /* LJ_HASJIT */
	};
	const int test_result = test_run_group(tgroup, L);
	utils_lua_close(L);
	return test_result;
}
