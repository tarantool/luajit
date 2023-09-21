#include "lua.h"
#include "luaconf.h"

#include "test.h"
#include "utils.h"

#include <stdlib.h>

/* XXX: Still need normal assert for sanity checks. */
#undef NDEBUG
#include <assert.h>

static lua_Alloc old_allocf = NULL;
static void *old_alloc_state = NULL;

/* Always OOM on reallocation (not on allocation). */
static void *allocf_null_realloc(void *ud, void *ptr, size_t osize,
				 size_t nsize)
{
	assert(old_allocf != NULL);
	if (ptr != NULL && osize < nsize)
		return NULL;
	else
		return old_allocf(ud, ptr, osize, nsize);
}

static void enable_allocinject(lua_State *L)
{
	assert(old_allocf == NULL);
	old_allocf = lua_getallocf(L, &old_alloc_state);
	lua_setallocf(L, allocf_null_realloc, old_alloc_state);
}

/* Restore the default allocator function. */
static void disable_allocinject(lua_State *L)
{
	assert(old_allocf != NULL);
	lua_setallocf(L, old_allocf, old_alloc_state);
	old_allocf = NULL;
	old_alloc_state = NULL;
}

static int checkstack_res = -1;

static int test_checkstack(lua_State *L)
{
	/*
	 * There is no stack overflow error, but the OOM error
	 * due to stack reallocation, before the patch.
	 */
	checkstack_res = lua_checkstack(L, LUAI_MAXCSTACK / 2);
	return 0;
}

static int oom_on_lua_checkstack(void *test_state)
{
	lua_State *L = test_state;
	/* Use fresh-new coroutine for stack manipulations. */
	lua_State *L1 = lua_newthread(L);

	enable_allocinject(L);
	/*
	 * `L1` should have enough space to `cpcall()` without
	 * stack reallocation.
	 */
	int status = lua_cpcall(L1, test_checkstack, NULL);
	disable_allocinject(L);

	assert_true(status == LUA_OK);
	assert_true(checkstack_res == 0);

	return TEST_EXIT_SUCCESS;
}

int main(void)
{
	lua_State *L = utils_lua_init();
	const struct test_unit tgroup[] = {
		test_unit_def(oom_on_lua_checkstack),
	};
	const int test_result = test_run_group(tgroup, L);
	utils_lua_close(L);
	return test_result;
}
