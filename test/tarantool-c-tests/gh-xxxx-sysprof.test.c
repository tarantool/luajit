#include "lua.h"
#include "lauxlib.h"
#include "lmisclib.h"

#undef NDEBUG
#include <assert.h>

#include "test.h"
#include "utils.h"

#include <signal.h>
#include <unistd.h>

static int fill_stack(lua_State *L)
{
	for (int i = 0; i < 100; i++) {
		lua_pushnil(L);
	}
	return 0;
}

static int some_func_2(lua_State *L)
{
	/* lua_pushcfunction(L, fill_stack); */
	/* lua_call(L, 0, 0); */
	lua_cpcall(L, fill_stack, NULL);
	return TEST_EXIT_SUCCESS;
}

static int some_func_1(lua_State *L)
{
	lua_pushcfunction(L, some_func_2);
	lua_call(L, 0, 1);
	fill_stack(L);

	pid_t self_pid = getpid();
	/* Dump the single sample outside the VM. */
	kill(self_pid, SIGPROF);
	return lua_yield(L, 0);
}

static int execute_coro(lua_State *L)
{
	lua_pushcfunction(L, some_func_1);
	lua_call(L, 0, 1);
	fill_stack(L);

	lua_State *L2 = lua_newthread(L);
	lua_pushcfunction(L2, some_func_1);
	lua_resume(L2, 0);
	fill_stack(L2);

	/* (void)luaL_dostring(L, */
	/* 	"misc.sysprof.start({mode = 'C', path = '/dev/null'})"); */

	/* pid_t self_pid = getpid(); */
	/* /1* Dump the single sample outside the VM. *1/ */
	/* kill(self_pid, SIGPROF); */

	/* /1* No assertion fail -- stop the profiler and exit. *1/ */
	/* (void)luaL_dostring(L, "misc.sysprof.stop()"); */

	return 0;
}

/* Sysprof dummy stream helpers. {{{ */

/*
 * Yep, 8Mb. Tuned in order not to bother the platform with too
 * often flushes.
 */
#define STREAM_BUFFER_SIZE (8 * 1024 * 1024)

struct dummy_ctx {
	/* Buffer for data recorded by sysprof. */
	uint8_t buf[STREAM_BUFFER_SIZE];
};

static struct dummy_ctx context;

static int stream_new(struct luam_Sysprof_Options *options)
{
	/* Set dummy context. */
	options->ctx = &context;
	options->buf = (uint8_t *)&context.buf;
	options->len = STREAM_BUFFER_SIZE;
	return PROFILE_SUCCESS;
}

static int stream_delete(void *rawctx, uint8_t *buf)
{
	/* assert(rawctx == &context); */
	/* XXX: No need to release context memory. Just return. */
	return PROFILE_SUCCESS;
}

static size_t stream_writer(const void **buf_addr, size_t len, void *rawctx)
{
	/* assert(rawctx == &context); */
	/* Do nothing, just return back to the profiler. */
	return STREAM_BUFFER_SIZE;
}

static int sysprof_wrong_top_frame(void *test_state)
{
	/* struct luam_Sysprof_Counters counters = {}; */
	struct luam_Sysprof_Options opt = {
		/* Collect full backtraces per event. */
		.mode = LUAM_SYSPROF_CALLGRAPH,
		/* msec */
		.interval = 1,
	};

	lua_State *L = test_state;

	/* Customize and start profiler. */
	assert(stream_new(&opt) == PROFILE_SUCCESS);
	assert(luaM_sysprof_set_writer(stream_writer) == PROFILE_SUCCESS);
	assert(luaM_sysprof_set_on_stop(stream_delete) == PROFILE_SUCCESS);

	/* Start profiler. */
	assert(luaM_sysprof_start(L, &opt) == PROFILE_SUCCESS);

	int status = lua_cpcall(L, execute_coro, NULL);
	assert_true(status == LUA_ERRRUN);
	fill_stack(L);

	kill(getpid(), SIGPROF);

	/* Terminate profiler. */
	assert(luaM_sysprof_stop(L) == PROFILE_SUCCESS);

	return TEST_EXIT_SUCCESS;
}

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

static int error_after_coroutine_return(lua_State *L)
{
	lua_State *innerL = lua_newthread(L);
	fprintf(stderr, "innerL %p\n", innerL);
	luaL_loadstring(innerL, "return");
	lua_pcall(innerL, 0, 0, 0);
	luaL_error(L, "my fancy error");
	assert(NULL); /* Unreachable. */
	return 0;
}

static int func1(lua_State *L)
{
	lua_State *L2 = lua_newthread(L);
	/* fprintf(stderr, "innerL %p\n", func2); */
	lua_pushcfunction(L2, error_after_coroutine_return);
	lua_pcall(L2, 0, 0, 0);
	/* lua_resume(L2, 0); */
	kill(getpid(), SIGPROF);
	return 0;
}

static int sysprof_err_throw(void *test_state)
{
	lua_State *L = test_state;
	/* Start profiler. */
	(void)luaL_dostring(L,
		"misc.sysprof.start({mode = 'C', path = '/dev/null', interval = 999999999999})");

	lua_cpcall(L, func1, NULL);

	/* Terminate profiler. */
	/* No assertion fail -- stop the profiler and exit. */
	(void)luaL_dostring(L, "misc.sysprof.stop()");

	return TEST_EXIT_SUCCESS;
}

static int nop(lua_State *L)
{
	lua_State *innerL = lua_newthread(L);
	fprintf(stderr, "innerL %p\n", innerL);
	luaL_loadstring(innerL, "return");
	lua_pcall(innerL, 0, 0, 0);
	kill(getpid(), SIGPROF);
	return 0;
}

static int func2(lua_State *L)
{
	lua_State *L2 = lua_newthread(L);
	lua_pushcfunction(L2, nop);
	lua_pcall(L2, 0, 0, 0);
	/* lua_resume(L2, 0); */
	kill(getpid(), SIGPROF);
	return 0;
}

static int sysprof_creturn(void *test_state)
{
	lua_State *L = test_state;
	/* Start profiler. */
	(void)luaL_dostring(L,
		"misc.sysprof.start({mode = 'C', path = '/dev/null', interval = 999999999999})");

	lua_cpcall(L, func2, NULL);

	/* Terminate profiler. */
	/* No assertion fail -- stop the profiler and exit. */
	(void)luaL_dostring(L, "misc.sysprof.stop()");

	return TEST_EXIT_SUCCESS;
}

int main(void)
{
	lua_State *L = utils_lua_init();
	const struct test_unit tgroup[] = {
		test_unit_def(sysprof_wrong_top_frame),
		test_unit_def(sysprof_resizestack),
		test_unit_def(sysprof_err_throw),
		test_unit_def(sysprof_creturn),
	};
	const int test_result = test_run_group(tgroup, L);
	utils_lua_close(L);
	return test_result;
}
