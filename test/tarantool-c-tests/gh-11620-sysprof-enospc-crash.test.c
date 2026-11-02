/*
** Testing of the sysprof behaviour when a stream write fails.
**
** A full file system makes the sysprof writer return an error and
** release the stream buffer. The profiler must stop the stream
** gracefully, return an error from luaM_sysprof_stop() and
** release the resources.
*/

#include "lauxlib.h"
#include "lua.h"

/* Need for skipcond for OS and ARCH. */
#include "lj_arch.h"

#include "test.h"

#if LJ_HASSYSPROF && !defined(LUAJIT_USE_VALGRIND)

#include "lmisclib.h"
#include "utils.h"

#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

/*
 * The buffer size is enough for the maximal ULEB128 value.
 * A small buffer makes the profiler flush it right during the
 * prologue or the first sample.
 */
#define STREAM_BUFFER_SIZE 10

/* Do not let the timer interfere with the manually emitted signals. */
#define SYSPROF_TEST_INTERVAL 1000

struct sysprof_ctx {
	/* Simulate write errors. */
	int fail;
	/* Number of on_stop callback calls. */
	int on_stop_calls;
};

static struct sysprof_ctx ctx;

/*
 * The profiler skips the frames up to
 * SYSPROF_HANDLER_STACK_DEPTH (6) while streaming the host stack,
 * so provide the frames after that boundary.
 */
#define SYSPROF_TEST_FRAME_START 7
#define SYSPROF_TEST_FRAME_COUNT 4

static size_t failing_writer(const void **buf_addr, size_t len, void *opt)
{
	struct sysprof_ctx *ctx = opt;

	if (ctx->fail) {
		errno = ENOSPC;
		*buf_addr = NULL;
		return 0;
	}

	return len;
}

static int on_stop(void *opt, uint8_t *buf)
{
	struct sysprof_ctx *ctx = opt;

	UNUSED(buf);
	ctx->on_stop_calls++;
	return 0;
}

static void backtracer(void *(*frame_writer)(int, void *))
{
	int frame_no;

	for (frame_no = SYSPROF_TEST_FRAME_START;
	     frame_no < SYSPROF_TEST_FRAME_START + SYSPROF_TEST_FRAME_COUNT;
	     ++frame_no)
		frame_writer(frame_no, (void *)(uintptr_t)frame_no);
}

static void sysprof_test_configure(struct luam_Sysprof_Options *opt,
				   uint8_t *buf)
{
	memset(&ctx, 0, sizeof(ctx));
	memset(opt, 0, sizeof(*opt));
	opt->mode = LUAM_SYSPROF_CALLGRAPH;
	opt->interval = SYSPROF_TEST_INTERVAL;
	opt->buf = buf;
	opt->len = STREAM_BUFFER_SIZE;
	opt->ctx = &ctx;

	assert_true(luaM_sysprof_set_writer(failing_writer) == PROFILE_SUCCESS);
	assert_true(luaM_sysprof_set_on_stop(on_stop) == PROFILE_SUCCESS);
	assert_true(luaM_sysprof_set_backtracer(backtracer) == PROFILE_SUCCESS);
}

static int sysprof_enospc_during_sampling(void *test_state)
{
	lua_State *L = test_state;
	static uint8_t buf[STREAM_BUFFER_SIZE];
	struct luam_Sysprof_Options opt;
	struct luam_Sysprof_Counters counters = {};

	sysprof_test_configure(&opt, buf);
	assert_true(luaM_sysprof_start(L, &opt) == PROFILE_SUCCESS);
	assert_int_equal(ctx.on_stop_calls, 0);

	/* Let the next stream flush fail as if the disk is full. */
	ctx.fail = 1;
	assert_int_equal(kill(getpid(), SIGPROF), 0);

	/* The stream is stopped gracefully, without a crash. */
	errno = 0;
	assert_int_equal(luaM_sysprof_stop(L), PROFILE_ERRIO);
	assert_int_equal(errno, ENOSPC);

	/* Counters are still available. */
	assert_true(luaM_sysprof_report(&counters) == PROFILE_SUCCESS);
	assert_true(counters.samples >= 1);

	/* The profiler is stopped. */
	assert_int_equal(luaM_sysprof_stop(L), PROFILE_ERRRUN);

	return TEST_EXIT_SUCCESS;
}

static int sysprof_enospc_on_start(void *test_state)
{
	lua_State *L = test_state;
	static uint8_t buf[STREAM_BUFFER_SIZE];
	struct luam_Sysprof_Options opt;

	sysprof_test_configure(&opt, buf);
	/* The very first flush fails, so the prologue cannot be streamed. */
	ctx.fail = 1;
	errno = 0;
	assert_int_equal(luaM_sysprof_start(L, &opt), PROFILE_ERRIO);
	assert_int_equal(errno, ENOSPC);
	/* The start error path releases the profiler resources. */
	assert_int_equal(ctx.on_stop_calls, 1);

	/* The profiler is not running. */
	assert_int_equal(luaM_sysprof_stop(L), PROFILE_ERRRUN);

	return TEST_EXIT_SUCCESS;
}

#endif /* LJ_HASSYSPROF && !defined(LUAJIT_USE_VALGRIND) */

int main(void)
{
#if LUAJIT_USE_VALGRIND
	return skip_all("Disabled due to #10803");
#elif !LJ_HASSYSPROF
	return skip_all("Sysprof is disabled");
#else
	if (LUAJIT_OS != LUAJIT_OS_LINUX)
		return skip_all("Sysprof is implemented for Linux only");
	if (LUAJIT_TARGET != LUAJIT_ARCH_X86
	    && LUAJIT_TARGET != LUAJIT_ARCH_X64)
		return skip_all("Sysprof is implemented for x86_64 only");

	lua_State *L = utils_lua_init();

	const struct test_unit tgroup[] = {
		test_unit_def(sysprof_enospc_during_sampling),
		test_unit_def(sysprof_enospc_on_start)
	};
	const int test_result = test_run_group(tgroup, L);
	utils_lua_close(L);
	return test_result;
#endif /* LUAJIT_USE_VALGRIND */
}
